import argparse
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

PREFERRED_ORDER = ["cuda", "qsv", "vaapi", "vdpau"]


@dataclass
class ProbeResult:
    mode: str
    ok: bool
    elapsed_s: float | None
    details: str


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def get_ffmpeg_hwaccels() -> list[str]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH")

    proc = _run(["ffmpeg", "-hide_banner", "-hwaccels"])
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg -hwaccels failed: {err}")

    modes: list[str] = []
    for line in (proc.stdout or "").splitlines():
        text = line.strip().lower()
        if not text or text.endswith(":"):
            continue
        if text.isalpha() and text not in modes:
            modes.append(text)
    return modes


def _probe_mode_with_video(mode: str, video_path: Path, timeout_s: int) -> ProbeResult:
    # Decode + lightweight scale to ensure actual hardware decoding path is exercised.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-hwaccel",
        mode,
        "-threads",
        "0",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-vf",
        "scale=640:-2:flags=fast_bilinear",
        "-f",
        "null",
        "-",
    ]

    started = time.perf_counter()
    try:
        proc = _run_with_timeout(cmd, timeout_s)
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - started
        return ProbeResult(mode=mode, ok=False, elapsed_s=elapsed, details=f"timeout after {timeout_s}s")

    elapsed = time.perf_counter() - started
    if proc.returncode == 0:
        return ProbeResult(mode=mode, ok=True, elapsed_s=elapsed, details=f"ok ({elapsed:.2f}s)")

    stderr = (proc.stderr or "").strip()
    return ProbeResult(mode=mode, ok=False, elapsed_s=elapsed, details=stderr or "ffmpeg returned non-zero exit")


def _run_with_timeout(cmd: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)


def pick_best_by_preference(available: list[str]) -> str | None:
    for mode in PREFERRED_ORDER:
        if mode in available:
            return mode
    return available[0] if available else None


def pick_best_by_benchmark(results: list[ProbeResult]) -> str | None:
    successful = [r for r in results if r.ok and r.elapsed_s is not None]
    if not successful:
        return None
    successful.sort(key=lambda r: (r.elapsed_s or 1e18, PREFERRED_ORDER.index(r.mode) if r.mode in PREFERRED_ORDER else 999))
    return successful[0].mode


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect and choose the best ffmpeg hardware acceleration mode for this machine."
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=None,
        help="Optional sample video path for real benchmark-based selection.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per hwaccel probe when --video is provided.",
    )
    args = parser.parse_args()

    try:
        available = get_ffmpeg_hwaccels()
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)

    print("Detected ffmpeg hwaccels:")
    if available:
        for mode in available:
            print(f"  - {mode}")
    else:
        print("  (none)")

    if not available:
        print("\nRecommended: CVAT_FFMPEG_HWACCEL=none")
        return

    if args.video is None:
        choice = pick_best_by_preference(available)
        print("\nNo sample video supplied; using preference-based choice.")
        print(f"Recommended: CVAT_FFMPEG_HWACCEL={choice}")
        return

    video_path = args.video.expanduser().resolve()
    if not video_path.exists():
        print(f"ERROR: sample video does not exist: {video_path}")
        raise SystemExit(2)

    if not video_path.is_file():
        print(f"ERROR: sample video is not a file: {video_path}")
        raise SystemExit(2)

    print(f"\nBenchmarking modes with sample: {video_path}")
    results: list[ProbeResult] = []
    for mode in available:
        result = _probe_mode_with_video(mode, video_path, args.timeout)
        results.append(result)
        status = "PASS" if result.ok else "FAIL"
        print(f"  [{status}] {mode}: {result.details}")

    choice = pick_best_by_benchmark(results)
    if choice is None:
        fallback = pick_best_by_preference(available)
        print("\nNo hwaccel mode passed benchmark; falling back to preference order.")
        print(f"Recommended: CVAT_FFMPEG_HWACCEL={fallback}")
        return

    print(f"\nRecommended: CVAT_FFMPEG_HWACCEL={choice}")


if __name__ == "__main__":
    main()
