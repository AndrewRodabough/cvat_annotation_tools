import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
import yaml
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_str_env_var
from utils.yaml_parse import need

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

SERVER = get_str_env_var("SERVER").rstrip("/")
EMAIL = get_str_env_var("EMAIL")
PASSWORD = get_str_env_var("PASSWORD")
MAPPING_FILE_FOLDER = project_root / "annotation" / "mapping"
CONFIG_PATH = project_root / "annotation" / "config.yaml"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

SKELETON_LABEL = need("SKELETON_LABEL", cfg)


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(EMAIL, PASSWORD)


def _parse_task_ids(raw_values: list[str]) -> list[int]:
    task_ids: list[int] = []
    for raw in raw_values:
        for part in raw.split(","):
            value = part.strip()
            if not value:
                continue
            try:
                task_ids.append(int(value))
            except ValueError as exc:
                raise ValueError(f"Invalid task id: {value}") from exc
    if not task_ids:
        raise ValueError("At least one task id is required")
    return task_ids


def _load_mapping(mapping_file: str) -> tuple[str, dict[str, str], str]:
    mapping_path = Path(mapping_file)
    candidate_paths = [mapping_path]
    if not mapping_path.is_absolute():
        candidate_paths.append(project_root / mapping_file)
        candidate_paths.append(MAPPING_FILE_FOLDER / mapping_path.name)

    for candidate_path in candidate_paths:
        if candidate_path.exists():
            mapping_path = candidate_path
            break
    else:
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    with mapping_path.open("r", encoding="utf-8") as f:
        raw_mapping = json.load(f)

    metadata = raw_mapping.get("metadata", {})
    function_name = metadata.get("name")
    if not function_name:
        raise ValueError(f"Mapping file is missing metadata.name: {mapping_path}")

    data = raw_mapping.get("data", {})
    model_to_task: dict[str, str] = {}
    for _, sublabels in data.items():
        for model_idx, task_idx in sublabels.items():
            model_to_task[str(model_idx)] = str(task_idx)

    return function_name, model_to_task, str(mapping_path)


def _strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_ids(val)
            for key, val in value.items()
            if key != "id"
        }
    if isinstance(value, list):
        return [_strip_ids(item) for item in value]
    return value


def _fetch_task(task_id: int) -> dict:
    url = f"{SERVER}/api/tasks/{task_id}"
    resp = requests.get(url, auth=_auth(), timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch task {task_id} ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def _fetch_annotations(task_id: int) -> dict:
    url = f"{SERVER}/api/tasks/{task_id}/annotations"
    resp = requests.get(url, auth=_auth(), timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch annotations for task {task_id} ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def _fetch_task_labels(task_info: dict, task_id: int) -> Any:
    labels = task_info.get("labels")
    if isinstance(labels, dict):
        labels_url = labels.get("url")
        if labels_url:
            resp = requests.get(labels_url, auth=_auth(), timeout=60)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict):
                    for key in ("results", "labels", "data"):
                        value = body.get(key)
                        if value:
                            return value
                    return body
                return body

    url = f"{SERVER}/api/labels"
    resp = requests.get(url, params={"task_id": task_id}, auth=_auth(), timeout=60)
    if resp.status_code == 200:
        body = resp.json()
        if isinstance(body, dict):
            for key in ("results", "labels", "data"):
                value = body.get(key)
                if value:
                    return value
            return body
        return body

    return labels


def _put_annotations(task_id: int, payload: dict) -> None:
    url = f"{SERVER}/api/tasks/{task_id}/annotations"
    resp = requests.put(url, auth=_auth(), json=payload, timeout=120)
    if resp.status_code not in (200, 201, 202, 204):
        raise RuntimeError(
            f"Failed to update annotations for task {task_id} ({resp.status_code}): {resp.text}"
        )


def _flatten_labels(labels: Any) -> dict[str, int]:
    result: dict[str, int] = {}

    def visit(items: Any) -> None:
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            label_id = item.get("id")
            if name is not None and label_id is not None:
                try:
                    result[str(name)] = int(label_id)
                except (TypeError, ValueError):
                    pass
            for child_key in ("sublabels", "labels", "children"):
                child_items = item.get(child_key)
                if child_items:
                    visit(child_items)

    visit(labels)
    return result


def _resolve_task_labels(task_info: dict) -> dict[str, int]:
    task_id = task_info.get("id")
    labels = _fetch_task_labels(task_info, int(task_id) if task_id is not None else 0)
    if labels:
        return _flatten_labels(labels)

    meta = task_info.get("meta")
    if isinstance(meta, dict):
        labels = meta.get("labels")
        if labels:
            return _flatten_labels(labels)

    return {}


def _ensure_label_id(
    candidate_label: str,
    task_label_id_lookup: dict[str, int],
) -> int | None:
    if candidate_label in task_label_id_lookup:
        return task_label_id_lookup[candidate_label]

    candidate_str = str(candidate_label)
    if candidate_str in task_label_id_lookup:
        return task_label_id_lookup[candidate_str]

    return None


def _is_rectangle_like(shape: dict) -> bool:
    shape_type = str(shape.get("type", "")).lower()
    return shape_type in {"rectangle", "bbox", "rect"}


def _iter_bbox_regions(annotations: dict) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []

    for shape in annotations.get("shapes", []) or []:
        if not isinstance(shape, dict) or not _is_rectangle_like(shape):
            continue
        points = shape.get("points") or []
        if len(points) < 4:
            continue
        regions.append(
            {
                "frame": int(shape.get("frame", 0)),
                "track_id": shape.get("track_id"),
                "label_id": shape.get("label_id"),
                "points": [float(points[0]), float(points[1]), float(points[2]), float(points[3])],
            }
        )

    for track in annotations.get("tracks", []) or []:
        if not isinstance(track, dict):
            continue
        track_id = track.get("id")
        label_id = track.get("label_id")
        for shape in track.get("shapes", []) or []:
            if not isinstance(shape, dict):
                continue
            if shape.get("outside"):
                continue
            if not _is_rectangle_like(shape):
                continue
            points = shape.get("points") or []
            if len(points) < 4:
                continue
            regions.append(
                {
                    "frame": int(shape.get("frame", 0)),
                    "track_id": track_id,
                    "label_id": label_id,
                    "points": [float(points[0]), float(points[1]), float(points[2]), float(points[3])],
                }
            )

    regions.sort(
        key=lambda item: (
            int(item["frame"]),
            int(item["track_id"]) if item.get("track_id") is not None else -1,
        )
    )
    return regions


def _group_regions_by_frame(regions: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for region in regions:
        frame = int(region["frame"])
        grouped.setdefault(frame, []).append(region)
    return grouped


def _download_frame_bytes(
    task_id: int,
    frame: int,
    frame_url_templates: list[str],
    fallback_frame_dir: str | None,
    task_info: dict,
) -> bytes:
    for template in frame_url_templates:
        url = template.format(task_id=task_id, frame=frame, SERVER=SERVER)
        resp = requests.get(url, auth=_auth(), timeout=60)
        content_type = resp.headers.get("content-type", "").lower()
        if resp.status_code == 200 and not content_type.startswith("application/json"):
            return resp.content

    if fallback_frame_dir:
        frame_dir = Path(fallback_frame_dir)
        if not frame_dir.exists():
            raise FileNotFoundError(f"Frame directory does not exist: {fallback_frame_dir}")

        candidate_names = [
            f"{frame}.jpg",
            f"{frame}.jpeg",
            f"{frame}.png",
            f"{frame:06d}.jpg",
            f"{frame:06d}.png",
        ]
        for candidate in candidate_names:
            path = frame_dir / candidate
            if path.exists():
                return path.read_bytes()

        data = task_info.get("data") if isinstance(task_info, dict) else None
        if isinstance(data, dict):
            data_name = data.get("name")
            if isinstance(data_name, str):
                path = frame_dir / data_name
                if path.exists():
                    return path.read_bytes()

    raise RuntimeError(
        f"Could not download frame {frame} for task {task_id}. Try --frame-url-template or --frame-dir."
    )


def _decode_image(image_bytes: bytes) -> np.ndarray:
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Unable to decode image bytes")
    return image


def _call_vitpose(function_url: str, image_bytes: bytes, regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = {
        "image": base64.b64encode(image_bytes).decode("ascii"),
        "regions": regions,
    }
    resp = requests.post(function_url, json=payload, timeout=180)
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"ViTPose request failed ({resp.status_code}): {resp.text}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"ViTPose response was not valid JSON: {resp.text}") from exc

    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("result"), list):
        return body["result"]
    raise RuntimeError(f"Unexpected ViTPose response shape: {body}")


def _prediction_to_shape(
    prediction: dict[str, Any],
    task_label_id_lookup: dict[str, int],
    model_to_task_point: dict[str, str],
    frame: int,
    track_id: int | None,
    fallback_skeleton_label: str,
) -> dict[str, Any]:
    skeleton_label_id = _ensure_label_id(fallback_skeleton_label, task_label_id_lookup)
    if skeleton_label_id is None:
        raise RuntimeError(
            f"Could not resolve skeleton label id for {fallback_skeleton_label!r}"
        )

    skeleton: dict[str, Any] = {
        "type": "skeleton",
        "frame": frame,
        "group": int(track_id) if track_id is not None else 0,
        "occluded": False,
        "outside": False,
        "attributes": [],
        "elements": [],
        "label": fallback_skeleton_label,
    }

    if skeleton_label_id is not None:
        skeleton["label_id"] = skeleton_label_id

    elements: list[dict[str, Any]] = []
    for element in prediction.get("elements", []) or []:
        label_name = str(element.get("label", ""))
        mapped_label = model_to_task_point.get(label_name)
        if mapped_label is None:
            continue

        label_id = _ensure_label_id(mapped_label, task_label_id_lookup)
        if label_id is None:
            continue

        points = element.get("points") or []
        if len(points) < 2:
            continue
        kp: dict[str, Any] = {
            "type": "points",
            "label": mapped_label,
            "frame": frame,
            "points": [float(points[0]), float(points[1])],
            "outside": False,
            "occluded": False,
            "attributes": [],
        }
        kp["label_id"] = label_id
        elements.append(kp)

    skeleton["elements"] = elements
    return skeleton


def _remove_existing_skeletons(annotations: dict) -> dict:
    shapes = annotations.get("shapes", []) or []
    kept_shapes = [shape for shape in shapes if str(shape.get("type", "")).lower() != "skeleton"]
    updated = {
        "version": annotations.get("version", 0),
        "tags": _strip_ids(annotations.get("tags", []) or []),
        "shapes": _strip_ids(kept_shapes),
        "tracks": _strip_ids(annotations.get("tracks", []) or []),
    }
    return updated


def _count_rectangle_shapes(annotations: dict) -> int:
    count = 0
    for shape in (annotations.get("shapes", []) or []):
        if _is_rectangle_like(shape):
            count += 1
    for track in (annotations.get("tracks", []) or []):
        for shape in (track.get("shapes", []) or []):
            if _is_rectangle_like(shape):
                count += 1
    return count


def _sanitize_no_unintended_deletions(
    original: dict,
    updated: dict,
    allow_remove_bboxes: bool,
    allow_remove_tracks: bool,
) -> None:
    orig_bbox_count = _count_rectangle_shapes(original)
    updated_bbox_count = _count_rectangle_shapes(updated)
    if updated_bbox_count < orig_bbox_count and not allow_remove_bboxes:
        raise RuntimeError(
            "Sanity check failed: rectangle (bbox) shapes were removed but --remove-bboxes was not set"
        )

    orig_tracks = len(original.get("tracks", []) or [])
    updated_tracks = len(updated.get("tracks", []) or [])
    if updated_tracks < orig_tracks and not allow_remove_tracks:
        raise RuntimeError(
            "Sanity check failed: tracks were removed but --remove-tracks was not set"
        )


def _run_task(
    task_id: int,
    mapping_file: str,
    function_url: str,
    frame_url_templates: list[str],
    fallback_frame_dir: str | None,
    replace_existing_skeletons: bool,
    remove_bboxes: bool,
    remove_tracks: bool,
    dry_run: bool,
) -> None:
    function_name, model_to_task_point, mapping_path = _load_mapping(mapping_file)
    task_info = _fetch_task(task_id)
    task_label_id_lookup = _resolve_task_labels(task_info)
    annotations = _fetch_annotations(task_id)
    regions = _iter_bbox_regions(annotations)
    grouped_regions = _group_regions_by_frame(regions)

    print(f"Task {task_id}")
    print(f"  mapping file: {mapping_path}")
    print(f"  function name: {function_name}")
    print(f"  bbox regions found: {len(regions)}")
    print(f"  frames with bboxes: {len(grouped_regions)}")
    print(f"  replace_existing_skeletons: {replace_existing_skeletons}")
    print(f"  remove_bboxes: {remove_bboxes}")
    print(f"  remove_tracks: {remove_tracks}")

    generated_shapes: list[dict[str, Any]] = []
    for frame in sorted(grouped_regions):
        frame_bytes = _download_frame_bytes(
            task_id=task_id,
            frame=frame,
            frame_url_templates=frame_url_templates,
            fallback_frame_dir=fallback_frame_dir,
            task_info=task_info,
        )
        _decode_image(frame_bytes)

        for region in grouped_regions[frame]:
            predictions = _call_vitpose(
                function_url=function_url,
                image_bytes=frame_bytes,
                regions=[{"points": region["points"]}],
            )
            if not predictions:
                continue
            for prediction in predictions:
                generated_shapes.append(
                    _prediction_to_shape(
                        prediction=prediction,
                        task_label_id_lookup=task_label_id_lookup,
                        model_to_task_point=model_to_task_point,
                        frame=frame,
                        track_id=region.get("track_id"),
                        fallback_skeleton_label=SKELETON_LABEL,
                    )
                )

    if replace_existing_skeletons:
        updated = _remove_existing_skeletons(annotations)
    else:
        updated = {
            "version": annotations.get("version", 0),
            "tags": _strip_ids(annotations.get("tags", []) or []),
            "shapes": _strip_ids(annotations.get("shapes", []) or []),
            "tracks": _strip_ids(annotations.get("tracks", []) or []),
        }

    # If removal of bboxes is requested, strip rectangle-like shapes from both
    # top-level shapes and shapes embedded in tracks. By default we preserve
    # all rectangle shapes.
    if remove_bboxes:
        kept_shapes = [s for s in updated.get("shapes", []) or [] if not _is_rectangle_like(s)]
        updated["shapes"] = kept_shapes
        kept_tracks = []
        for tr in updated.get("tracks", []) or []:
            new_shapes = [s for s in tr.get("shapes", []) or [] if not _is_rectangle_like(s)]
            tr = dict(tr)
            tr["shapes"] = new_shapes
            kept_tracks.append(tr)
        updated["tracks"] = kept_tracks

    # If removal of tracks is requested, clear the tracks list. By default we
    # preserve all tracks.
    if remove_tracks:
        updated["tracks"] = []

    # Append generated skeletons
    updated["shapes"] = list(updated.get("shapes", [])) + generated_shapes

    # Sanity check: ensure we did not remove bboxes/tracks unless explicitly allowed
    _sanitize_no_unintended_deletions(
        original=annotations,
        updated=updated,
        allow_remove_bboxes=bool(remove_bboxes),
        allow_remove_tracks=bool(remove_tracks),
    )

    print(f"  generated skeletons: {len(generated_shapes)}")

    if dry_run:
        print("Dry run enabled. No changes were sent to CVAT.")
        return

    _put_annotations(task_id, updated)
    print("Update complete. Skeleton annotations were written back to the task.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ViTPose on existing CVAT rectangle tracks and write skeleton annotations back to the task"
    )
    parser.add_argument(
        "--task-id",
        nargs="+",
        required=True,
        help="One or more CVAT task IDs (space or comma separated)",
    )
    parser.add_argument(
        "--mapping-file",
        type=str,
        required=True,
        help="Mapping file name or path used to translate model keypoints",
    )
    parser.add_argument(
        "--function-url",
        type=str,
        default=os.getenv("NUCLIO_FUNCTION_URL", ""),
        help="HTTP URL of the deployed Nuclio function",
    )
    parser.add_argument(
        "--frame-url-template",
        action="append",
        default=[],
        help="Frame download URL template. Use {task_id} and {frame} placeholders. Can be repeated.",
    )
    parser.add_argument(
        "--frame-dir",
        type=str,
        default=None,
        help="Optional local frame directory fallback if CVAT frame download is not available",
    )
    parser.add_argument(
        "--replace-existing-skeletons",
        action="store_true",
        help="Remove existing skeleton shapes before appending new predictions",
    )
    parser.add_argument(
        "--remove-bboxes",
        action="store_true",
        help="Allow removing rectangle (bbox) shapes before appending new predictions (default: preserve bboxes)",
    )
    parser.add_argument(
        "--remove-tracks",
        action="store_true",
        help="Allow removing existing tracks from the task (default: preserve tracks)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process frames and print counts without updating CVAT",
    )

    args = parser.parse_args()

    try:
        task_ids = _parse_task_ids(args.task_id)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.function_url:
        parser.error("--function-url is required, or set NUCLIO_FUNCTION_URL in the environment")

    frame_url_templates = args.frame_url_template or [
        f"{SERVER}/api/tasks/{{task_id}}/data?type=frame&number={{frame}}",
        f"{SERVER}/api/tasks/{{task_id}}/data?frame={{frame}}",
        f"{SERVER}/api/tasks/{{task_id}}/data/{{frame}}",
    ]

    for task_id in task_ids:
        _run_task(
            task_id=task_id,
            mapping_file=args.mapping_file,
            function_url=args.function_url,
            frame_url_templates=frame_url_templates,
            fallback_frame_dir=args.frame_dir,
            replace_existing_skeletons=args.replace_existing_skeletons,
            remove_bboxes=args.remove_bboxes,
            remove_tracks=args.remove_tracks,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()