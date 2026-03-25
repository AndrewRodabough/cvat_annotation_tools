import cv2
import os
from pathlib import Path
import argparse

def video_to_frames(input_video: str, output_dir: str) -> None:
    """
    Decompose a video into individual frames as high-quality JPGs.
    
    Args:
        input_video: Path to the input video file
        output_dir: Path to the output directory for frames
    """
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Open the video file
    cap = cv2.VideoCapture(input_video)
    
    if not cap.isOpened():
        raise ValueError(f"Cannot open video file: {input_video}")
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            break
        
        # Save frame as high-quality JPG (quality=95)
        output_path = os.path.join(output_dir, f"frame_{frame_count:06d}.jpg")
        cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        frame_count += 1
    
    cap.release()
    print(f"Extracted {frame_count} frames to {output_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frames from a video file")
    parser.add_argument("input_video", help="Path to the input video file")
    parser.add_argument("output_dir", help="Path to the output directory for frames")
    
    args = parser.parse_args()
    video_to_frames(args.input_video, args.output_dir)