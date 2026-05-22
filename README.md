# CVAT Upload and Auto-Annotation Tools

This repo contains scripts to:
- Prepare and upload videos to CVAT (trim, segment, crop, frame)
- Trigger server-side auto-annotation of tasks
- Run client-side auto-annotation for unsupported annotation tasks
- Utilities for automating repetitive annotation tasks

## Requirements

- Python 3.10+
- ffmpeg on `PATH` (required for trimming/frame extraction)
- CVAT server running and reachable (project has been tested on v2.65.0 only)
- A Python virtual environment (recommended)
- Python packages (see `requirements.txt`):
  - python-dotenv
  - PyYAML
  - requests
  - opencv-python

## Installation and setup

### System packages

#### Fedora
```bash
sudo dnf install -y ffmpeg python3 python3-virtualenv
```

#### Ubuntu / Debian
```bash
sudo apt update
sudo apt install -y ffmpeg python3 python3-venv
```

### Clone repository
```bash
git clone https://github.com/AndrewRodabough/cvat_annotation_tools.git
cd cvat_annotation_tools
```

### Setup Python environment (recommended)
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Environment (.env)

Create a file named `.env` in the repository root.

Required keys:

```env
SERVER=http://localhost:8080
EMAIL=your-cvat-email@example.com
PASSWORD=your-cvat-password
```

Optional keys:

```env
PROJECT_ID=1               # default cvat project id
CVAT_FFMPEG_HWACCEL=auto   # auto, none, or specific hwaccel (cuda, qsv, vaapi, ...)
```

## Usage

Quick examples — see the full guides in `docs/` for details.

- Prepare, trim and upload clips (interactive):

```bash
python3 run/prep_and_upload.py
```

- Trigger a CVAT lambda auto-annotation using a mapping file:

```bash
python3 annotation/annotation_mapping.py --task-id 123 --mapping-file spine_pose_mapping.json
```

- Annotate existing bbox tracks with a remote ViTPose function:

```bash
python3 annotation/annotate_bbox_tracks_with_vitpose.py \
  --task-id 123 \
  --mapping-file vitpose_plus_plus_wholebody_numeric_mapping.json \
  --function-url http://<nuclio-host>/api/pth-vitpose-plus-plus-wholebody
```

See the detailed usage guide and configuration reference:

- [Usage Guide](docs/usage.md)