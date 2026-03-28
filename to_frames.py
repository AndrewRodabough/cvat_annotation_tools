import cv2
import os
import shutil
import subprocess
from pathlib import Path
import argparse


PREFERRED_HWACCEL_ORDER = [
    "cuda",
    "qsv",
    "vaapi",
    "vdpau",
    "vulkan",
    "d3d11va",
    "dxva2",
    "videotoolbox",
    "drm",
    "opencl",
]

_AUTO_HWACCEL_MODE: str | None = None
_AUTO_HWACCEL_RESOLVED = False


def _is_disk_write_error(text: str) -> bool:
    lower = (text or "").lower()
    return (
        "disk quota exceeded" in lower
        or "no space left on device" in lower
        or "errno 122" in lower
        or "errno 28" in lower
    )


def _jpeg_quality_to_ffmpeg_qscale(jpeg_quality: int) -> int:
    quality = max(1, min(100, int(jpeg_quality)))
    # ffmpeg qscale: 2 (best) -> 31 (worst), inverse of 1..100 quality.
    return int(round(31 - (quality - 1) * (29 / 99)))


def _remove_existing_output_frames(output_dir: str, image_format: str) -> None:
    ext = "jpg" if image_format in ("jpg", "jpeg") else "png"
    out_path = Path(output_dir)
    for existing in out_path.glob(f"frame_*.{ext}"):
        existing.unlink(missing_ok=True)


def _get_ffmpeg_hwaccel_mode() -> str | None:
    """
    Returns ffmpeg hwaccel mode from environment.

    Environment variable:
      CVAT_FFMPEG_HWACCEL=auto|cuda|vaapi|qsv|none
    Default: auto
    """
    return _get_ffmpeg_hwaccel_mode_for_video(None)


def _list_ffmpeg_hwaccels() -> list[str]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-hwaccels"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []

    modes: list[str] = []
    for line in (proc.stdout or "").splitlines():
        text = line.strip().lower()
        if not text or text.endswith(":"):
            continue
        if text.isalpha() and text not in modes:
            modes.append(text)
    return modes


def _probe_hwaccel_mode(mode: str, input_video: str) -> bool:
    # Fast probe: decode a few frames to ensure mode actually works on this machine/video.
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
        input_video,
        "-map",
        "0:v:0",
        "-frames:v",
        "8",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def _auto_pick_hwaccel(input_video: str | None) -> str | None:
    available = _list_ffmpeg_hwaccels()
    if not available:
        return None

    candidates = [mode for mode in PREFERRED_HWACCEL_ORDER if mode in available]
    if not candidates:
        candidates = available

    if input_video is None:
        return candidates[0]

    for mode in candidates:
        if _probe_hwaccel_mode(mode, input_video):
            return mode
    return None


def _get_ffmpeg_hwaccel_mode_for_video(input_video: str | None) -> str | None:
    global _AUTO_HWACCEL_MODE
    global _AUTO_HWACCEL_RESOLVED

    env_value = os.getenv("CVAT_FFMPEG_HWACCEL")
    if env_value is not None:
        value = env_value.strip().lower()
        if value in ("", "none", "off", "false", "0", "disable", "disabled"):
            return None
        if value != "auto":
            return value
        # Explicit auto means fall through to detector below.

    if _AUTO_HWACCEL_RESOLVED:
        return _AUTO_HWACCEL_MODE

    _AUTO_HWACCEL_MODE = _auto_pick_hwaccel(input_video)
    _AUTO_HWACCEL_RESOLVED = True
    return _AUTO_HWACCEL_MODE


def _extract_frames_with_ffmpeg(
    input_video: str,
    output_dir: str,
    image_format: str,
    jpeg_quality: int,
    png_compression: int,
    frame_skip: int,
    max_dimension: int | None,
    crop_rect: tuple[int, int, int, int] | None,
) -> int:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not available")

    _remove_existing_output_frames(output_dir, image_format)

    output_ext = "jpg" if image_format in ("jpg", "jpeg") else "png"
    output_pattern = str(Path(output_dir) / f"frame_%06d.{output_ext}")

    filters: list[str] = []

    if crop_rect is not None:
        crop_x, crop_y, crop_w, crop_h = crop_rect
        if crop_w <= 0 or crop_h <= 0:
            raise ValueError("crop_rect width/height must be > 0")
        if crop_x < 0 or crop_y < 0:
            raise ValueError("crop_rect x/y must be >= 0")
        filters.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")

    if frame_skip > 1:
        filters.append(f"select='not(mod(n\\,{frame_skip}))'")

    if max_dimension is not None and int(max_dimension) > 0:
        dim = int(max_dimension)
        # Preserve aspect ratio, shrinking so the SHORT edge is at most `dim`.
        filters.append(
            f"scale='if(gte(iw,ih),-2,min(iw,{dim}))':'if(gte(iw,ih),min(ih,{dim}),-2)':flags=fast_bilinear"
        )

    def _build_cmd(hwaccel_mode: str | None) -> list[str]:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if hwaccel_mode is not None:
            cmd.extend(["-hwaccel", hwaccel_mode])
        cmd.extend([
            "-threads",
            "0",
            "-i",
            input_video,
        ])

        if filters:
            cmd.extend(["-vf", ",".join(filters)])
        if frame_skip > 1:
            cmd.extend(["-vsync", "vfr"])

        if output_ext == "jpg":
            qscale = _jpeg_quality_to_ffmpeg_qscale(jpeg_quality)
            cmd.extend(["-q:v", str(qscale)])
        else:
            compression = max(0, min(9, int(png_compression)))
            cmd.extend(["-compression_level", str(compression)])

        cmd.extend(["-start_number", "0", output_pattern])
        return cmd

    env_value = os.getenv("CVAT_FFMPEG_HWACCEL")
    env_mode = (env_value or "").strip().lower()
    auto_requested = env_value is None or env_mode == "auto"

    hwaccel_mode = _get_ffmpeg_hwaccel_mode_for_video(input_video)
    if hwaccel_mode is not None:
        source = "auto" if auto_requested else "env"
        print(f"ffmpeg hwaccel mode: {hwaccel_mode} ({source})")
    else:
        source = "auto" if auto_requested else "env"
        print(f"ffmpeg hwaccel mode: none ({source}, software decode)")

    primary_cmd = _build_cmd(hwaccel_mode)
    proc = subprocess.run(primary_cmd, capture_output=True, text=True)
    if proc.returncode != 0 and hwaccel_mode is not None:
        # Hardware acceleration can fail depending on ffmpeg build/driver availability.
        # Retry once with software ffmpeg before falling back to OpenCV.
        primary_stderr = (proc.stderr or "").strip()
        print("ffmpeg hwaccel failed, retrying ffmpeg without hwaccel...")
        retry_cmd = _build_cmd(None)
        retry_proc = subprocess.run(retry_cmd, capture_output=True, text=True)
        if retry_proc.returncode == 0:
            proc = retry_proc
        else:
            retry_stderr = (retry_proc.stderr or "").strip()
            raise RuntimeError(
                "ffmpeg extraction failed with and without hwaccel "
                f"(hwaccel_exit={proc.returncode}, software_exit={retry_proc.returncode}): "
                f"hwaccel_stderr={primary_stderr or '<empty>'}; "
                f"software_stderr={retry_stderr or '<empty>'}"
            )
    elif proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"ffmpeg extraction failed ({proc.returncode}): {stderr}")

    frame_count = len(list(Path(output_dir).glob(f"frame_*.{output_ext}")))
    if frame_count <= 0:
        raise RuntimeError("ffmpeg extraction produced no frames")
    return frame_count


def _extract_frames_with_opencv(
    input_video: str,
    output_dir: str,
    image_format: str,
    jpeg_quality: int,
    png_compression: int,
    frame_skip: int,
    max_dimension: int | None,
    crop_rect: tuple[int, int, int, int] | None,
) -> int:
    # Open the video file
    cap = cv2.VideoCapture(input_video)

    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {input_video}")

    video_frame_index = 0
    output_frame_count = 0

    while True:
        ret, frame = cap.read()

        if not ret:
            break

        if video_frame_index % frame_skip == 0:
            if crop_rect is not None:
                crop_x, crop_y, crop_w, crop_h = crop_rect
                if crop_w <= 0 or crop_h <= 0:
                    raise ValueError("crop_rect width/height must be > 0")
                if crop_x < 0 or crop_y < 0:
                    raise ValueError("crop_rect x/y must be >= 0")
                frame_h, frame_w = frame.shape[:2]
                x0 = min(max(0, crop_x), frame_w - 1)
                y0 = min(max(0, crop_y), frame_h - 1)
                x1 = min(frame_w, x0 + crop_w)
                y1 = min(frame_h, y0 + crop_h)
                if x1 <= x0 or y1 <= y0:
                    raise ValueError("crop_rect is outside frame bounds")
                frame = frame[y0:y1, x0:x1]

            if max_dimension is not None and int(max_dimension) > 0:
                max_dim = int(max_dimension)
                h, w = frame.shape[:2]
                shortest = min(h, w)
                if shortest > max_dim:
                    scale = max_dim / float(shortest)
                    new_w = max(2, int(round(w * scale)))
                    new_h = max(2, int(round(h * scale)))
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            if image_format in ("jpg", "jpeg"):
                output_path = os.path.join(output_dir, f"frame_{output_frame_count:06d}.jpg")
                ok = cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
            else:
                output_path = os.path.join(output_dir, f"frame_{output_frame_count:06d}.png")
                ok = cv2.imwrite(output_path, frame, [cv2.IMWRITE_PNG_COMPRESSION, png_compression])

            if not ok:
                raise RuntimeError(
                    "Failed to write extracted frame to disk. "
                    "This is usually due to disk space/quota limits or write permissions. "
                    f"Path: {output_path}"
                )

            output_frame_count += 1

        video_frame_index += 1

    cap.release()
    return output_frame_count

def video_to_frames(
    input_video: str,
    output_dir: str,
    image_format: str = "jpg",
    jpeg_quality: int = 95,
    png_compression: int = 0,
    frame_skip: int = 1,
    max_dimension: int | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
) -> int:
    """
    Decompose a video into individual image frames.
    
    Args:
        input_video: Path to the input video file
        output_dir: Path to the output directory for frames
        image_format: Output image format, "jpg" or "png"
        jpeg_quality: JPEG quality (1-100)
        png_compression: PNG compression (0-9), where 0 is no compression
        frame_skip: Extract every Nth frame (frame_skip=1 means all frames, frame_skip=4 means every 4th frame)
        max_dimension: Optionally resize frames so the shortest edge is at most this value
        crop_rect: Optional crop rectangle as (x, y, width, height)

    Returns:
        Number of extracted frames (after skipping)
    """
    image_format = image_format.lower().lstrip(".")
    if image_format not in ("jpg", "jpeg", "png"):
        raise ValueError("image_format must be one of: jpg, jpeg, png")
    
    frame_skip = max(1, int(frame_skip))

    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        output_frame_count = _extract_frames_with_ffmpeg(
            input_video=input_video,
            output_dir=output_dir,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
            png_compression=png_compression,
            frame_skip=frame_skip,
            max_dimension=max_dimension,
            crop_rect=crop_rect,
        )
    except Exception as ffmpeg_exc:
        if _is_disk_write_error(str(ffmpeg_exc)):
            raise RuntimeError(
                "Frame extraction failed due to disk space/quota limits while writing files. "
                f"Original error: {ffmpeg_exc}"
            ) from ffmpeg_exc
        print(f"ffmpeg extraction unavailable/failed, falling back to OpenCV: {ffmpeg_exc}")
        _remove_existing_output_frames(output_dir, image_format)
        output_frame_count = _extract_frames_with_opencv(
            input_video=input_video,
            output_dir=output_dir,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
            png_compression=png_compression,
            frame_skip=frame_skip,
            max_dimension=max_dimension,
            crop_rect=crop_rect,
        )

    print(f"Extracted {output_frame_count} frames (skipping every {frame_skip}) to {output_dir}")
    return output_frame_count

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frames from a video file")
    parser.add_argument("input_video", help="Path to the input video file")
    parser.add_argument("output_dir", help="Path to the output directory for frames")
    parser.add_argument(
        "--format",
        choices=["jpg", "jpeg", "png"],
        default="jpg",
        help="Image format for extracted frames",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=95,
        help="JPEG quality from 1 to 100",
    )
    parser.add_argument(
        "--png-compression",
        type=int,
        default=0,
        help="PNG compression from 0 to 9 (0 means no compression)",
    )
    parser.add_argument(
        "--frame-skip",
        type=int,
        default=1,
        help="Extract every Nth frame (1=all, 4=every 4th, etc.)",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=None,
        help="Resize extracted frames so the shortest edge is at most this value (e.g., 1080 or 1440)",
    )
    parser.add_argument("--crop-x", type=int, default=None, help="Crop origin X")
    parser.add_argument("--crop-y", type=int, default=None, help="Crop origin Y")
    parser.add_argument("--crop-width", type=int, default=None, help="Crop width")
    parser.add_argument("--crop-height", type=int, default=None, help="Crop height")
    
    args = parser.parse_args()
    crop_rect = None
    if None not in (args.crop_x, args.crop_y, args.crop_width, args.crop_height):
        crop_rect = (args.crop_x, args.crop_y, args.crop_width, args.crop_height)

    video_to_frames(
        args.input_video,
        args.output_dir,
        image_format=args.format,
        jpeg_quality=args.jpeg_quality,
        png_compression=args.png_compression,
        frame_skip=args.frame_skip,
        max_dimension=args.max_dimension,
        crop_rect=crop_rect,
    )