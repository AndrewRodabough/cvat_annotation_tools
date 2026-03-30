import shutil
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import Tk, filedialog
import cv2
from dotenv import load_dotenv
from pathlib import Path
import sys
import yaml

from upload_clip import upload_clip
from clip_trimming import make_clips_from_ranges
from crop_ui import CropUiConfig, ask_crop_roi
from cv_ui_common import restore_terminal_after_cv
from range_selection import ask_ranges_text, print_ranges
from range_preview_ui import PreviewUiConfig, ask_ranges_preview
from terminal_state import initialize_terminal_state_restore, restore_terminal_state

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_int_env_var
from utils.yaml_parse import need
from utils.video_data import get_video_dimensions, video_duration_seconds

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ID = get_int_env_var("PROJECT_ID")
CONFIG_PATH = project_root / "upload" / "config.yaml"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

SCRUBBER_HEIGHT = int(need("SCRUBBER_HEIGHT", cfg))
SCRUBBER_MARGIN = int(need("SCRUBBER_MARGIN", cfg))
OVERLAY_TEXT_SCALE = float(need("OVERLAY_TEXT_SCALE", cfg))
OVERLAY_TEXT_COLOR = tuple(need("OVERLAY_TEXT_COLOR", cfg))
OVERLAY_TEXT_OUTLINE_COLOR = tuple(need("OVERLAY_TEXT_OUTLINE_COLOR", cfg))
OVERLAY_TEXT_THICKNESS = int(need("OVERLAY_TEXT_THICKNESS", cfg))
OVERLAY_TEXT_OUTLINE_THICKNESS = int(need("OVERLAY_TEXT_OUTLINE_THICKNESS", cfg))
OVERLAY_LINE_START_Y = int(need("OVERLAY_LINE_START_Y", cfg))
OVERLAY_LINE_SPACING = int(need("OVERLAY_LINE_SPACING", cfg))
POPUP_WINDOW_DEFAULT_WIDTH = int(need("POPUP_WINDOW_DEFAULT_WIDTH", cfg))
POPUP_WINDOW_DEFAULT_HEIGHT = int(need("POPUP_WINDOW_DEFAULT_HEIGHT", cfg))

raw_video_extensions = need("VIDEO_EXTENSIONS", cfg)
if not isinstance(raw_video_extensions, list):
    raise ValueError("VIDEO_EXTENSIONS must be a list in config.yaml")

VIDEO_EXTENSIONS = [tuple(item) for item in raw_video_extensions]

PREVIEW_UI_CONFIG = PreviewUiConfig(
    scrubber_height=SCRUBBER_HEIGHT,
    scrubber_margin=SCRUBBER_MARGIN,
    overlay_text_scale=OVERLAY_TEXT_SCALE,
    overlay_text_color=OVERLAY_TEXT_COLOR,
    overlay_text_outline_color=OVERLAY_TEXT_OUTLINE_COLOR,
    overlay_text_thickness=OVERLAY_TEXT_THICKNESS,
    overlay_text_outline_thickness=OVERLAY_TEXT_OUTLINE_THICKNESS,
    overlay_line_start_y=OVERLAY_LINE_START_Y,
    overlay_line_spacing=OVERLAY_LINE_SPACING,
    popup_window_default_width=POPUP_WINDOW_DEFAULT_WIDTH,
    popup_window_default_height=POPUP_WINDOW_DEFAULT_HEIGHT,
)

CROP_UI_CONFIG = CropUiConfig(
    scrubber_height=SCRUBBER_HEIGHT,
    scrubber_margin=SCRUBBER_MARGIN,
    popup_window_default_width=POPUP_WINDOW_DEFAULT_WIDTH,
    popup_window_default_height=POPUP_WINDOW_DEFAULT_HEIGHT,
)


def _prompt_input(prompt: str) -> str:
    """Read prompt input robustly, with /dev/tty fallback when stdin gets detached."""
    try:
        return input(prompt)
    except EOFError:
        pass

    try:
        with open("/dev/tty", "r", encoding="utf-8", errors="ignore") as tty_in:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            return tty_in.readline().rstrip("\n")
    except OSError as exc:
        raise RuntimeError(f"Unable to read terminal input for prompt: {prompt}") from exc


initialize_terminal_state_restore()


def choose_videos() -> list[str]:
    root = Tk()
    root.withdraw()
    root.update()
    selected = filedialog.askopenfilenames(
        title="Select one or more videos for trim + CVAT upload",
        filetypes=VIDEO_EXTENSIONS,
    )
    root.destroy()
    return list(selected)


def _ask_ranges_for_video(video_path: str) -> list[tuple[float, float]] | None:
    duration = video_duration_seconds(video_path)
    print("\n" + "=" * 80)
    print(f"Video: {video_path}")
    if duration > 0:
        print(f"Duration: {duration:.2f}s")

    try:
        return ask_ranges_preview(
            video_path,
            duration,
            PREVIEW_UI_CONFIG,
            restore_terminal_state,
        )
    except (cv2.error, MemoryError) as e:
        if isinstance(e, MemoryError):
            print("⚠️  Out of memory during preview. Falling back to text range input.")
            print("   Tip: For very large 4K files, consider converting to 1080p first:")
            print("   ffmpeg -i input.mov -vf scale=1920:1080 -c:v libx264 -preset fast output.mp4")
        else:
            print("Preview window unavailable. Falling back to text range input.")
        return ask_ranges_text(video_path, duration, _prompt_input)


def _ask_resolution_choice(video_path: str) -> int | None:
    width, height = get_video_dimensions(video_path)
    longest_edge = max(width, height)

    # 1080p-or-smaller sources keep full resolution by default and skip the prompt.
    if longest_edge <= 1920:
        return None

    print("\nExtraction resolution for this video?")
    print(f"  source: {width}x{height}")
    print("  [Enter] keep full resolution")

    options: dict[str, int] = {}
    if longest_edge <= 2560:
        # 1440p class source: only offer downscale to 1080p.
        print("  1 = 1080p short edge")
        options["1"] = 1080
    else:
        print("  1 = 1440p short edge")
        print("  2 = 1080p short edge")
        options["1"] = 1440
        options["2"] = 1080

    choice = _prompt_input("Select resolution mode: ").strip().lower()
    if not choice:
        return None

    if choice in options:
        return options[choice]
    if choice in ("1080", "1080p"):
        return 1080
    if longest_edge > 2560 and choice in ("1440", "1440p"):
        return 1440

    print("Unknown choice; keeping full resolution.")
    return None


def _upload_clip_with_result_lock(
    clip_path: str,
    extraction_max_dimension: int | None,
    extraction_crop_rect: tuple[int, int, int, int] | None,
    results_lock: threading.Lock,
    upload_results: list[dict],
) -> None:
    result = upload_clip(
        clip_path,
        max_dimension=extraction_max_dimension,
        crop_rect=extraction_crop_rect,
        project_id=PROJECT_ID,
    )
    with results_lock:
        upload_results.append(result)
    if result["status"] == "success":
        print(f"  ✓ {Path(clip_path).name}: task_id={result['task_id']}")
    else:
        print(f"  ❌ {Path(clip_path).name}: {result['error']}")


def _process_video_and_queue_uploads(
    video_path: str,
    index: int,
    total_videos: int,
    temp_clips_root: str,
    executor: ThreadPoolExecutor,
    futures: list[Future],
    upload_results: list[dict],
    results_lock: threading.Lock,
    annotation_errors: list[str],
) -> None:
    print(f"\n[{index}/{total_videos}] Annotating: {Path(video_path).name}")
    try:
        ranges = _ask_ranges_for_video(video_path)
        if ranges is None:
            annotation_errors.append(f"{video_path}: skipped by user")
            return

        print_ranges(ranges)
        print(f"✓ Annotation complete for {Path(video_path).name}")

        # Ask operator preferences per video after range marking.
        clip_max_dimension = _ask_resolution_choice(video_path)
        clip_crop_rect = ask_crop_roi(
            video_path,
            _prompt_input,
            CROP_UI_CONFIG,
            restore_terminal_state,
        )

        # Trim clips in foreground (fast)
        try:
            print("Starting trim stage (this can take a few minutes for long/high-res clips)...")
            clips = make_clips_from_ranges(video_path, temp_clips_root, ranges)
            print(f"✓ Trimmed {len(clips)} clip(s) from {Path(video_path).name}")

            # Queue each clip for async upload
            for clip_path in clips:
                future = executor.submit(
                    _upload_clip_with_result_lock,
                    clip_path,
                    clip_max_dimension,
                    clip_crop_rect,
                    results_lock,
                    upload_results,
                )
                futures.append(future)
        except Exception as exc:
            print(f"❌ Failed to trim clips from {Path(video_path).name}: {exc}")

    except KeyboardInterrupt:
        annotation_errors.append(f"{video_path}: interrupted by user")
        print("Interrupted while annotating; skipping this video.")
    except Exception as exc:
        annotation_errors.append(f"{video_path}: {exc}")


def _wait_for_uploads(futures: list[Future]) -> None:
    if not futures:
        return

    print("\n" + "=" * 80)
    print("WAITING FOR BACKGROUND UPLOADS TO COMPLETE...")
    print("=" * 80)
    for i, future in enumerate(futures, start=1):
        future.result()
        print(f"  [{i}/{len(futures)}] uploads completed")


def _print_final_summary(
    videos: list[str],
    upload_results: list[dict],
    annotation_errors: list[str],
) -> None:
    success_count = sum(1 for r in upload_results if r["status"] == "success")
    failure_count = len(upload_results) - success_count

    print("\n" + "=" * 80)
    print("=== FINAL SUMMARY ===")
    print("=" * 80)
    print(f"Source videos:      {len(videos)}")
    print(f"Successful uploads: {success_count}")
    print(f"Failed uploads:     {failure_count}")

    if annotation_errors:
        print("\nAnnotation/prep errors:")
        for err in annotation_errors:
            print(f"- {err}")

    if failure_count:
        print("\nUpload failures:")
        for result in upload_results:
            if result["status"] == "failed":
                print(f"- {result['clip']}")
                print(f"  Error: {result['error']}")
                if "frames_dir" in result:
                    print(f"  Frames: {result['frames_dir']}")

def main() -> None:
    temp_clips_root = tempfile.mkdtemp(prefix="cvat_trimmed_clips_")
    try:
        videos = choose_videos()
        if not videos:
            print("No videos selected. Exiting.")
            return

        print(f"Selected {len(videos)} source videos. Project ID={PROJECT_ID}")

        # ============================================================================
        # PHASE 1 & 2: ANNOTATION + ASYNC PROCESSING
        # Annotate each video, then immediately trim and queue for upload
        # Uploads happen in background while you annotate the next video
        # ============================================================================
        print("\n" + "=" * 80)
        print("PHASE 1+2: ANNOTATION & ASYNC UPLOAD")
        print("Each video will be annotated, trimmed, and queued for upload")
        print("Uploads will happen in background while you annotate other videos")
        print("=" * 80)

        annotation_errors: list[str] = []
        upload_results: list[dict] = []
        results_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures: list[Future] = []

            for i, video_path in enumerate(videos, start=1):
                _process_video_and_queue_uploads(
                    video_path=video_path,
                    index=i,
                    total_videos=len(videos),
                    temp_clips_root=temp_clips_root,
                    executor=executor,
                    futures=futures,
                    upload_results=upload_results,
                    results_lock=results_lock,
                    annotation_errors=annotation_errors,
                )

            _wait_for_uploads(futures)

        _print_final_summary(videos, upload_results, annotation_errors)

    finally:
        restore_terminal_after_cv(restore_terminal_state)
        restore_terminal_state()
        shutil.rmtree(temp_clips_root, ignore_errors=True)


if __name__ == "__main__":
    main()    