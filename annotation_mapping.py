import requests
from requests.auth import HTTPBasicAuth

# --- CONFIGURATION ---
TASK_ID = 10
MODEL_ID = "pth-mmpose-hrnet32"
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

# Structured Mapping based on your provided image and UI payload
# Top level: Model Category | Internal: Model Sublabel -> Your Skeleton Point
RAW_MAPPING = {
    "body": {
        "1": "2", "4": "4", "5": "3", "6": "14", "7": "9", "8": "15", "9": "10", 
        "12": "25", "13": "22", "14": "26", "15": "23", "16": "27", "17": "24"
    },
    "hands": {
        "1": "16", "6": "17", "18": "18", "22": "11", "27": "13", "39": "12"
    },
    "feet": {
        "1": "38", "2": "37", "3": "34", "4": "32", "5": "31", "6": "28"
    }
}

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