import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


project_root = Path(__file__).resolve().parents[1]
env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)


def _get_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


SERVER = _get_env("SERVER").rstrip("/")
EMAIL = _get_env("EMAIL")
PASSWORD = _get_env("PASSWORD")
AUTH = HTTPBasicAuth(EMAIL, PASSWORD)


def fetch_annotations(task_id: int) -> dict[str, Any]:
    resp = requests.get(f"{SERVER}/api/tasks/{task_id}/annotations", auth=AUTH, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch annotations for task {task_id} ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def fetch_task_labels(task_id: int) -> Any:
    resp = requests.get(f"{SERVER}/api/labels?task_id={task_id}", auth=AUTH, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch labels for task {task_id} ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def strip_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_ids(val) for key, val in value.items() if key != "id"}
    if isinstance(value, list):
        return [strip_ids(item) for item in value]
    return value


def _extract_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("results", "labels", "data"):
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def _flatten_label_ids(labels: Any) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}

    def visit(items: Any) -> None:
        for item in _extract_items(items):
            name = item.get("name")
            label_id = item.get("id")
            if name is not None and label_id is not None:
                result.setdefault(str(name), set()).add(int(label_id))
            for child_key in ("sublabels", "labels", "children"):
                child_items = item.get(child_key)
                if child_items:
                    visit(child_items)

    visit(labels)
    return result


def resolve_label_ids(task_id: int, label_name: str) -> set[int]:
    labels = fetch_task_labels(task_id)
    label_lookup = _flatten_label_ids(labels)
    return set(label_lookup.get(str(label_name), set()))


def update_annotations(task_id: int, payload: dict[str, Any]) -> None:
    resp = requests.put(f"{SERVER}/api/tasks/{task_id}/annotations", auth=AUTH, json=payload, timeout=120)
    if resp.status_code not in (200, 201, 202, 204):
        raise RuntimeError(
            f"Failed to update annotations for task {task_id} ({resp.status_code}): {resp.text}"
        )
