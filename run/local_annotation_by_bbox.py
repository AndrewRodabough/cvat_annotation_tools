import argparse
import os
from pathlib import Path
import runpy
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ViTPose on existing CVAT rectangle tracks and write skeleton annotations back to the task"
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Override the PROJECT_ID value from .env (accepted for consistency)",
    )
    args, remaining = parser.parse_known_args()

    if args.project_id is not None:
        os.environ["PROJECT_ID"] = str(args.project_id)

    script_path = (
        Path(__file__).resolve().parents[1] / "annotation" / "annotate_bbox_tracks_with_vitpose.py"
    )
    sys.argv = [os.fspath(script_path), *remaining]
    runpy.run_path(os.fspath(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
