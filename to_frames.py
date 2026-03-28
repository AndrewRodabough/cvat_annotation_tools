import cv2
import os
import shutil
import subprocess
from pathlib import Path
import argparse


def _jpeg_quality_to_ffmpeg_qscale(jpeg_quality: int) -> int:
    quality = max(1, min(100, int(jpeg_quality)))
    # ffmpeg qscale: 2 (best) -> 31 (worst), inverse of 1..100 quality.
    return int(round(31 - (quality - 1) * (29 / 99)))


def _remove_existing_output_frames(output_dir: str, image_format: str) -> None:
    ext = "jpg" if image_format in ("jpg", "jpeg") else "png"
    out_path = Path(output_dir)
    for existing in out_path.glob(f"frame_*.{ext}"):
        existing.unlink(missing_ok=True)


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

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_video,
    ]

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
        # Preserve aspect ratio, only shrink very large frames.
        filters.append(
            f"scale='if(gte(iw,ih),min(iw,{dim}),-2)':'if(gte(iw,ih),-2,min(ih,{dim}))':flags=fast_bilinear"
        )

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

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
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
                longest = max(h, w)
                if longest > max_dim:
                    scale = max_dim / float(longest)
                    new_w = max(2, int(round(w * scale)))
                    new_h = max(2, int(round(h * scale)))
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            if image_format in ("jpg", "jpeg"):
                output_path = os.path.join(output_dir, f"frame_{output_frame_count:06d}.jpg")
                cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
            else:
                output_path = os.path.join(output_dir, f"frame_{output_frame_count:06d}.png")
                cv2.imwrite(output_path, frame, [cv2.IMWRITE_PNG_COMPRESSION, png_compression])
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
        max_dimension: Optionally resize frames so the longest edge is at most this value
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
        help="Resize extracted frames so the longest edge is at most this value (e.g., 1920)",
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