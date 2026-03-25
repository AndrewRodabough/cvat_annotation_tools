import requests
import json
from requests.auth import HTTPBasicAuth

# --- CONFIGURATION ---
MODEL_ID = "pth-mmpose-hrnet32"
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

def deep_inspect():
    url = f"{SERVER}/api/lambda/functions/{MODEL_ID}"
    response = requests.get(url, auth=AUTH)
    
    if response.status_code == 200:
        data = response.json()
        # This will print the full technical spec of the model
        print("--- FULL MODEL SPEC ---")
        print(json.dumps(data.get('labels', []), indent=2))
        
        # Check for 'spec' field which sometimes holds the real names
        if 'spec' in data:
            print("\n--- MODEL SPEC FIELD ---")
            print(data['spec'])
    else:
        print(f"Error {response.status_code}: {response.text}")

if __name__ == "__main__":
    deep_inspect()