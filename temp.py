import requests
from requests.auth import HTTPBasicAuth

PROJECT_ID = 4
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

def deep_sniff():
    # We query the labels endpoint directly, filtered by project
    url = f"{SERVER}/api/labels?project_id={PROJECT_ID}"
    
    print(f"Querying: {url}")
    resp = requests.get(url, auth=AUTH)
    
    if resp.status_code != 200:
        print(f"Failed: {resp.status_code} - {resp.text}")
        return

    data = resp.json()
    # Paginated responses put results in a 'results' key
    labels = data.get('results', [])
    
    print(f"\n--- Detailed Labels for Project {PROJECT_ID} ---")
    if not labels:
        print("No labels found. Check if the project ID is correct or if labels are defined at the task level instead.")
        return

    for l in labels:
        name = l.get('name')
        l_id = l.get('id')
        print(f"\nPARENT LABEL: '{name}' (ID: {l_id})")
        
        sublabels = l.get('sublabels', [])
        if sublabels:
            print("  Sub-labels (Points):")
            for sl in sublabels:
                print(f"    - '{sl.get('name')}' (Internal ID: {sl.get('id')})")
        else:
            print("  No sub-labels found (this might not be a skeleton).")

if __name__ == "__main__":
    deep_sniff()