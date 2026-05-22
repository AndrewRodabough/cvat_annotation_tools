import argparse
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from run._annotation_cleanup import fetch_annotations, resolve_label_ids, strip_ids, update_annotations


def _remove_object_annotations(annotations: dict, label_ids: set[int]) -> tuple[dict, int, int]:
    shapes = annotations.get("shapes", []) or []
    tracks = annotations.get("tracks", []) or []

    kept_shapes = [shape for shape in shapes if int(shape.get("label_id", -1)) not in label_ids]
    kept_tracks = [track for track in tracks if int(track.get("label_id", -1)) not in label_ids]

    removed_shapes = len(shapes) - len(kept_shapes)
    removed_tracks = len(tracks) - len(kept_tracks)

    updated = {
        "version": annotations.get("version", 0),
        "tags": strip_ids(annotations.get("tags", []) or []),
        "shapes": strip_ids(kept_shapes),
        "tracks": strip_ids(kept_tracks),
    }
    return updated, removed_shapes, removed_tracks


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete a label's annotations for a CVAT task")
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
    updated, removed_shapes, removed_tracks = _remove_object_annotations(annotations, label_ids)

    print(f"Task {task_id}")
    print(f"  object name: {args.name}")
    print(f"  label ids: {sorted(label_ids)}")
    print(f"  shapes to remove: {removed_shapes}")
    print(f"  tracks to remove: {removed_tracks}")

    if args.dry_run:
        print("Dry run enabled. No changes were sent to CVAT.")
        return

    update_annotations(task_id, updated)
    print("Update complete. Matching shapes and tracks removed.")


if __name__ == "__main__":
    main()
