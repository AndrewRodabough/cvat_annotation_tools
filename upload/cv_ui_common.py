import os
from contextlib import contextmanager

import cv2


@contextmanager
def suppress_stderr():
    """Temporarily silence noisy native stderr output (Qt/OpenCV backend warnings)."""
    try:
        saved_stderr_fd = os.dup(2)
    except OSError:
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


def restore_terminal_after_cv(restore_terminal_state) -> None:
    """Close HighGUI windows and flush pending key events before terminal prompts."""
    with suppress_stderr():
        cv2.destroyAllWindows()
        cv2.waitKey(1)
        cv2.waitKey(1)
    restore_terminal_state()


def scrubber_geometry(
    frame_width: int,
    frame_height: int,
    scrubber_height: int,
    scrubber_margin: int,
) -> tuple[int, int, int, int]:
    x0 = scrubber_margin
    x1 = max(x0 + 20, frame_width - scrubber_margin)
    y1 = max(scrubber_height + 10, frame_height - 10)
    y0 = y1 - scrubber_height
    return x0, y0, x1, y1


def time_from_scrubber_x(x: int, duration: float, x0: int, x1: int) -> float:
    if duration <= 0 or x1 <= x0:
        return 0.0
    ratio = (x - x0) / float(x1 - x0)
    ratio = max(0.0, min(1.0, ratio))
    return ratio * duration


def draw_scrubber(
    frame,
    now_s: float,
    duration_s: float,
    ranges: list[tuple[float, float]],
    mark_in: float | None,
    scrubber_height: int,
    scrubber_margin: int,
) -> tuple[int, int, int, int]:
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = scrubber_geometry(w, h, scrubber_height, scrubber_margin)

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
