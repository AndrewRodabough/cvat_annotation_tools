# CVAT Upload and Auto-Annotation Tools

This repo contains scripts to:
- Prepare dance videos for CVAT (trim, optional crop/downscale, frame extraction)
- Upload extracted frames as CVAT tasks
- Trigger server-side auto-annotation using a mapping file

## Requirements

- Python 3.10+
- ffmpeg available on PATH
- CVAT server running and reachable
- Python packages:

```bash
pip install requests python-dotenv opencv-python pyyaml
```

## Environment Setup (.env)

Create a file named `.env` in the repository root.

Required keys:

```env
SERVER=http://localhost:8080
EMAIL=your-cvat-email@example.com
PASSWORD=your-cvat-password
PROJECT_ID=4
```

Optional key:

```env
# auto (default), none, or a specific ffmpeg hwaccel mode (cuda, qsv, vaapi, ...)
CVAT_FFMPEG_HWACCEL=auto
```

What each key does:
- `SERVER`: Base URL for CVAT API requests.
- `EMAIL`: CVAT login email.
- `PASSWORD`: CVAT login password.
- `PROJECT_ID`: Default CVAT project ID used when creating tasks.
- `CVAT_FFMPEG_HWACCEL`: Controls ffmpeg decode acceleration during frame extraction.

## Config File

Runtime behavior for the prep/upload tool is controlled by [upload/config.yaml](upload/config.yaml).

This includes:
- Target annotation FPS
- Segment size and overlap
- Video picker extensions
- Preview/scrubber UI tuning values

## Using annotation/annotation_mapping.py

Script: [annotation/annotation_mapping.py](annotation/annotation_mapping.py)

Purpose:
- Sends a CVAT lambda request to run an auto-annotation model on an existing task.
- Translates model keypoints to your task skeleton keypoints using a mapping JSON.

### Mapping file format

Mapping files live in [annotation/mapping](annotation/mapping).
Examples:
- [annotation/mapping/spine_pose_mapping.json](annotation/mapping/spine_pose_mapping.json)
- [annotation/mapping/hrnet_mapping.json](annotation/mapping/hrnet_mapping.json)

Structure:

```json
{
  "metadata": {
    "name": "model-function-name-on-cvat"
  },
  "data": {
    "body": {
      "<model_point_id>": "<task_point_id>"
    }
  }
}
```

Notes:
- `metadata.name` becomes the `function` sent to `/api/lambda/requests`.
- `data` can contain groups like `body`, `hands`, `feet`, `face`.
- Relative mapping names are resolved from `annotation/mapping/`.

### Run it

From repo root:

```bash
python annotation/annotation_mapping.py --task-id 123 --mapping-file spine_pose_mapping.json
```

Or with an absolute path:

```bash
python annotation/annotation_mapping.py --task-id 123 --mapping-file /full/path/to/mapping.json
```

Expected result:
- If accepted, CVAT returns success (HTTP 200/201/202) and auto-annotation starts asynchronously.

## Using upload/prep_and_upload_tool.py

Script: [upload/prep_and_upload_tool.py](upload/prep_and_upload_tool.py)

Purpose:
- Interactive desktop workflow for preparing videos and uploading clips to CVAT tasks.

### What it does

For each selected source video, it:
1. Opens an interactive range picker (OpenCV window) to mark keep ranges.
2. Optionally prompts for extraction resolution (for large sources).
3. Optionally prompts for crop ROI.
4. Trims selected ranges into clips with ffmpeg.
5. Extracts frames with ffmpeg/OpenCV fallback.
6. Creates CVAT tasks and uploads frames.
7. Prints task IDs in the final summary.

### Run it

From repo root:

```bash
python upload/prep_and_upload_tool.py
```

The script opens a file picker for one or more videos.

### Interactive controls (range picker)

- `space`: play/pause
- `j` / `l`: jump -/+ 5 seconds
- `,` / `.`: previous/next frame
- `i`: set range start (IN)
- `o`: set range end (OUT) and add range
- `d`: remove last range
- `c`: clear all ranges
- `Enter`: accept ranges
- `q` or `Esc`: skip current video

### Output behavior

- Each trimmed clip becomes a CVAT task under `PROJECT_ID`.
- Upload results are printed as success/failure.
- On success, each clip prints its `task_id`.

## Typical Workflow

1. Fill out `.env`.
2. Run prep/upload:

```bash
python upload/prep_and_upload_tool.py
```

3. Collect `task_id` values from output.
4. Trigger auto-annotation per task:

```bash
python annotation/annotation_mapping.py --task-id <TASK_ID> --mapping-file spine_pose_mapping.json
```

## Security Notes

- `.env` is ignored by git in [.gitignore](.gitignore).
- Keep credentials only in `.env`, never hardcoded in scripts.
