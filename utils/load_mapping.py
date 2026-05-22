import json
from pathlib import Path

def load_mapping(mapping_file: str) -> tuple[str, dict, str, dict]:
    mapping_path = Path(mapping_file)

    if not mapping_path.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")

    with mapping_path.open("r", encoding="utf-8") as f:
        raw_mapping = json.load(f)

    metadata = raw_mapping.get("metadata", {})
    function_name = metadata.get("name")
    if not function_name:
        raise ValueError(f"Mapping file is missing metadata.name: {mapping_path}")

    data = raw_mapping.get("data", {})
    nested_mapping: dict[str, dict[str, str]] = {}
    for model_label, sublabels in data.items():
        # Normalize several common shapes into a mapping of str->str:
        # - dict: {model_idx: task_idx}
        # - list/tuple: [task_idx, ...] -> {index: task_idx}
        # - scalar (str/int): single mapping -> {"0": task_idx}
        if isinstance(sublabels, dict):
            items = sublabels.items()
        elif isinstance(sublabels, (list, tuple)):
            items = enumerate(sublabels)
        else:
            items = [(0, sublabels)]

        nested_mapping[str(model_label)] = {str(k): str(v) for k, v in items}

    return function_name, nested_mapping, str(mapping_path), data
