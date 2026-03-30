import shutil
import subprocess
from pathlib import Path
from time import perf_counter


def _format_seconds(seconds: float) -> str:
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


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


def _build_trim_failure_message(
    copy_exc: subprocess.CalledProcessError,
    primary_exc: subprocess.CalledProcessError,
    retry_exc: subprocess.CalledProcessError,
) -> str:
    copy_err = (copy_exc.stderr or "").strip()
    primary_err = (primary_exc.stderr or "").strip()
    retry_err = (retry_exc.stderr or "").strip()
    return (
        "ffmpeg trim failed across copy + encode attempts. "
        f"copy_exit={copy_exc.returncode}, "
        f"primary_exit={primary_exc.returncode}, fallback_exit={retry_exc.returncode}.\n"
        f"Copy stderr:\n{copy_err or '<empty>'}\n"
        f"Primary stderr:\n{primary_err or '<empty>'}\n"
        f"Fallback stderr:\n{retry_err or '<empty>'}"
    )


def _trim_single_clip_with_fallback(
    video_path: str,
    clip_path: str,
    start_s: float,
    end_s: float,
) -> None:
    copy_cmd = _build_ffmpeg_trim_copy_cmd(video_path, clip_path, start_s, end_s)
    try:
        subprocess.run(copy_cmd, check=True, capture_output=True, text=True)
        return
    except subprocess.CalledProcessError as copy_exc:
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
            return
        except subprocess.CalledProcessError as primary_exc:
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
                return
            except subprocess.CalledProcessError as retry_exc:
                msg = _build_trim_failure_message(copy_exc, primary_exc, retry_exc)
                raise RuntimeError(msg) from retry_exc


def make_clips_from_ranges(
    video_path: str,
    work_dir: str,
    ranges: list[tuple[float, float]],
) -> list[str]:
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
        _trim_single_clip_with_fallback(video_path, clip_path, start_s, end_s)
        elapsed = perf_counter() - t0
        print(f"  ✓ Finished clip {i}/{total} in {elapsed:.1f}s")
        output_paths.append(clip_path)

    return output_paths
