from dataclasses import dataclass
from pathlib import Path
import time

import cv2

from cv_ui_common import draw_scrubber, restore_terminal_after_cv, suppress_stderr, time_from_scrubber_x
from range_selection import finalize_ranges


SCRUB_SEEK_THROTTLE_S = 0.12


@dataclass(frozen=True)
class PreviewUiConfig:
    scrubber_height: int
    scrubber_margin: int
    overlay_text_scale: float
    overlay_text_color: tuple[int, int, int]
    overlay_text_outline_color: tuple[int, int, int]
    overlay_text_thickness: int
    overlay_text_outline_thickness: int
    overlay_line_start_y: int
    overlay_line_spacing: int
    popup_window_default_width: int
    popup_window_default_height: int


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
    cfg: PreviewUiConfig,
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

    y = cfg.overlay_line_start_y
    for line in lines:
        cv2.putText(
            frame,
            line,
            (14, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            cfg.overlay_text_scale,
            cfg.overlay_text_outline_color,
            cfg.overlay_text_outline_thickness,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            line,
            (14, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            cfg.overlay_text_scale,
            cfg.overlay_text_color,
            cfg.overlay_text_thickness,
            cv2.LINE_AA,
        )
        y += cfg.overlay_line_spacing


def ask_ranges_preview(
    video_path: str,
    duration: float,
    cfg: PreviewUiConfig,
    restore_terminal_state,
) -> list[tuple[float, float]] | None:
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

        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)

        is_4k = frame_width >= 3840 or frame_height >= 2160
        is_large = file_size_mb > 500 or (is_4k and duration > 60)

        scale_factor = 1.0
        if is_large:
            if frame_width > 1920:
                scale_factor = 1920.0 / frame_width
            print(f"⚠️  Large video detected ({file_size_mb:.0f}MB, {frame_width}x{frame_height})")
            print(
                f"   Preview will be downscaled to {int(frame_width * scale_factor)}x"
                f"{int(frame_height * scale_factor)} for performance"
            )

        current_frame = 0
        positioned_frame = -1
        playing = True
        ranges: list[tuple[float, float]] = []
        mark_in: float | None = None
        mouse_state = {
            "dragging": False,
            "seek_requested": False,
            "seek_force": False,
            "seek_seconds": 0.0,
            "last_seek_apply_ts": 0.0,
            "scrubber": (0, 0, 0, 0),
        }

        window = f"Preview: {Path(video_path).name}"
        with suppress_stderr():
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                window,
                cfg.popup_window_default_width,
                cfg.popup_window_default_height,
            )

        def _on_mouse(event, x, y, flags, param):
            del flags
            del param
            x0, y0, x1, y1 = mouse_state["scrubber"]
            in_bar = x0 <= x <= x1 and y0 <= y <= y1

            if event == cv2.EVENT_LBUTTONDOWN and in_bar:
                mouse_state["dragging"] = True
                mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration, x0, x1)
                mouse_state["seek_requested"] = True
                mouse_state["seek_force"] = True
            elif event == cv2.EVENT_MOUSEMOVE and mouse_state["dragging"]:
                mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration, x0, x1)
                mouse_state["seek_requested"] = True
                mouse_state["seek_force"] = False
            elif event == cv2.EVENT_LBUTTONUP:
                if mouse_state["dragging"]:
                    mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration, x0, x1)
                    mouse_state["seek_requested"] = True
                    mouse_state["seek_force"] = True
                mouse_state["dragging"] = False

        cv2.setMouseCallback(window, _on_mouse)

        print("\nPreview controls:")
        print("  space play/pause | j/l -/+5s | ,/. -/+1 frame")
        print("  mouse drag on scrubber to seek")
        print("  i mark in | o mark out | d undo last | c clear")
        print("  Enter accept ranges | q skip this video")

        while True:
            current_frame = max(0, min(current_frame, total_frames - 1))

            if positioned_frame != current_frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
                positioned_frame = current_frame

            ret, frame = cap.read()
            if not ret:
                break

            positioned_frame = current_frame + 1 if playing else current_frame

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
                cfg,
            )
            mouse_state["scrubber"] = draw_scrubber(
                frame,
                now_s,
                duration,
                ranges,
                mark_in,
                cfg.scrubber_height,
                cfg.scrubber_margin,
            )
            with suppress_stderr():
                cv2.imshow(window, frame)

            delay_ms = max(1, int(1000 / fps)) if playing else 30
            with suppress_stderr():
                key = cv2.waitKey(delay_ms) & 0xFF

            if mouse_state["seek_requested"]:
                now_ts = time.monotonic()
                should_apply_seek = mouse_state["seek_force"] or (
                    now_ts - mouse_state["last_seek_apply_ts"] >= SCRUB_SEEK_THROTTLE_S
                )
                if should_apply_seek:
                    target_s = max(0.0, min(mouse_state["seek_seconds"], duration))
                    current_frame = int(round(target_s * fps))
                    playing = False
                    mouse_state["seek_requested"] = False
                    mouse_state["seek_force"] = False
                    mouse_state["last_seek_apply_ts"] = now_ts
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
                        ranges = finalize_ranges(ranges, duration)
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
                        ranges = finalize_ranges(ranges, duration)
                        start_f = int(round(start_s * fps))
                        end_f = int(round(end_s * fps))
                        print(
                            f"Auto-closed to end of video: {start_s:.3f}s - {end_s:.3f}s "
                            f"(frames {start_f}-{end_f})"
                        )
                    mark_in = None
                return finalize_ranges(ranges, duration)
            elif key in (ord("q"), 27):
                return None

        return finalize_ranges(ranges, duration)
    finally:
        cap.release()
        restore_terminal_after_cv(restore_terminal_state)
