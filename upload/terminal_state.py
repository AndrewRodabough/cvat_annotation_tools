import atexit
import os
import subprocess
import sys
import termios

_CAPTURED_TTY_STATE = None


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


def capture_terminal_state() -> None:
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


def restore_terminal_state() -> None:
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


def initialize_terminal_state_restore() -> None:
    capture_terminal_state()
    atexit.register(restore_terminal_state)
