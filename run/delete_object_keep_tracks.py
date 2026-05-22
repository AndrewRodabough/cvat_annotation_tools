import argparse
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from run._annotation_cleanup import fetch_annotations, resolve_label_ids, strip_ids, update_annotations


def _remove_object_shapes(annotations: dict, label_ids: set[int]) -> tuple[dict, int]:
    shapes = annotations.get("shapes", []) or []
    # Determine which tracks are preserved and keep any shapes that belong to those tracks
    tracks = annotations.get("tracks", []) or []
    preserved_track_ids = {track.get("id") for track in tracks}

    kept_shapes = []
    removed_shapes = 0
    for shape in shapes:
        try:
            shape_label = int(shape.get("label_id", -1))
        except Exception:
            shape_label = -1

        track_id = shape.get("track_id")

        # If the shape's label matches the label_ids we want to remove, but it
        # is part of a preserved track (directly linked by track_id), we keep it.
        if shape_label in label_ids:
            if track_id is not None and track_id in preserved_track_ids:
                kept_shapes.append(shape)
            else:
                removed_shapes += 1
            continue

        kept_shapes.append(shape)

    updated = {
        "shapes": kept_shapes,
        "tracks": strip_ids(annotations.get("tracks", []) or []),
    }
    return updated, removed_shapes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete a label's untracked annotations for a CVAT task, preserving tracks"
    )
    parser.add_argument("--task-id", type=int, required=True, help="CVAT task id")
    parser.add_argument("--name", required=True, help="Name of the object/label to delete")
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Override the PROJECT_ID value from .env (accepted for consistency)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be removed without updating CVAT",
    )
    args = parser.parse_args()

    del args.project_id

    task_id = int(args.task_id)
    label_ids = resolve_label_ids(task_id, args.name)
    if not label_ids:
        raise SystemExit(f"No label ids found for name {args.name!r}")

    annotations = fetch_annotations(task_id)
    updated, removed_shapes = _remove_object_shapes(annotations, label_ids)

    print(f"Task {task_id}")
    print(f"  object name: {args.name}")
    print(f"  label ids: {sorted(label_ids)}")
    print(f"  shapes to remove: {removed_shapes}")
    print(f"  tracks preserved: {len(updated['tracks'])}")

    if args.dry_run:
        print("Dry run enabled. No changes were sent to CVAT.")
        return

    update_annotations(task_id, updated)
    print("Update complete. Matching shapes removed and tracks preserved.")


if __name__ == "__main__":
    main()
