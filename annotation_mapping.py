import requests
from requests.auth import HTTPBasicAuth

# --- CONFIGURATION ---
TASK_ID = 12
MODEL_ID = "pth-mmpose-hrnet32"
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

# Structured Mapping based on your provided image and UI payload
# Top level: Model Category | Internal: Model Sublabel -> Your Skeleton Point
RAW_MAPPING = {
    "body": {
        "1": "3",   # nose
        "4": "5",   # l_ear
        "5": "1",   # r_ear
        "6": "11",  # l_shoulder
        "7": "6",   # r_shoulder
        "8": "12",  # l_elbow
        "9": "7",   # r_elbow
        "12": "23", # l_hip
        "13": "21", # r_hip
        "14": "27", # l_knee
        "15": "25", # r_knee
        "16": "28", # l_ankle
        "17": "26", # r_ankle
        # "18": "41" # Neck (Optional: Recommended for 3D pivot)
    },
    "hands": {
        "1": "13",  # l_wrist
        "6": "15",  # l_index_kn
        "18": "14", # l_pinky_kn
        "22": "8",   # r_wrist
        "27": "10",  # r_index_kn
        "39": "9"    # r_pinky_kn
    },
    "feet": {
        "1": "39",  # l_big_toe
        "2": "40",  # l_small_toe
        "3": "35",  # l_heel
        "4": "33",  # r_big_toe
        "5": "34",  # r_small_toe
        "6": "29"   # r_heel
    },
    "face": {
        "39": "4",  # l_inner_eye
        "42": "2"   # r_inner_eye
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