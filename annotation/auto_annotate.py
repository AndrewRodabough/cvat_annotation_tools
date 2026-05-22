import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from pathlib import Path
import argparse
import sys
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_str_env_var
from utils.load_mapping import load_mapping
from utils.yaml_parse import need

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

EMAIL = get_str_env_var("EMAIL")
PASSWORD = get_str_env_var("PASSWORD")
SERVER = get_str_env_var("SERVER")
AUTH = HTTPBasicAuth(EMAIL, PASSWORD)
CONFIG_PATH = project_root / "annotation" / "config.yaml"

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


def _build_nested_mapping(
    data: dict[str, dict[str, str]],
) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    final_mapping: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for model_label, sublabels in data.items():
        final_mapping[model_label] = {
            "name": SKELETON_LABEL,
            "attributes": {},
            "sublabels": {
                model_idx: {"name": task_idx, "attributes": {}}
                for model_idx, task_idx in sublabels.items()
            },
        }
    return final_mapping


def trigger_annotation(task_id, mapping_file):
    """queue auto annotation request for a given CVAT task and model with a specific mapping"""

    model_name, nested_mapping, mapping_path, raw_data = load_mapping(mapping_file)

    final_mapping = {}
    # If the original mapping contains a single group whose keys look like
    # model label names (non-numeric), lift those sublabels to top-level
    # entries so the payload matches model specs like YOLO (which list
    # 'person','bicycle',... at the top level).
    if len(raw_data) == 1:
        only_key = next(iter(raw_data))
        only_val = raw_data[only_key]
        if isinstance(only_val, dict):
            # check if subkeys are non-numeric strings -> likely model labels
            subkeys = list(only_val.keys())
            if subkeys and all(not str(k).isdigit() for k in subkeys):
                for model_label, task_idx in nested_mapping.get(only_key, {}).items():
                    final_mapping[model_label] = {
                        "name": str(task_idx),
                        "attributes": {},
                        "sublabels": {},
                    }
    # Fallback / normal behavior: preserve groups as model categories (e.g., body/hands)
    if not final_mapping:
        for model_label, original_sublabels in (raw_data.items()):
            # If the original mapping had a scalar/list for this model_label,
            # treat it as a direct mapping to a CVAT label (no sublabels).
            if not isinstance(original_sublabels, dict):
                single = nested_mapping.get(model_label, {})
                single_name = None
                if single:
                    single_name = next(iter(single.values()))
                final_mapping[model_label] = {
                    "name": single_name or str(original_sublabels),
                    "attributes": {},
                    "sublabels": {},
                }
            else:
                sublabels = nested_mapping.get(model_label, {})
                final_mapping[model_label] = {
                    "name": SKELETON_LABEL,
                    "attributes": {},
                    "sublabels": {
                        model_idx: {"name": task_idx, "attributes": {}}
                        for model_idx, task_idx in sublabels.items()
                    },
                }
    
    payload = {
        "function": model_name,
        "task": task_id,
        "mapping": final_mapping,
        "cleanup": True,
        "conv_mask_to_poly": False
    }
    
    url = f"{SERVER}/api/lambda/requests"
    print(f"Triggering {model_name} for Task {task_id} using mapping {mapping_path}")
    
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
    parser.add_argument("--mapping-file", type=str, required=True, help="Mapping file path")
    args = parser.parse_args()

    try:
        task_ids = _parse_task_ids(args.task_id)
    except ValueError as exc:
        parser.error(str(exc))

    for task_id in task_ids:
        trigger_annotation(task_id=task_id, mapping_file=args.mapping_file)