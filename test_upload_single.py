#!/usr/bin/env python3
"""Minimal test to debug CVAT frame upload"""
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path

SERVER = "http://localhost:8080"
EMAIL = "REDACTED_EMAIL"
PASSWORD = "REDACTED_PASSWORD"
PROJECT_ID = 4

def test_upload():
    auth = HTTPBasicAuth(EMAIL, PASSWORD)
    
    # Create task
    print("Creating task...")
    resp = requests.post(
        f"{SERVER}/api/tasks",
        auth=auth,
        json={"name": "test_task", "project_id": PROJECT_ID},
        timeout=60
    )
    print(f"Task creation: {resp.status_code}")
    if resp.status_code not in (200, 201):
        print(f"Error: {resp.text}")
        return
    
    task_id = resp.json()["id"]
    print(f"Created task {task_id}")
    
    # Find a frame from the last extraction
    frames_dir = Path("/tmp/cvat_frames_fxs11a3l")
    if not frames_dir.exists():
        print(f"Frames dir {frames_dir} not found")
        return
    
    frames = sorted(list(frames_dir.glob("*.jpg")))[:1]
    if not frames:
        print("No frames found")
        return
    
    frame_path = frames[0]
    print(f"Testing with frame: {frame_path}")
    print(f"Frame size: {frame_path.stat().st_size} bytes")
    
    # Upload single frame
    print("\nUploading single frame...")
    
    # Try with pre-read file data and indexed key
    print(f"\n  Trying with indexed key: client_files[0]")
    with open(frame_path, "rb") as f:
        file_data = f.read()
    files = {"client_files[0]": (frame_path.name, file_data, "image/jpeg")}
    data = {
        "image_quality": "100",
        "sorting_method": "lexicographical",
        "segment_size": "500",
        "overlap": "3",
        "frame_filter": "step=1",
        "use_zip_chunks": "false",
    }
    
    resp = requests.post(
        f"{SERVER}/api/tasks/{task_id}/data",
        auth=auth,
        data=data,
        files=files,
        timeout=60
    )

    print(f"    Response: {resp.status_code}")
    if resp.status_code in (200, 201, 202):
        try:
            body = resp.json()
            rq_id = body.get("rq_id")
            print(f"    Request ID: {rq_id}")
            if rq_id:
                # Check status
                for i in range(5):
                    status_resp = requests.get(
                        f"{SERVER}/api/requests/{rq_id}",
                        auth=auth,
                        timeout=30
                    )
                    status_body = status_resp.json()
                    status = status_body.get("status")
                    print(f"      Poll {i}: status={status}")
                    if status in ("failed", "error"):
                        print(f"        Error: {status_body.get('message')}")
                    if status in ("finished", "completed", "failed"):
                        break
                    import time
                    time.sleep(1)
        except Exception as e:
            print(f"    Error parsing response: {e}")
    else:
        print(f"    Response: {resp.text[:200]}")

if __name__ == "__main__":
    test_upload()
