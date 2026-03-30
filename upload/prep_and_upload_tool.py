import os
import re
import shutil
import subprocess
import tempfile
import threading
import termios
import atexit
from time import perf_counter
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from tkinter import Tk, filedialog
import cv2
from to_frames import video_to_frames
from dotenv import load_dotenv
from upload_videos import process_video_frames_for_upload
from pathlib import Path
import sys
import yaml

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.get_env import get_int_env_var, get_str_env_var

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)

PROJECT_ID = get_int_env_var("PROJECT_ID")
CONFIG_PATH = project_root / "upload" / "config.yaml"

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

def _need(name: str):
    if name not in cfg:
        raise ValueError(f"Missing required config key: {name}")
    return cfg[name]

TARGET_ANNOTATION_FPS = float(_need("TARGET_ANNOTATION_FPS"))
SEGMENT_SIZE = int(_need("SEGMENT_SIZE"))
SEGMENT_OVERLAP = int(_need("SEGMENT_OVERLAP"))
FAST_EXTRACT_MAX_DIMENSION = int(_need("FAST_EXTRACT_MAX_DIMENSION"))
UPLOAD_BATCH_SIZE = int(_need("UPLOAD_BATCH_SIZE"))

SCRUBBER_HEIGHT = int(_need("SCRUBBER_HEIGHT"))
SCRUBBER_MARGIN = int(_need("SCRUBBER_MARGIN"))
OVERLAY_TEXT_SCALE = float(_need("OVERLAY_TEXT_SCALE"))
OVERLAY_TEXT_COLOR = tuple(_need("OVERLAY_TEXT_COLOR"))
OVERLAY_TEXT_OUTLINE_COLOR = tuple(_need("OVERLAY_TEXT_OUTLINE_COLOR"))
OVERLAY_TEXT_THICKNESS = int(_need("OVERLAY_TEXT_THICKNESS"))
OVERLAY_TEXT_OUTLINE_THICKNESS = int(_need("OVERLAY_TEXT_OUTLINE_THICKNESS"))
OVERLAY_LINE_START_Y = int(_need("OVERLAY_LINE_START_Y"))
OVERLAY_LINE_SPACING = int(_need("OVERLAY_LINE_SPACING"))
POPUP_WINDOW_DEFAULT_WIDTH = int(_need("POPUP_WINDOW_DEFAULT_WIDTH"))
POPUP_WINDOW_DEFAULT_HEIGHT = int(_need("POPUP_WINDOW_DEFAULT_HEIGHT"))

raw_video_extensions = _need("VIDEO_EXTENSIONS")
if not isinstance(raw_video_extensions, list):
    raise ValueError("VIDEO_EXTENSIONS must be a list in config.yaml")

VIDEO_EXTENSIONS = [tuple(item) for item in raw_video_extensions]

_CAPTURED_TTY_STATE = None


def _quality_for_max_edge(max_edge: int) -> int:
    # User-configured quality tiers by output resolution.
    # >1440p -> 90, >1080p and <=1440p -> 92, <=1080p -> 96.
    if max_edge > 1440:
        return 90
    if max_edge > 1080:
        return 92
    return 96


def _get_tty_fd() -> tuple[int | None, bool]:
    """Return a tty file descriptor and whether caller should close it."""
    try:
        stdin_fd = sys.stdin.fileno()
        if os.isatty(stdin_fd):
            return stdin_fd, False
    except (AttributeError, OSError, ValueError):
        pass

    try:
        fd = os.open("/dev/tty", os.O_RDWR)
        return fd, True
    except OSError:
        return None, False


def _capture_terminal_state() -> None:
    global _CAPTURED_TTY_STATE
    fd, should_close = _get_tty_fd()
    if fd is None:
        return
    try:
        _CAPTURED_TTY_STATE = termios.tcgetattr(fd)
    except termios.error:
        _CAPTURED_TTY_STATE = None
    finally:
        if should_close:
            os.close(fd)


def _restore_terminal_state() -> None:
    fd, should_close = _get_tty_fd()
    try:
        if fd is not None and _CAPTURED_TTY_STATE is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, _CAPTURED_TTY_STATE)
                return
            except termios.error:
                pass
    finally:
        if should_close and fd is not None:
            os.close(fd)

    # Fallback: force sane terminal mode if termios restore failed.
    try:
        with open("/dev/tty", "r", encoding="utf-8", errors="ignore") as tty_in:
            subprocess.run(
                ["stty", "sane"],
                stdin=tty_in,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    except OSError:
        pass


@contextmanager
def _suppress_stderr():
    """Temporarily silence noisy native stderr output (Qt/OpenCV backend warnings)."""
    try:
        saved_stderr_fd = os.dup(2)
    except OSError:
        # If fd operations fail, continue without suppression.
        yield
        return

    devnull_fd = None
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull_fd, 2)
        yield
    finally:
        try:
            os.dup2(saved_stderr_fd, 2)
        finally:
            os.close(saved_stderr_fd)
            if devnull_fd is not None:
                os.close(devnull_fd)


def _restore_terminal_after_cv() -> None:
    """Close HighGUI windows and flush pending key events before terminal prompts."""
    with _suppress_stderr():
        cv2.destroyAllWindows()
        cv2.waitKey(1)
        cv2.waitKey(1)
    _restore_terminal_state()


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


_capture_terminal_state()
atexit.register(_restore_terminal_state)


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


def _time_to_seconds(value: str) -> float:
    v = value.strip()
    if not v:
        raise ValueError("Empty timestamp")

    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v)

    parts = v.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {value}")

    parts_f = [float(p) for p in parts]
    if len(parts_f) == 3:
        h, m, s = parts_f
    elif len(parts_f) == 2:
        h = 0.0
        m, s = parts_f
    else:
        h = 0.0
        m = 0.0
        s = parts_f[0]

    return h * 3600.0 + m * 60.0 + s


def _parse_ranges(raw: str) -> list[tuple[float, float]]:
    raw = raw.strip()
    if not raw:
        return []

    ranges: list[tuple[float, float]] = []
    for token in raw.split(","):
        piece = token.strip()
        if not piece:
            continue
        if "-" not in piece:
            raise ValueError(
                "Each range must look like start-end, e.g. 00:00:05-00:00:12"
            )
        start_s, end_s = piece.split("-", 1)
        start = _time_to_seconds(start_s)
        end = _time_to_seconds(end_s)
        if end <= start:
            raise ValueError(f"Range end must be greater than start: {piece}")
        ranges.append((start, end))

    return sorted(ranges, key=lambda x: x[0])


def _format_seconds(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def _video_duration_seconds(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {video_path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    finally:
        cap.release()

    if fps <= 0 or frames <= 0:
        return 0.0
    return frames / fps


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


def _get_video_dimensions(video_path: str) -> tuple[int, int]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file for dimension check: {video_path}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid dimensions detected for video: {video_path}")
    return width, height


def _frame_step_from_fps(fps: float, target_fps: float = TARGET_ANNOTATION_FPS) -> int:
    return max(1, int(round(fps / target_fps)))


def _build_ffmpeg_trim_cmd(
    src_path: str,
    dst_path: str,
    start_s: float,
    end_s: float,
    *,
    fallback: bool = False,
) -> list[str]:
    duration = max(0.001, end_s - start_s)

    # Lossless x264 can be unstable or extremely heavy for some large/high-bit-depth MOV sources.
    # Use high quality defaults first, then fall back to a lighter encode profile if needed.
    crf = "16" if not fallback else "20"
    preset = "veryfast" if not fallback else "ultrafast"
    threads = "0" if not fallback else "1"

    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_seconds(start_s),
        "-i",
        src_path,
        "-t",
        _format_seconds(duration),
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        crf,
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-threads",
        threads,
        "-movflags",
        "+faststart",
        dst_path,
    ]


def _build_ffmpeg_trim_copy_cmd(
    src_path: str,
    dst_path: str,
    start_s: float,
    end_s: float,
) -> list[str]:
    duration = max(0.001, end_s - start_s)
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        _format_seconds(start_s),
        "-i",
        src_path,
        "-t",
        _format_seconds(duration),
        "-map",
        "0:v:0",
        "-an",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        dst_path,
    ]


def _make_clips_from_ranges(video_path: str, work_dir: str, ranges: list[tuple[float, float]]) -> list[str]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required but not found in PATH")

    output_paths: list[str] = []
    stem = Path(video_path).stem

    if not ranges:
        output_paths.append(video_path)
        return output_paths

    total = len(ranges)
    for i, (start_s, end_s) in enumerate(ranges, start=1):
        clip_path = str(Path(work_dir) / f"{stem}_clip_{i:03d}.mp4")
        clip_duration = max(0.0, end_s - start_s)
        print(
            f"  Trimming clip {i}/{total}: {start_s:.3f}s -> {end_s:.3f}s "
            f"(duration {clip_duration:.1f}s)..."
        )
        t0 = perf_counter()
        # Fast path: stream-copy trim to avoid expensive 4K re-encode waits.
        copy_cmd = _build_ffmpeg_trim_copy_cmd(video_path, clip_path, start_s, end_s)
        try:
            subprocess.run(copy_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as copy_exc:
            copy_err = (copy_exc.stderr or "").strip()
            print("  Fast copy-trim failed; retrying with re-encode settings...")
            primary_cmd = _build_ffmpeg_trim_cmd(
                video_path,
                clip_path,
                start_s,
                end_s,
                fallback=False,
            )
            try:
                subprocess.run(primary_cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as primary_exc:
                primary_err = (primary_exc.stderr or "").strip()
                print("  Primary trim encode failed; retrying with fallback settings...")
                retry_cmd = _build_ffmpeg_trim_cmd(
                    video_path,
                    clip_path,
                    start_s,
                    end_s,
                    fallback=True,
                )
                try:
                    subprocess.run(retry_cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as retry_exc:
                    retry_err = (retry_exc.stderr or "").strip()
                    combined = (
                        "ffmpeg trim failed across copy + encode attempts. "
                        f"copy_exit={copy_exc.returncode}, "
                        f"primary_exit={primary_exc.returncode}, fallback_exit={retry_exc.returncode}.\n"
                        f"Copy stderr:\n{copy_err or '<empty>'}\n"
                        f"Primary stderr:\n{primary_err or '<empty>'}\n"
                        f"Fallback stderr:\n{retry_err or '<empty>'}"
                    )
                    raise RuntimeError(combined) from retry_exc
            elapsed = perf_counter() - t0
            print(f"  ✓ Finished clip {i}/{total} in {elapsed:.1f}s")
        output_paths.append(clip_path)

    return output_paths


def _finalize_ranges(ranges: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    if not ranges:
        return []

    normalized = []
    for start_s, end_s in ranges:
        if duration > 0:
            start_s = max(0.0, min(start_s, duration))
            end_s = max(0.0, min(end_s, duration))
        if end_s > start_s:
            normalized.append((start_s, end_s))

    normalized.sort(key=lambda x: x[0])

    merged: list[tuple[float, float]] = []
    for start_s, end_s in normalized:
        if not merged or start_s > merged[-1][1]:
            merged.append((start_s, end_s))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_s))
    return merged


def _ask_ranges_text(video_path: str, duration: float) -> list[tuple[float, float]]:
    duration = _video_duration_seconds(video_path)
    print("\n" + "=" * 80)
    print(f"Video: {video_path}")
    if duration > 0:
        print(f"Duration: {duration:.2f}s")
    print(
        "Enter keep-ranges as comma-separated start-end pairs. "
        "Examples: 5-15, 00:01:10-00:01:20, 75.5-81.2"
    )
    print("Leave blank to keep the full video.")

    raw = _prompt_input("Keep ranges: ")
    ranges = _parse_ranges(raw)
    return _finalize_ranges(ranges, duration)


def _draw_overlay(
    frame,
    video_name: str,
    now_s: float,
    duration_s: float,
    mark_in: float | None,
    ranges: list[tuple[float, float]],
    fps: float,
    current_frame: int,
    total_frames: int,
) -> None:
    now_frame = int(round(now_s * fps))
    duration_frame = max(0, total_frames - 1)
    lines = [
        f"{video_name}",
        f"time: {now_s:.2f}s / {duration_s:.2f}s",
        f"frame: {now_frame} / {duration_frame} (current_idx={current_frame})",
        "space=play/pause  j/l=-/+5s  ,/.=-/+1f",
        "i=mark in  o=mark out  d=undo last  c=clear",
        "enter=accept  q=skip video",
    ]
    if mark_in is not None:
        lines.append(f"current IN: {mark_in:.2f}s (f={int(round(mark_in * fps))})")
    lines.append(f"ranges: {len(ranges)}")

    y = OVERLAY_LINE_START_Y
    for line in lines:
        cv2.putText(
            frame,
            line,
            (14, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            OVERLAY_TEXT_SCALE,
            OVERLAY_TEXT_OUTLINE_COLOR,
            OVERLAY_TEXT_OUTLINE_THICKNESS,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            line,
            (14, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            OVERLAY_TEXT_SCALE,
            OVERLAY_TEXT_COLOR,
            OVERLAY_TEXT_THICKNESS,
            cv2.LINE_AA,
        )
        y += OVERLAY_LINE_SPACING


def _scrubber_geometry(frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    x0 = SCRUBBER_MARGIN
    x1 = max(x0 + 20, frame_width - SCRUBBER_MARGIN)
    y1 = max(SCRUBBER_HEIGHT + 10, frame_height - 10)
    y0 = y1 - SCRUBBER_HEIGHT
    return x0, y0, x1, y1


def _time_from_scrubber_x(x: int, duration: float, x0: int, x1: int) -> float:
    if duration <= 0 or x1 <= x0:
        return 0.0
    ratio = (x - x0) / float(x1 - x0)
    ratio = max(0.0, min(1.0, ratio))
    return ratio * duration


def _draw_scrubber(
    frame,
    now_s: float,
    duration_s: float,
    ranges: list[tuple[float, float]],
    mark_in: float | None,
) -> tuple[int, int, int, int]:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = _scrubber_geometry(w, h)

    cv2.rectangle(frame, (x0, y0), (x1, y1), (40, 40, 40), -1)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (180, 180, 180), 1)

    if duration_s > 0:
        for start_s, end_s in ranges:
            start_x = int(x0 + (start_s / duration_s) * (x1 - x0))
            end_x = int(x0 + (end_s / duration_s) * (x1 - x0))
            start_x = max(x0, min(x1, start_x))
            end_x = max(x0, min(x1, end_x))
            if end_x > start_x:
                cv2.rectangle(frame, (start_x, y0 + 2), (end_x, y1 - 2), (60, 140, 60), -1)

        if mark_in is not None:
            in_x = int(x0 + (mark_in / duration_s) * (x1 - x0))
            in_x = max(x0, min(x1, in_x))
            cv2.line(frame, (in_x, y0), (in_x, y1), (80, 180, 255), 2)

        now_x = int(x0 + (now_s / duration_s) * (x1 - x0))
        now_x = max(x0, min(x1, now_x))
        cv2.line(frame, (now_x, y0 - 4), (now_x, y1 + 4), (0, 0, 255), 2)

    cv2.putText(
        frame,
        "Scrubber: click/drag to seek",
        (x0, y0 - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return x0, y0, x1, y1


def _ask_ranges_preview(video_path: str, duration: float) -> list[tuple[float, float]] | None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video for preview: {video_path}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 0:
            fps = 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames <= 0 and duration > 0:
            total_frames = max(1, int(duration * fps))
        if total_frames <= 0:
            total_frames = 1

        # Get video dimensions for optimization
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)

        # Detect if video is high resolution or large file
        is_4k = frame_width >= 3840 or frame_height >= 2160
        is_large = file_size_mb > 500 or (is_4k and duration > 60)

        # For large/4K videos, downsample preview for performance
        scale_factor = 1.0
        if is_large:
            if frame_width > 1920:
                scale_factor = 1920.0 / frame_width
            print(f"⚠️  Large video detected ({file_size_mb:.0f}MB, {frame_width}x{frame_height})")
            print(f"   Preview will be downscaled to {int(frame_width * scale_factor)}x{int(frame_height * scale_factor)} for performance")

        current_frame = 0
        positioned_frame = -1
        playing = True
        ranges: list[tuple[float, float]] = []
        mark_in: float | None = None
        mouse_state = {
            "dragging": False,
            "seek_requested": False,
            "seek_seconds": 0.0,
            "scrubber": (0, 0, 0, 0),
        }

        window = f"Preview: {Path(video_path).name}"
        with _suppress_stderr():
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                window,
                POPUP_WINDOW_DEFAULT_WIDTH,
                POPUP_WINDOW_DEFAULT_HEIGHT,
            )

        def _on_mouse(event, x, y, flags, param):
            del flags
            del param
            x0, y0, x1, y1 = mouse_state["scrubber"]
            in_bar = x0 <= x <= x1 and y0 <= y <= y1

            if event == cv2.EVENT_LBUTTONDOWN and in_bar:
                mouse_state["dragging"] = True
                mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration, x0, x1)
                mouse_state["seek_requested"] = True
            elif event == cv2.EVENT_MOUSEMOVE and mouse_state["dragging"]:
                mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration, x0, x1)
                mouse_state["seek_requested"] = True
            elif event == cv2.EVENT_LBUTTONUP:
                if mouse_state["dragging"]:
                    mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration, x0, x1)
                    mouse_state["seek_requested"] = True
                mouse_state["dragging"] = False

        cv2.setMouseCallback(window, _on_mouse)

        print("\nPreview controls:")
        print("  space play/pause | j/l -/+5s | ,/. -/+1 frame")
        print("  mouse drag on scrubber to seek")
        print("  i mark in | o mark out | d undo last | c clear")
        print("  Enter accept ranges | q skip this video")

        while True:
            current_frame = max(0, min(current_frame, total_frames - 1))

            # Seeking on every iteration is very expensive for large 4K videos.
            # Only seek when the requested frame is not the next sequential frame.
            if positioned_frame != current_frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                positioned_frame = current_frame

            ret, frame = cap.read()
            if not ret:
                break

            positioned_frame = current_frame + 1

            # Downscale frame if needed for performance
            if scale_factor < 1.0:
                new_width = int(frame.shape[1] * scale_factor)
                new_height = int(frame.shape[0] * scale_factor)
                frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)

            now_s = current_frame / fps
            _draw_overlay(
                frame,
                Path(video_path).name,
                now_s,
                duration,
                mark_in,
                ranges,
                fps,
                current_frame,
                total_frames,
            )
            mouse_state["scrubber"] = _draw_scrubber(frame, now_s, duration, ranges, mark_in)
            with _suppress_stderr():
                cv2.imshow(window, frame)

            delay_ms = max(1, int(1000 / fps)) if playing else 30
            with _suppress_stderr():
                key = cv2.waitKey(delay_ms) & 0xFF

            if mouse_state["seek_requested"]:
                target_s = max(0.0, min(mouse_state["seek_seconds"], duration))
                current_frame = int(round(target_s * fps))
                playing = False
                mouse_state["seek_requested"] = False
                continue

            if key == 255:
                if playing:
                    current_frame += 1
                    if current_frame >= total_frames:
                        current_frame = total_frames - 1
                        playing = False
                continue

            if key == ord(" "):
                playing = not playing
            elif key == ord("j"):
                current_frame -= int(5 * fps)
                playing = False
            elif key == ord("l"):
                current_frame += int(5 * fps)
                playing = False
            elif key == ord(","):
                current_frame -= 1
                playing = False
            elif key == ord("."):
                current_frame += 1
                playing = False
            elif key == ord("i"):
                mark_in = now_s
                print(f"IN set at {mark_in:.3f}s (frame {int(round(mark_in * fps))})")
            elif key == ord("o"):
                if mark_in is None:
                    mark_in = now_s
                    print(
                        f"IN set at {mark_in:.3f}s (frame {int(round(mark_in * fps))}) "
                        "(press 'o' again to close range)"
                    )
                else:
                    start_s = min(mark_in, now_s)
                    end_s = max(mark_in, now_s)
                    if end_s > start_s:
                        ranges.append((start_s, end_s))
                        ranges = _finalize_ranges(ranges, duration)
                        start_f = int(round(start_s * fps))
                        end_f = int(round(end_s * fps))
                        print(
                            f"Added range: {start_s:.3f}s - {end_s:.3f}s "
                            f"(frames {start_f}-{end_f})"
                        )
                    mark_in = None
            elif key == ord("d"):
                if ranges:
                    removed = ranges.pop()
                    start_f = int(round(removed[0] * fps))
                    end_f = int(round(removed[1] * fps))
                    print(
                        f"Removed range: {removed[0]:.3f}s - {removed[1]:.3f}s "
                        f"(frames {start_f}-{end_f})"
                    )
            elif key == ord("c"):
                ranges.clear()
                mark_in = None
                print("Cleared all ranges")
            elif key in (13, 10):
                if mark_in is not None:
                    start_s = mark_in
                    end_s = duration
                    if end_s > start_s:
                        ranges.append((start_s, end_s))
                        ranges = _finalize_ranges(ranges, duration)
                        start_f = int(round(start_s * fps))
                        end_f = int(round(end_s * fps))
                        print(
                            f"Auto-closed to end of video: {start_s:.3f}s - {end_s:.3f}s "
                            f"(frames {start_f}-{end_f})"
                        )
                    mark_in = None
                return _finalize_ranges(ranges, duration)
            elif key in (ord("q"), 27):
                return None

        return _finalize_ranges(ranges, duration)
    finally:
        cap.release()
        _restore_terminal_after_cv()


def _ask_ranges_for_video(video_path: str) -> list[tuple[float, float]] | None:
    duration = _video_duration_seconds(video_path)
    print("\n" + "=" * 80)
    print(f"Video: {video_path}")
    if duration > 0:
        print(f"Duration: {duration:.2f}s")

    try:
        return _ask_ranges_preview(video_path, duration)
    except (cv2.error, MemoryError) as e:
        if isinstance(e, MemoryError):
            print("⚠️  Out of memory during preview. Falling back to text range input.")
            print("   Tip: For very large 4K files, consider converting to 1080p first:")
            print("   ffmpeg -i input.mov -vf scale=1920:1080 -c:v libx264 -preset fast output.mp4")
        else:
            print("Preview window unavailable. Falling back to text range input.")
        return _ask_ranges_text(video_path, duration)


def _print_ranges(ranges: list[tuple[float, float]]) -> None:
    if not ranges:
        print("Ranges: full video")
        return
    print("Ranges:")
    for idx, (start_s, end_s) in enumerate(ranges, start=1):
        print(f"  {idx}. {start_s:.3f}s -> {end_s:.3f}s")


def _ask_resolution_choice(video_path: str) -> int | None:
    width, height = _get_video_dimensions(video_path)
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


def _ask_crop_roi(video_path: str) -> tuple[int, int, int, int] | None:
    answer = _prompt_input("Crop this video before frame extraction? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Could not open video for crop selection; skipping crop.")
        return None

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 0:
            fps = 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        if total_frames <= 0:
            total_frames = 1

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if src_w <= 0 or src_h <= 0:
            print("Could not determine video dimensions; skipping crop.")
            return None

        scale = 1.0
        max_preview = 1920
        if max(src_w, src_h) > max_preview:
            scale = max_preview / float(max(src_w, src_h))

        current_frame = 0
        positioned_frame = -1
        playing = False
        crop_display_rect: tuple[int, int, int, int] | None = None
        duration_s = (total_frames - 1) / fps if total_frames > 1 else 0.0
        mouse_state = {
            "dragging": False,
            "seek_requested": False,
            "seek_seconds": 0.0,
            "scrubber": (0, 0, 0, 0),
        }
        window_name = f"Crop ROI: {Path(video_path).name}"

        print("\nCrop review controls:")
        print("  r set/update crop on current frame")
        print("  c clear crop")
        print("  space play/pause | j/l -/+5s | ,/. -/+1 frame")
        print("  mouse drag on scrubber to seek")
        print("  Enter accept crop | q skip crop")

        with _suppress_stderr():
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                window_name,
                POPUP_WINDOW_DEFAULT_WIDTH,
                POPUP_WINDOW_DEFAULT_HEIGHT,
            )

        def _on_mouse(event, x, y, flags, param):
            del flags
            del param
            x0, y0, x1, y1 = mouse_state["scrubber"]
            in_bar = x0 <= x <= x1 and y0 <= y <= y1

            if event == cv2.EVENT_LBUTTONDOWN and in_bar:
                mouse_state["dragging"] = True
                mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration_s, x0, x1)
                mouse_state["seek_requested"] = True
            elif event == cv2.EVENT_MOUSEMOVE and mouse_state["dragging"]:
                mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration_s, x0, x1)
                mouse_state["seek_requested"] = True
            elif event == cv2.EVENT_LBUTTONUP:
                if mouse_state["dragging"]:
                    mouse_state["seek_seconds"] = _time_from_scrubber_x(x, duration_s, x0, x1)
                    mouse_state["seek_requested"] = True
                mouse_state["dragging"] = False

        cv2.setMouseCallback(window_name, _on_mouse)

        while True:
            current_frame = max(0, min(current_frame, total_frames - 1))

            if positioned_frame != current_frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                positioned_frame = current_frame

            ret, frame = cap.read()
            if not ret or frame is None:
                break

            positioned_frame = current_frame + 1

            if scale < 1.0:
                disp_w = max(2, int(round(frame.shape[1] * scale)))
                disp_h = max(2, int(round(frame.shape[0] * scale)))
                display = cv2.resize(frame, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
            else:
                display = frame.copy()

            if crop_display_rect is not None:
                x, y, w, h = crop_display_rect
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 255), 2)

            time_s = current_frame / fps
            cv2.putText(
                display,
                f"frame {current_frame}/{total_frames - 1}  time {time_s:.2f}s",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                display,
                "r=set crop  c=clear  space=play  j/l=5s  ,/.=1f  enter=accept  q=skip",
                (12, 56),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            mouse_state["scrubber"] = _draw_scrubber(display, time_s, duration_s, [], None)

            with _suppress_stderr():
                cv2.imshow(window_name, display)

            delay_ms = max(1, int(1000 / fps)) if playing else 30
            with _suppress_stderr():
                key = cv2.waitKey(delay_ms) & 0xFF

            if mouse_state["seek_requested"]:
                target_s = max(0.0, min(mouse_state["seek_seconds"], duration_s))
                current_frame = int(round(target_s * fps))
                playing = False
                mouse_state["seek_requested"] = False
                continue

            if key == 255:
                if playing:
                    current_frame += 1
                    if current_frame >= total_frames:
                        current_frame = total_frames - 1
                        playing = False
                continue

            if key == ord(" "):
                playing = not playing
            elif key == ord("j"):
                current_frame -= int(5 * fps)
                playing = False
            elif key == ord("l"):
                current_frame += int(5 * fps)
                playing = False
            elif key == ord(","):
                current_frame -= 1
                playing = False
            elif key == ord("."):
                current_frame += 1
                playing = False
            elif key == ord("c"):
                crop_display_rect = None
                print("Crop cleared")
            elif key == ord("r"):
                with _suppress_stderr():
                    x, y, rw, rh = cv2.selectROI(
                        window_name,
                        display,
                        fromCenter=False,
                        showCrosshair=True,
                    )
                # selectROI installs its own mouse handler; restore scrubber callback after it returns.
                mouse_state["dragging"] = False
                cv2.setMouseCallback(window_name, _on_mouse)
                if rw > 0 and rh > 0:
                    crop_display_rect = (int(x), int(y), int(rw), int(rh))
                    print(f"Crop candidate set: x={x}, y={y}, w={rw}, h={rh}")
                else:
                    print("Crop selection cancelled")
            elif key in (13, 10):
                if crop_display_rect is None:
                    print("No crop selected; keeping full frame.")
                    return None

                x, y, rw, rh = crop_display_rect
                crop_x = int(round(x / scale))
                crop_y = int(round(y / scale))
                crop_w = int(round(rw / scale))
                crop_h = int(round(rh / scale))

                crop_x = max(0, min(crop_x, src_w - 1))
                crop_y = max(0, min(crop_y, src_h - 1))
                crop_w = max(1, min(crop_w, src_w - crop_x))
                crop_h = max(1, min(crop_h, src_h - crop_y))

                print(f"Crop selected: x={crop_x}, y={crop_y}, w={crop_w}, h={crop_h}")
                return (crop_x, crop_y, crop_w, crop_h)
            elif key in (ord("q"), 27):
                print("Crop skipped.")
                return None

        print("Could not complete crop selection; skipping crop.")
        return None
    finally:
        cap.release()
        _restore_terminal_after_cv()


def _upload_single_clip(
    clip_path: str,
    keep_temp_frames_on_failure: bool = True,
    max_dimension: int | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
) -> dict:
    clip_name = Path(clip_path).name
    temp_frames = tempfile.mkdtemp(prefix="cvat_frames_")
    try:
        fps = _get_video_fps(clip_path)
        width, height = _get_video_dimensions(clip_path)

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

        task_id = process_video_frames_for_upload(
            frame_dir=temp_frames,
            video_name=clip_name,
            project_id=PROJECT_ID,
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
            futures = []
            video_extract_options: dict[str, dict] = {}

            for i, video_path in enumerate(videos, start=1):
                print(f"\n[{i}/{len(videos)}] Annotating: {Path(video_path).name}")
                try:
                    ranges = _ask_ranges_for_video(video_path)
                    if ranges is None:
                        annotation_errors.append(f"{video_path}: skipped by user")
                        continue

                    _print_ranges(ranges)
                    print(f"✓ Annotation complete for {Path(video_path).name}")

                    # Ask operator preferences per video after range marking.
                    max_dimension = _ask_resolution_choice(video_path)
                    crop_rect = _ask_crop_roi(video_path)
                    video_extract_options[video_path] = {
                        "max_dimension": max_dimension,
                        "crop_rect": crop_rect,
                    }

                    # Trim clips in foreground (fast)
                    try:
                        print("Starting trim stage (this can take a few minutes for long/high-res clips)...")
                        clips = _make_clips_from_ranges(video_path, temp_clips_root, ranges)
                        print(f"✓ Trimmed {len(clips)} clip(s) from {Path(video_path).name}")

                        # Queue each clip for async upload
                        for clip_path in clips:
                            options = video_extract_options.get(video_path, {})
                            clip_max_dimension = options.get("max_dimension")
                            clip_crop_rect = options.get("crop_rect")

                            def upload_with_lock(
                                cp: str,
                                extraction_max_dimension: int | None,
                                extraction_crop_rect: tuple[int, int, int, int] | None,
                            ) -> None:
                                result = _upload_single_clip(
                                    cp,
                                    max_dimension=extraction_max_dimension,
                                    crop_rect=extraction_crop_rect,
                                )
                                with results_lock:
                                    upload_results.append(result)
                                if result["status"] == "success":
                                    print(f"  ✓ {Path(cp).name}: task_id={result['task_id']}")
                                else:
                                    print(f"  ❌ {Path(cp).name}: {result['error']}")

                            future = executor.submit(
                                upload_with_lock,
                                clip_path,
                                clip_max_dimension,
                                clip_crop_rect,
                            )
                            futures.append(future)

                    except Exception as exc:
                        print(f"❌ Failed to trim clips from {Path(video_path).name}: {exc}")

                except KeyboardInterrupt:
                    annotation_errors.append(f"{video_path}: interrupted by user")
                    print("Interrupted while annotating; skipping this video.")
                except Exception as exc:
                    annotation_errors.append(f"{video_path}: {exc}")

            # Wait for all uploads to complete
            if futures:
                print("\n" + "=" * 80)
                print("WAITING FOR BACKGROUND UPLOADS TO COMPLETE...")
                print("=" * 80)
                for i, future in enumerate(futures, start=1):
                    future.result()  # Wait for each upload to finish
                    print(f"  [{i}/{len(futures)}] uploads completed")

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
            for e in annotation_errors:
                print(f"- {e}")

        if failure_count:
            print("\nUpload failures:")
            for r in upload_results:
                if r["status"] == "failed":
                    print(f"- {r['clip']}")
                    print(f"  Error: {r['error']}")
                    if "frames_dir" in r:
                        print(f"  Frames: {r['frames_dir']}")

    finally:
        _restore_terminal_after_cv()
        _restore_terminal_state()
        shutil.rmtree(temp_clips_root, ignore_errors=True)


if __name__ == "__main__":
    main()