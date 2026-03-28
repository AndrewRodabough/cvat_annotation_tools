#!/usr/bin/env python3
"""Check CVAT task creation with media inline"""
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path

SERVER = "http://localhost:8080"
EMAIL = "REDACTED_EMAIL"
PASSWORD = "REDACTED_PASSWORD"
PROJECT_ID = 4

def test_with_media_param():
    """Try creating task with media specified in payload"""
    auth = HTTPBasicAuth(EMAIL, PASSWORD)
    
    # Get a frame
    frames_dir = Path("/tmp/cvat_frames_8xc6mshe")
    if frames_dir.exists():
        frames = sorted(list(frames_dir.glob("*.jpg")))[:5]
    else:
        frames_dir = Path("/tmp/cvat_frames_fxs11a3l")
        frames = sorted(list(frames_dir.glob("*.jpg")))[:5]
    
    if not frames:
        print("No frames found")
        return
    
    print(f"Found {len(frames)} frames")
    print(f"First frame: {frames[0]}")
    
    # Create task AND upload data in one call
    print("\nCreating task with media upload in payload...")
    
    files = {}
    for i, frame_path in enumerate(frames):
        with open(frame_path, "rb") as f:
            files[f"client_files[{i}]"] = (frame_path.name, f.read(), "image/jpeg")
    
    data = {
        "name": "test_with_media",
        "project_id": str(PROJECT_ID),
        "image_quality": "100",
        "sorting_method": "lexicographical",
        "segment_size": "500",
        "overlap": "3",
        "frame_filter": "step=1",
    }
    
    resp = requests.post(
        f"{SERVER}/api/tasks",
        auth=auth,
        data=data,
        files=files,
        timeout=60
    )
    
    print(f"Response: {resp.status_code}")
    print(f"Response: {resp.text[:500]}")

if __name__ == "__main__":
    test_with_media_param()
