import requests
from requests.auth import HTTPBasicAuth
import json
from dotenv import load_dotenv
from pathlib import Path
import argparse
import sys
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_str_env_var
from utils.yaml_parse import need

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

EMAIL = get_str_env_var("EMAIL")
PASSWORD = get_str_env_var("PASSWORD")
SERVER = get_str_env_var("SERVER")
AUTH = HTTPBasicAuth(EMAIL, PASSWORD)
MAPPING_FILE_FOLDER = project_root / "annotation" / "mapping"
CONFIG_PATH = project_root / "upload" / "config.yaml"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

SKELETON_LABEL = need("SKELETON_LABEL", cfg)


def _parse_task_ids(raw_values: list[str]) -> list[int]:
    """parse task ids from command line arguments, allowing for both space and comma separation"""
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


def trigger_annotation(task_id, mapping_file):
    """queue auto annotation request for a given CVAT task and model with a specific mapping"""
    
    # Load the mapping from the JSON file
    mapping_path = Path(mapping_file)
    if not mapping_path.is_absolute():
        mapping_path = MAPPING_FILE_FOLDER / mapping_file
    
    with open(mapping_path, 'r') as f:
        RAW_MAPPING = json.load(f)

    METADATA = RAW_MAPPING.get("metadata", {})
    MODEL_NAME = METADATA.get("name")
    DATA = RAW_MAPPING.get("data", {})
    
    # Build the nested mapping structure the server requires
    final_mapping = {}
    for model_label, sublabels in DATA.items():
        final_mapping[model_label] = {
            "name": SKELETON_LABEL,
            "attributes": {},
            "sublabels": {
                model_idx: {"name": task_idx, "attributes": {}} 
                for model_idx, task_idx in sublabels.items()
            }
        }
    
    payload = {
        "function": MODEL_NAME,
        "task": task_id,
        "mapping": final_mapping,
        "cleanup": True,
        "conv_mask_to_poly": False
    }
    
    url = f"{SERVER}/api/lambda/requests"
    print(f"Triggering {MODEL_NAME} for Task {task_id} using mapping {mapping_path}")
    
    response = requests.post(url, auth=AUTH, json=payload)
    
    if response.status_code in [200, 201, 202]:
        print("Success! The request is accepted. Your dance skeletons are being generated.")
    else:
        print(f"Error {response.status_code}: {response.text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger CVAT annotation with SpinePose model")
    parser.add_argument(
        "--task-id",
        nargs="+",
        required=True,
        help="One or more CVAT task IDs (space or comma separated)",
    )
    parser.add_argument("--mapping-file", type=str, required=True, help="Mapping file name or path (default: spine_pose_mapping.json)")
    args = parser.parse_args()

    try:
        task_ids = _parse_task_ids(args.task_id)
    except ValueError as exc:
        parser.error(str(exc))

    for task_id in task_ids:
        trigger_annotation(task_id=task_id, mapping_file=args.mapping_file)