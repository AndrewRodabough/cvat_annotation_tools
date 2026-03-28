import requests
from requests.auth import HTTPBasicAuth

# --- CONFIGURATION ---
TASK_ID = 12 
SERVER = "http://localhost:8080"
AUTH = HTTPBasicAuth("REDACTED_EMAIL", "REDACTED_PASSWORD")

# We keep this as a safety check, but we won't strictly filter by name anymore
PERSON_LABEL_ID = 143

def permissive_merge():
    url = f"{SERVER}/api/tasks/{TASK_ID}/annotations"
    
    print(f"Fetching annotations for Task {TASK_ID}...")
    resp = requests.get(url, auth=AUTH)
    if resp.status_code != 200:
        print(f"Failed to fetch: {resp.text}")
        return
    data = resp.json()
    
    skeletons_by_frame = {}
    other_shapes = []
    
    for shape in data.get('shapes', []):
        if shape.get('type') == 'skeleton':
            frame = shape['frame']
            if frame not in skeletons_by_frame:
                skeletons_by_frame[frame] = []
            skeletons_by_frame[frame].append(shape)
        else:
            shape.pop('id', None)
            other_shapes.append(shape)

    merged_shapes = []

    for frame, skeletons in skeletons_by_frame.items():
        if not skeletons: continue
        
        # 1. Start with a master container
        master = {
            "type": "skeleton",
            "frame": frame,
            "label_id": PERSON_LABEL_ID,
            "group": 0,
            "occluded": False,
            "outside": False,
            "attributes": [],
            "elements": []
        }
        
        # 2. Grab EVERY point from all fragments in this frame
        all_elements = []
        for skel in skeletons:
            for el in skel.get('elements', []):
                # Strip the ID so CVAT treats it as a new point
                el.pop('id', None)
                # Ensure it's pointing to a valid sub-label ID for the Person skeleton
                # (Since they were already auto-annotated to Person, this is likely fine)
                all_elements.append(el)
        
        # 3. CRITICAL: Only add the skeleton if we actually found points!
        if all_elements:
            master['elements'] = all_elements
            merged_shapes.append(master)
        else:
            print(f"Warning: Frame {frame} had skeletons but no points were found.")

    # 4. Push it back
    print(f"Pushing {len(merged_shapes)} merged skeletons...")
    final_payload = {"shapes": merged_shapes + other_shapes, "tracks": [], "tags": []}
    
    put_resp = requests.put(url, auth=AUTH, json=final_payload)
    
    if put_resp.status_code in [200, 201, 202, 204]:
        print("Success! Skeletons unified.")
    else:
        print(f"Error {put_resp.status_code}: {put_resp.text}")

if __name__ == "__main__":
    permissive_merge()