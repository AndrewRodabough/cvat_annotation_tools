import argparse
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET


def _numeric_label_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill missing CVAT skeleton keypoints in an export XML"
    )
    parser.add_argument("--input", required=True, help="Path to the CVAT XML export")
    parser.add_argument(
        "--output",
        help="Path to write the sanitized XML. Defaults to <input>_sanitized.xml",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="Overwrite the input file instead of writing a new file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing an output file",
    )
    return parser.parse_args()


def _extract_required_labels(root: ET.Element) -> dict[str, list[str]]:
    labels_by_parent: dict[str, list[str]] = defaultdict(list)

    for label in root.findall("./meta/task/labels/label") + root.findall("./meta/job/labels/label"):
        label_name = label.findtext("name")
        parent_name = label.findtext("parent")
        label_type = (label.findtext("type") or "").strip().lower()

        if not label_name or not parent_name:
            continue

        if label_type == "points":
            labels_by_parent[parent_name].append(label_name)

    return {parent: sorted(labels, key=_numeric_label_sort_key) for parent, labels in labels_by_parent.items()}


def _normalize_meta_container(root: ET.Element) -> None:
    meta = root.find("./meta")
    if meta is None:
        return

    task_meta = meta.find("./task")
    job_meta = meta.find("./job")
    if task_meta is None and job_meta is not None:
        job_meta.tag = "task"


def _build_frame_centers(root: ET.Element) -> dict[int, tuple[float, float]]:
    frame_centers: dict[int, tuple[float, float]] = {}
    for image in root.findall("./image"):
        frame_raw = image.get("id")
        width_raw = image.get("width")
        height_raw = image.get("height")
        if frame_raw is None or width_raw is None or height_raw is None:
            continue
        try:
            frame = int(frame_raw)
            width = float(width_raw)
            height = float(height_raw)
        except ValueError:
            continue
        frame_centers[frame] = (width / 2.0, height / 2.0)
    return frame_centers


def _parse_point_coordinates(points_value: str | None) -> tuple[float, float] | None:
    if not points_value:
        return None
    raw_parts = [part.strip() for part in points_value.split(",")]
    if len(raw_parts) < 2:
        return None
    try:
        return float(raw_parts[0]), float(raw_parts[1])
    except ValueError:
        return None


def _format_point_coordinates(x: float, y: float) -> str:
    return f"{x:.6f},{y:.6f}"


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not points:
        return None
    sum_x = sum(point[0] for point in points)
    sum_y = sum(point[1] for point in points)
    return sum_x / len(points), sum_y / len(points)


def _choose_fill_point(
    point_elements: list[ET.Element],
    frame: int,
    frame_centers: dict[int, tuple[float, float]],
) -> tuple[float, float]:
    present_points: list[tuple[float, float]] = []
    for point in point_elements:
        parsed = _parse_point_coordinates(point.get("points"))
        if parsed is not None:
            present_points.append(parsed)

    centroid = _centroid(present_points)
    if centroid is not None:
        return centroid

    if frame in frame_centers:
        return frame_centers[frame]

    return 0.0, 0.0


def _clone_point_template(
    point: ET.Element | None,
    label: str,
    coordinates: tuple[float, float],
) -> ET.Element:
    cloned = ET.Element("points")
    if point is not None:
        for key, value in point.attrib.items():
            if key != "label" and key != "points":
                cloned.set(key, value)

    cloned.set("label", label)
    cloned.set("points", _format_point_coordinates(*coordinates))
    cloned.set("outside", "1")
    cloned.set("occluded", "0")
    cloned.set("source", point.get("source", "manual") if point is not None else "manual")
    return cloned


def _move_label_attribute_first(point: ET.Element) -> None:
    label = point.get("label")
    if label is None:
        return

    ordered_attributes: dict[str, str] = {"label": label}
    for key, value in point.attrib.items():
        if key != "label":
            ordered_attributes[key] = value

    point.attrib.clear()
    point.attrib.update(ordered_attributes)


def _remove_keyframe_attribute(point: ET.Element) -> None:
    if "keyframe" in point.attrib:
        del point.attrib["keyframe"]


def _normalize_skeleton(
    skeleton: ET.Element,
    required_labels: list[str],
    frame_centers: dict[int, tuple[float, float]],
    frame_override: int | None = None,
) -> int:
    frame = frame_override
    if frame is None:
        frame_raw = skeleton.get("frame")
        if frame_raw is None:
            return 0

        try:
            frame = int(frame_raw)
        except ValueError:
            frame = -1

    existing_points = [child for child in list(skeleton) if child.tag == "points"]
    existing_by_label: dict[str, list[ET.Element]] = defaultdict(list)
    for point in existing_points:
        label = point.get("label")
        if label is not None:
            existing_by_label[label].append(point)

    fill_coordinates = _choose_fill_point(existing_points, frame, frame_centers)
    inserted = 0

    if not required_labels:
        return 0

    ordered_children: list[ET.Element] = []
    for label in required_labels:
        label_points = existing_by_label.get(label)
        if label_points:
            ordered_children.append(label_points.pop(0))
        else:
            template = existing_points[0] if existing_points else None
            ordered_children.append(_clone_point_template(template, label, fill_coordinates))
            inserted += 1

    def child_sort_key(point: ET.Element) -> tuple[int, int | str]:
        label = point.get("label")
        if label is None:
            return (2, "")
        return _numeric_label_sort_key(label)

    for label_points in existing_by_label.values():
        ordered_children.extend(label_points)

    ordered_children.sort(key=child_sort_key)

    for child in existing_points:
        skeleton.remove(child)
    for child in ordered_children:
        if child.tag == "points":
            _move_label_attribute_first(child)
            _remove_keyframe_attribute(child)
        skeleton.append(child)

    return inserted


def _normalize_skeletons_in_parent(
    parent: ET.Element,
    required_labels_by_parent: dict[str, list[str]],
    frame_centers: dict[int, tuple[float, float]],
    label_name: str,
) -> tuple[int, int]:
    required_labels = required_labels_by_parent.get(label_name)
    if not required_labels:
        return 0, 0

    inserted_total = 0
    normalized_count = 0
    for skeleton in parent.findall("./skeleton"):
        inserted = _normalize_skeleton(skeleton, required_labels, frame_centers)
        if inserted > 0:
            inserted_total += inserted
            normalized_count += 1
        else:
            normalized_count += 1

    return inserted_total, normalized_count


def sanitize_xml(
    input_path: Path,
    output_path: Path | None,
    inplace: bool,
    dry_run: bool,
) -> tuple[int, int]:
    tree = ET.parse(input_path)
    root = tree.getroot()

    _normalize_meta_container(root)

    required_labels_by_parent = _extract_required_labels(root)
    frame_centers = _build_frame_centers(root)

    inserted_total = 0
    normalized_skeletons = 0

    for track in root.findall("./track"):
        track_label = track.get("label")
        if not track_label:
            continue

        inserted_count, normalized_count = _normalize_skeletons_in_parent(
            parent=track,
            required_labels_by_parent=required_labels_by_parent,
            frame_centers=frame_centers,
            label_name=track_label,
        )
        inserted_total += inserted_count
        normalized_skeletons += normalized_count

    for image in root.findall("./image"):
        image_frame_raw = image.get("id")
        try:
            image_frame = int(image_frame_raw) if image_frame_raw is not None else None
        except ValueError:
            image_frame = None

        for skeleton in image.findall("./skeleton"):
            skeleton_label = skeleton.get("label")
            if not skeleton_label:
                continue

            required_labels = required_labels_by_parent.get(skeleton_label)
            if not required_labels:
                continue

            inserted_total += _normalize_skeleton(
                skeleton,
                required_labels,
                frame_centers,
                frame_override=image_frame,
            )
            normalized_skeletons += 1

    ET.indent(tree, space="  ")

    if inplace:
        target_path = input_path
    elif output_path is not None:
        target_path = output_path
    else:
        target_path = input_path.with_name(f"{input_path.stem}_sanitized{input_path.suffix}")

    if not dry_run:
        tree.write(target_path, encoding="utf-8", xml_declaration=True)
    return inserted_total, normalized_skeletons


def main() -> None:
    args = _parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input XML not found: {input_path}")

    output_path = Path(args.output) if args.output else None
    inserted_total, normalized_skeletons = sanitize_xml(
        input_path=input_path,
        output_path=output_path,
        inplace=bool(args.inplace),
        dry_run=bool(args.dry_run),
    )

    target_path = input_path if args.inplace else output_path
    if target_path is None:
        target_path = input_path.with_name(f"{input_path.stem}_sanitized{input_path.suffix}")

    print(f"Input: {input_path}")
    print(f"Output: {target_path}")
    print(f"Skeletons normalized: {normalized_skeletons}")
    print(f"Inserted keypoints: {inserted_total}")
    if args.dry_run:
        print("Dry run enabled. No file was written.")


if __name__ == "__main__":
    main()