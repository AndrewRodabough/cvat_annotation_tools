import argparse
import mimetypes
import os
import time
from pathlib import Path
import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

project_root = Path(__file__).parent.parent

from utils.get_env import get_int_env_var, get_str_env_var


env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

SERVER = get_str_env_var("SERVER")
EMAIL = get_str_env_var("EMAIL")
PASSWORD = get_str_env_var("PASSWORD")
PROJECT_ID = get_int_env_var("PROJECT_ID")


def _auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(EMAIL, PASSWORD)


def create_task_for_video(task_name: str, project_id: int = PROJECT_ID) -> int:
    url = f"{SERVER}/api/tasks"
    payload = {
        "name": task_name,
        "project_id": project_id,
        "media_type": "image",
    }

    resp = requests.post(url, auth=_auth(), json=payload, timeout=60)
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Task creation failed ({resp.status_code}): {resp.text}"
        )

    data = resp.json()
    task_id = data.get("id")
    if task_id is None:
        raise RuntimeError(f"Task creation response missing id: {data}")
    return int(task_id)


def _collect_frame_paths(frame_dir: str) -> list[Path]:
    p = Path(frame_dir)
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Frame directory does not exist: {frame_dir}")

    frames = sorted(
        [
            *p.glob("*.jpg"),
            *p.glob("*.jpeg"),
            *p.glob("*.png"),
            *p.glob("*.bmp"),
            *p.glob("*.webp"),
        ]
    )
    if not frames:
        raise ValueError(f"No image frames found in: {frame_dir}")
    return frames


def _wait_for_request(rq_id: str, timeout_s: int = 1800, poll_s: int = 2) -> None:
    url = f"{SERVER}/api/requests/{rq_id}"
    deadline = time.time() + timeout_s

    while time.time() < deadline:
        resp = requests.get(url, auth=_auth(), timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Request status polling failed ({resp.status_code}): {resp.text}"
            )

        body = resp.json()
        status = str(body.get("status", "")).lower()
        print(f"  Request {rq_id} status: {status}")
        if status in ("finished", "completed", "success"):
            return
        if status in ("failed", "error"):
            message = body.get("message") or body.get("result") or body
            raise RuntimeError(f"CVAT request failed: {message}")

        time.sleep(poll_s)

    raise TimeoutError(f"Timed out waiting for CVAT request {rq_id}")


def upload_frames_to_task(
    task_id: int,
    frame_dir: str,
    frame_step: int = 1,
    segment_size: int = 500,
    overlap: int = 3,
    image_quality: int = 100,
    batch_size: int = 100,
) -> None:
    frames = _collect_frame_paths(frame_dir)
    url = f"{SERVER}/api/tasks/{task_id}/data"

    frame_step = max(1, int(frame_step))
    segment_size = max(1, int(segment_size))
    overlap = max(0, int(overlap))
    if overlap >= segment_size:
        overlap = max(0, segment_size - 1)
    image_quality = max(1, min(100, int(image_quality)))

    data = {
        "image_quality": str(image_quality),
        "sorting_method": "lexicographical",
        "segment_size": str(segment_size),
        "overlap": str(overlap),
        "frame_filter": f"step={frame_step}",
        "use_zip_chunks": "false",
    }

    # CVAT requires all frames in a single upload, not multiple batches
    print(f"  Uploading all {len(frames)} frames...")
    
    # Build files dict with indexed keys: client_files[0], client_files[1], etc
    files = {}
    for idx, frame_path in enumerate(frames):
        with open(frame_path, "rb") as f:
            file_data = f.read()
        files[f"client_files[{idx}]"] = (
            frame_path.name,
            file_data,
            "image/jpeg"
        )
    
    resp = requests.post(
        url,
        auth=_auth(),
        data=data,
        files=files,
        timeout=1800
    )

    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"Frame upload failed ({resp.status_code}): {resp.text}")

    rq_id = None
    try:
        body = resp.json()
        rq_id = body.get("rq_id")
    except ValueError:
        body = {}

    if rq_id:
        _wait_for_request(str(rq_id))


def process_video_frames_for_upload(
    frame_dir: str,
    video_name: str,
    project_id: int = PROJECT_ID,
    frame_step: int = 1,
    segment_size: int = 500,
    overlap: int = 3,
    image_quality: int = 100,
) -> int:
    task_name = f"{Path(video_name).stem}_{int(time.time())}"
    task_id = create_task_for_video(task_name=task_name, project_id=project_id)
    upload_frames_to_task(
        task_id=task_id,
        frame_dir=frame_dir,
        frame_step=frame_step,
        segment_size=segment_size,
        overlap=overlap,
        image_quality=image_quality,
    )
    return task_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create CVAT task and upload extracted video frames"
    )
    parser.add_argument("frame_dir", help="Directory containing extracted frames")
    parser.add_argument(
        "--video-name",
        required=True,
        help="Original video filename used for task naming",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=PROJECT_ID,
        help="CVAT project id",
    )
    parser.add_argument(
        "--frame-step",
        type=int,
        default=1,
        help="Frame sampling step applied by CVAT (step=N)",
    )
    parser.add_argument(
        "--segment-size",
        type=int,
        default=500,
        help="CVAT segment size",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=3,
        help="CVAT segment overlap",
    )
    parser.add_argument(
        "--image-quality",
        type=int,
        default=100,
        help="CVAT image quality (1-100)",
    )

    args = parser.parse_args()

    task_id = process_video_frames_for_upload(
        frame_dir=args.frame_dir,
        video_name=args.video_name,
        project_id=args.project_id,
        frame_step=args.frame_step,
        segment_size=args.segment_size,
        overlap=args.overlap,
        image_quality=args.image_quality,
    )
    print(f"Upload complete. task_id={task_id} frame_dir={os.path.abspath(args.frame_dir)}")


if __name__ == "__main__":
    main()