# Virtualenv setup and usage

This project uses a Python virtual environment. The steps below assume a Debian/Ubuntu-like system; adapt package manager commands for other OSes.

## System prerequisites
- Install Python 3.9+ and `venv` support.
- Install `ffmpeg` (used for fast frame extraction).
- Install system Tk support to use file chooser UI (`tk` / `python3-tk`).

Example (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg python3-tk
```

Example (Fedora):

```bash
# Install Python + venv + pip + Tk
sudo dnf install -y python3 python3-venv python3-pip python3-tkinter

# Enable RPM Fusion repositories (required to install ffmpeg)
sudo dnf install -y \
	https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
	https://download1.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

# Install ffmpeg and common GL libraries needed by OpenCV GUI
sudo dnf install -y ffmpeg mesa-libGL
```

Note: OpenCV GUI windows may require additional system libraries (mesa, libgl). If you encounter errors opening windows, install your platform's GL/X11 packages.

## Create and activate a virtual environment

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

## Install Python dependencies

```bash
pip install -r requirements.txt
```

If you prefer a headless environment (no GUI windows), replace `opencv-python` with `opencv-python-headless` in the venv before installing:

```bash
pip uninstall -y opencv-python
pip install opencv-python-headless
```

## Running the upload tool (example)

Activate the venv then run:

```bash
source .venv/bin/activate
python ./upload/prep_and_upload_tool.py
```

If you see `ModuleNotFoundError: No module named 'cv2'`:
- Ensure the venv is activated.
- Run `pip install opencv-python` (or `opencv-python-headless` if appropriate).
- Confirm `python -c "import cv2; print(cv2.__version__)"` works.

## Optional: Pin exact versions
If you need reproducible installs, run `pip freeze > requirements-pinned.txt` after installing and commit that file instead of `requirements.txt`.

## Troubleshooting
- If `ffmpeg` is missing, frame extraction will fail; install system `ffmpeg`.
- If Tkinter dialogs fail to start, install `python3-tk` at the system level.
- For OpenCV GUI failures on Linux, try installing `libgl1-mesa-glx` or equivalent.
