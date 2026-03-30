from pathlib import Path
import sys
import tempfile
import shutil
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_int_env_var
from utils.video_data import get_video_fps, get_video_dimensions, video_duration_seconds
from utils.yaml_parse import need

from to_frames import video_to_frames
from upload_videos import process_video_frames_for_upload

CONFIG_PATH = project_root / "upload" / "config.yaml"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

TARGET_ANNOTATION_FPS = int(need("TARGET_ANNOTATION_FPS", cfg))
SEGMENT_SIZE = int(need("SEGMENT_SIZE", cfg))
SEGMENT_OVERLAP = int(need("SEGMENT_OVERLAP", cfg))

PROJECT_ID = get_int_env_var("PROJECT_ID")


def _frame_step_from_fps(fps: float, target_fps: float = TARGET_ANNOTATION_FPS) -> int:
    return max(1, int(round(fps / target_fps)))

def _quality_for_max_edge(max_edge: int) -> int:
    # User-configured quality tiers by output resolution.
    # >1440p -> 90, >1080p and <=1440p -> 92, <=1080p -> 96.
    if max_edge > 1440:
        return 90
    if max_edge > 1080:
        return 92
    return 96


def upload_clip(
    clip_path: str,
    keep_temp_frames_on_failure: bool = True,
    max_dimension: int | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
    project_id: int | None = None,
) -> dict:
    
    clip_name = Path(clip_path).name
    temp_frames = tempfile.mkdtemp(prefix="cvat_frames_")
    try:
        fps = get_video_fps(clip_path)
        width, height = get_video_dimensions(clip_path)

        base_width, base_height = width, height
        if crop_rect is not None:
            _, _, crop_w, crop_h = crop_rect
            base_width, base_height = crop_w, crop_h

        output_short_edge = max_dimension if max_dimension is not None else min(base_width, base_height)
        image_quality = _quality_for_max_edge(output_short_edge)
        frame_step = _frame_step_from_fps(fps)
        print(
            f"[{clip_name}] source fps={fps:.3f}, frame_step={frame_step} "
            f"(extracting every {frame_step} frames, target ~{TARGET_ANNOTATION_FPS} fps)"
        )
        if max_dimension is not None:
            out_width, out_height = base_width, base_height
            shortest = min(base_width, base_height)
            if shortest > max_dimension:
                scale = max_dimension / float(shortest)
                out_width = max(2, int(round(base_width * scale)))
                out_height = max(2, int(round(base_height * scale)))
            print(
                f"[{clip_name}] fast extract resize: {base_width}x{base_height} -> "
                f"{out_width}x{out_height} (short edge {max_dimension})"
            )
        print(f"[{clip_name}] quality tier: short_edge={output_short_edge} -> jpeg quality {image_quality}")

        video_to_frames(
            clip_path,
            temp_frames,
            image_format="jpg",
            jpeg_quality=image_quality,
            frame_skip=frame_step,
            max_dimension=max_dimension,
            crop_rect=crop_rect,
        )

        resolved_project_id = project_id
        if resolved_project_id is None:
            # Keep a resilient fallback even if module globals are altered during refactors.
            resolved_project_id = globals().get("PROJECT_ID")
        if resolved_project_id is None:
            resolved_project_id = get_int_env_var("PROJECT_ID")

        task_id = process_video_frames_for_upload(
            frame_dir=temp_frames,
            video_name=clip_name,
            project_id=int(resolved_project_id),
            frame_step=1,
            segment_size=SEGMENT_SIZE,
            overlap=SEGMENT_OVERLAP,
            image_quality=image_quality,
        )

        shutil.rmtree(temp_frames, ignore_errors=True)
        return {
            "status": "success",
            "clip": clip_path,
            "task_id": task_id,
            "fps": fps,
            "frame_step": frame_step,
            "extract_max_dimension": max_dimension,
            "crop_rect": crop_rect,
        }
    except Exception as exc:
        if not keep_temp_frames_on_failure:
            shutil.rmtree(temp_frames, ignore_errors=True)
        return {
            "status": "failed",
            "clip": clip_path,
            "error": str(exc),
            "frames_dir": temp_frames,
        }