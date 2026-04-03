import argparse
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_str_env_var


env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

SERVER = get_str_env_var("SERVER").rstrip("/")
EMAIL = get_str_env_var("EMAIL")
PASSWORD = get_str_env_var("PASSWORD")


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(EMAIL, PASSWORD)


def _fetch_annotations(task_id: int) -> dict:
    url = f"{SERVER}/api/tasks/{task_id}/annotations"
    resp = requests.get(url, auth=_auth(), timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch annotations for task {task_id} "
            f"({resp.status_code}): {resp.text}"
        )
    return resp.json()


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


def _remove_skeleton_shapes(annotations: dict) -> tuple[dict, int, int]:
    shapes = annotations.get("shapes", []) or []
    kept_shapes = [shape for shape in shapes if shape.get("type") != "skeleton"]

    removed = len(shapes) - len(kept_shapes)

    updated = {
        "version": annotations.get("version", 0),
        "tags": _strip_ids(annotations.get("tags", []) or []),
        "shapes": _strip_ids(kept_shapes),
        "tracks": _strip_ids(annotations.get("tracks", []) or []),
    }
    return updated, removed, len(shapes)


def _put_annotations(task_id: int, payload: dict) -> None:
    url = f"{SERVER}/api/tasks/{task_id}/annotations"
    resp = requests.put(url, auth=_auth(), json=payload, timeout=120)
    if resp.status_code not in (200, 201, 202, 204):
        raise RuntimeError(
            f"Failed to update annotations for task {task_id} "
            f"({resp.status_code}): {resp.text}"
        )


def _confirm_if_no_tracks(task_id: int, track_count: int) -> bool:
    if track_count > 0:
        return True

    print("WARNING: No tracks were found for this task.")
    answer = input(
        f"Task {task_id}: continue anyway and delete skeleton shapes? [y/N]: "
    ).strip().lower()
    return answer in ("y", "yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all skeleton shapes while preserving tracks for a CVAT task"
    )
    parser.add_argument("--task-id", type=int, required=True, help="CVAT task id")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be removed without updating CVAT",
    )
    args = parser.parse_args()

    task_id = int(args.task_id)
    annotations = _fetch_annotations(task_id)
    updated, removed_count, total_shapes = _remove_skeleton_shapes(annotations)

    print(f"Task {task_id}")
    print(f"  total shapes: {total_shapes}")
    print(f"  skeleton shapes to remove: {removed_count}")
    print(f"  shapes kept: {len(updated['shapes'])}")
    print(f"  tracks preserved: {len(updated['tracks'])}")

    if args.dry_run:
        print("Dry run enabled. No changes were sent to CVAT.")
        return

    if not _confirm_if_no_tracks(task_id=task_id, track_count=len(updated["tracks"])):
        print("Cancelled. No changes were sent to CVAT.")
        return

    _put_annotations(task_id, updated)
    print("Update complete. Skeleton shapes removed and tracks preserved.")


if __name__ == "__main__":
    main()