#!/usr/bin/env python3
"""Test uploading video file instead of individual frames"""
import requests
from requests.auth import HTTPBasicAuth
from pathlib import Path

SERVER = "http://localhost:8080"
EMAIL = "REDACTED_EMAIL"
PASSWORD = "REDACTED_PASSWORD"
PROJECT_ID = 4

def test_video_upload():
    auth = HTTPBasicAuth(EMAIL, PASSWORD)
    
    # Create task
    print("Creating task...")
    resp = requests.post(
        f"{SERVER}/api/tasks",
        auth=auth,
        json={"name": "test_video_task", "project_id": PROJECT_ID},
        timeout=60
    )
    print(f"Task creation: {resp.status_code}")
    if resp.status_code not in (200, 201):
        print(f"Error: {resp.text}")
        return
    
    task_id = resp.json()["id"]
    print(f"Created task {task_id}")
    
    # Find the trimmed video from the last run
    trimmed_videos = list(Path("/tmp").glob("cvat_trimmed_clips_*/solo_practice_clip_001.mp4"))
    if not trimmed_videos:
        print("No trimmed videos found")
        return
    
    video_path = trimmed_videos[-1]  # Get most recent
    print(f"\nTesting with video: {video_path}")
    print(f"Video size: {video_path.stat().st_size} bytes")
    
    # Upload video file
    print("\nUploading video file...")
    with open(video_path, "rb") as f:
        files = [("client_files", (video_path.name, f, "video/mp4"))]
        data = {
            "image_quality": "100",
            "sorting_method": "lexicographical",
            "segment_size": "500",
            "overlap": "3",
            "frame_filter": "step=4",
            "use_zip_chunks": "false",
        }
        
        resp = requests.post(
            f"{SERVER}/api/tasks/{task_id}/data",
            auth=auth,
            data=data,
            files=files,
            timeout=60
        )
    
    print(f"Upload response: {resp.status_code}")
    if resp.status_code in (200, 201, 202):
        try:
            body = resp.json()
            rq_id = body.get("rq_id")
            print(f"Request ID: {rq_id}")
            if rq_id:
                # Check status
                for i in range(10):
                    status_resp = requests.get(
                        f"{SERVER}/api/requests/{rq_id}",
                        auth=auth,
                        timeout=30
                    )
                    status_body = status_resp.json()
                    status = status_body.get("status")
                    print(f"Poll {i}: status={status}")
                    if status in ("failed", "error"):
                        print(f"  Error: {status_body.get('message')}")
                    if status in ("finished", "completed", "failed"):
                        break
                    import time
                    time.sleep(1)
        except Exception as e:
            print(f"Error parsing response: {e}")
    else:
        print(f"Response: {resp.text[:200]}")

if __name__ == "__main__":
    test_video_upload()
