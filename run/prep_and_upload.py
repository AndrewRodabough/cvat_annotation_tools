from pathlib import Path
import argparse
import sys


repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from upload.prep_and_upload.gui.prep_and_upload_tool import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare and upload videos to CVAT")
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Override the PROJECT_ID value from .env",
    )
    args = parser.parse_args()
    main(project_id=args.project_id)