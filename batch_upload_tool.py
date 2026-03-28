import shutil
import tempfile
from pathlib import Path
from tkinter import Tk, filedialog

import cv2

from to_frames import video_to_frames
from upload_videos import PROJECT_ID, process_video_frames_for_upload


VIDEO_EXTENSIONS = [
    ("Video files", "*.mp4 *.mov *.avi *.mkv *.wmv *.m4v *.webm"),
    ("All files", "*.*"),
]

TARGET_ANNOTATION_FPS = 7.5
SEGMENT_SIZE = 500
SEGMENT_OVERLAP = 3
UPLOAD_IMAGE_QUALITY = 100


def _get_video_fps(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file for fps check: {video_path}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    finally:
        cap.release()

    if fps <= 0:
        raise ValueError(f"Invalid fps detected for video: {video_path}")
    return fps


def _frame_step_from_fps(fps: float, target_fps: float = TARGET_ANNOTATION_FPS) -> int:
    step = int(round(fps / target_fps))
    return max(1, step)


def choose_videos() -> list[str]:
    root = Tk()
    root.withdraw()
    root.update()
    selected = filedialog.askopenfilenames(
        title="Select one or more videos for CVAT upload",
        filetypes=VIDEO_EXTENSIONS,
    )
    root.destroy()
    return list(selected)


def _process_single_video(video_path: str) -> dict:
    video_name = Path(video_path).name
    temp_dir = tempfile.mkdtemp(prefix="cvat_frames_")

    try:
        fps = _get_video_fps(video_path)
        frame_step = _frame_step_from_fps(fps)

        print(
            f"[{video_name}] source fps={fps:.3f}, frame_step={frame_step} "
            f"(target ~{TARGET_ANNOTATION_FPS} fps)"
        )
        print(f"[{video_name}] extracting frames to {temp_dir}")
        video_to_frames(
            video_path,
            temp_dir,
            image_format="png",
            png_compression=0,
        )

        print(f"[{video_name}] creating CVAT task + uploading frames")
        task_id = process_video_frames_for_upload(
            frame_dir=temp_dir,
            video_name=video_name,
            project_id=PROJECT_ID,
            frame_step=frame_step,
            segment_size=SEGMENT_SIZE,
            overlap=SEGMENT_OVERLAP,
            image_quality=UPLOAD_IMAGE_QUALITY,
        )

        shutil.rmtree(temp_dir, ignore_errors=True)
        return {
            "video": video_path,
            "status": "success",
            "task_id": task_id,
            "fps": fps,
            "frame_step": frame_step,
        }
    except Exception as exc:
        return {
            "video": video_path,
            "status": "failed",
            "error": str(exc),
            "frames_dir": temp_dir,
        }


def main() -> None:
    videos = choose_videos()
    if not videos:
        print("No videos selected. Exiting.")
        return

    print(f"Selected {len(videos)} videos. Project ID={PROJECT_ID}")

    results = []
    for index, video in enumerate(videos, start=1):
        print(f"\n[{index}/{len(videos)}] Processing: {video}")
        result = _process_single_video(video)
        results.append(result)

        if result["status"] == "success":
            print(f"Success: task_id={result['task_id']}")
        else:
            print(f"Failed: {result['error']}")
            print(f"Frames retained for debugging: {result['frames_dir']}")

    success_count = sum(1 for r in results if r["status"] == "success")
    failure_count = len(results) - success_count

    print("\n=== Batch Summary ===")
    print(f"Total: {len(results)}")
    print(f"Success: {success_count}")
    print(f"Failed: {failure_count}")

    if failure_count:
        print("\nFailed videos:")
        for r in results:
            if r["status"] == "failed":
                print(f"- {r['video']}")
                print(f"  Error: {r['error']}")
                print(f"  Frames: {r['frames_dir']}")


if __name__ == "__main__":
    main()