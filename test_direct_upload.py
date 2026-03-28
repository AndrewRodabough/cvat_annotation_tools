#!/usr/bin/env python3
"""Test upload with a simple extracted frames directory"""
import sys
from pathlib import Path
from upload_videos import process_video_frames_for_upload, PROJECT_ID

# Use the last extracted frames as test
frames_dir = Path("/tmp/cvat_frames_fxs11a3l")
if not frames_dir.exists():
    frames_dir = Path("/tmp/cvat_frames_8xc6mshe")

if not frames_dir.exists():
    print("No frames directory found to test upload")
    sys.exit(1)

frames = list(frames_dir.glob("*.jpg"))
print(f"Found {len(frames)} frames in {frames_dir}")

# Test upload
try:
    print("\nStarting upload test...")
    task_id = process_video_frames_for_upload(
        frame_dir=str(frames_dir),
        video_name="test_upload.mov",
        project_id=PROJECT_ID,
        frame_step=1,
        segment_size=500,
        overlap=3,
        image_quality=100,
        batch_size=100,
    )
    print(f"\n✅ SUCCESS! Task created: {task_id}")
except Exception as e:
    print(f"\n❌ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
