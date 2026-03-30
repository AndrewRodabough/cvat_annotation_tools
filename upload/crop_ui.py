from dataclasses import dataclass
from pathlib import Path
import time

import cv2

from cv_ui_common import draw_scrubber, restore_terminal_after_cv, suppress_stderr, time_from_scrubber_x


SCRUB_SEEK_THROTTLE_S = 0.12


@dataclass(frozen=True)
class CropUiConfig:
    scrubber_height: int
    scrubber_margin: int
    popup_window_default_width: int
    popup_window_default_height: int


def ask_crop_roi(
    video_path: str,
    prompt_input,
    cfg: CropUiConfig,
    restore_terminal_state,
) -> tuple[int, int, int, int] | None:
    answer = prompt_input("Crop this video before frame extraction? [y/N]: ").strip().lower()
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
            "seek_force": False,
            "seek_seconds": 0.0,
            "last_seek_apply_ts": 0.0,
            "scrubber": (0, 0, 0, 0),
        }
        window_name = f"Crop ROI: {Path(video_path).name}"

        print("\nCrop review controls:")
        print("  r set/update crop on current frame")
        print("  c clear crop")
        print("  space play/pause | j/l -/+5s | ,/. -/+1 frame")
        print("  mouse drag on scrubber to seek")
        print("  Enter accept crop | q skip crop")

        with suppress_stderr():
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                window_name,
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
                mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration_s, x0, x1)
                mouse_state["seek_requested"] = True
                mouse_state["seek_force"] = True
            elif event == cv2.EVENT_MOUSEMOVE and mouse_state["dragging"]:
                mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration_s, x0, x1)
                mouse_state["seek_requested"] = True
                mouse_state["seek_force"] = False
            elif event == cv2.EVENT_LBUTTONUP:
                if mouse_state["dragging"]:
                    mouse_state["seek_seconds"] = time_from_scrubber_x(x, duration_s, x0, x1)
                    mouse_state["seek_requested"] = True
                    mouse_state["seek_force"] = True
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

            positioned_frame = current_frame + 1 if playing else current_frame

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
            mouse_state["scrubber"] = draw_scrubber(
                display,
                time_s,
                duration_s,
                [],
                None,
                cfg.scrubber_height,
                cfg.scrubber_margin,
            )

            with suppress_stderr():
                cv2.imshow(window_name, display)

            delay_ms = max(1, int(1000 / fps)) if playing else 30
            with suppress_stderr():
                key = cv2.waitKey(delay_ms) & 0xFF

            if mouse_state["seek_requested"]:
                now_ts = time.monotonic()
                should_apply_seek = mouse_state["seek_force"] or (
                    now_ts - mouse_state["last_seek_apply_ts"] >= SCRUB_SEEK_THROTTLE_S
                )
                if should_apply_seek:
                    target_s = max(0.0, min(mouse_state["seek_seconds"], duration_s))
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
            elif key == ord("c"):
                crop_display_rect = None
                print("Crop cleared")
            elif key == ord("r"):
                with suppress_stderr():
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
        restore_terminal_after_cv(restore_terminal_state)
