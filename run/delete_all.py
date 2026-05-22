import argparse
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from run._annotation_cleanup import fetch_annotations, strip_ids, update_annotations


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete all annotations for a CVAT task")
    parser.add_argument("--task-id", type=int, required=True, help="CVAT task id")
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Override the PROJECT_ID value from .env (accepted for consistency)",
    )
    args = parser.parse_args()

    del args.project_id

    task_id = int(args.task_id)
    annotations = fetch_annotations(task_id)
    updated = {
        "version": annotations.get("version", 0),
        "tags": [],
        "shapes": [],
        "tracks": [],
    }

    print(f"Task {task_id}")
    print(f"  total tags: {len(annotations.get('tags', []) or [])}")
    print(f"  total shapes: {len(annotations.get('shapes', []) or [])}")
    print(f"  total tracks: {len(annotations.get('tracks', []) or [])}")

    update_annotations(task_id, strip_ids(updated))
    print("Update complete. All annotations removed.")


if __name__ == "__main__":
    main()
