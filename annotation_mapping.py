import requests
from requests.auth import HTTPBasicAuth
import json

# --- CONFIGURATION ---
TASK_ID = 12
MODEL_ID = "pth-mmpose-hrnet32"
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

# Path to the mapping JSON file
MAPPING_FILE = "mapping.json"

# Load the mapping from the JSON file
with open(MAPPING_FILE, 'r') as f:
    RAW_MAPPING = json.load(f)

def trigger_dance_ai():
    # Build the nested mapping structure the server requires
    final_mapping = {}
    for model_label, sublabels in RAW_MAPPING.items():
        final_mapping[model_label] = {
            "name": "Person", # All model labels map to your Person skeleton
            "attributes": {},
            "sublabels": {
                model_idx: {"name": task_idx, "attributes": {}} 
                for model_idx, task_idx in sublabels.items()
            }
        }
    
    payload = {
        "function": MODEL_ID,
        "task": TASK_ID,
        "mapping": final_mapping,
        "cleanup": True,
        "conv_mask_to_poly": False
    }
    
    url = f"{SERVER}/api/lambda/requests"
    print(f"Triggering {MODEL_ID} for Task {TASK_ID} using nested mapping...")
    
    response = requests.post(url, auth=AUTH, json=payload)
    
    if response.status_code in [200, 201, 202]:
        print("Success! The request is accepted. Your dance skeletons are being generated.")
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    trigger_dance_ai()