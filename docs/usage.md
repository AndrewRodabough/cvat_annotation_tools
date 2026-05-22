# Usage Guide

This document expands the quick examples in the repository `README.md` with runnable commands and flags.

## Video Upload

### Complete Prep and Upload Tool
tool for preparing a video (segmentation, crops, down sampling etc) and upload to cvat

```bash
python3 ./run/prep_and_upload.py

# Optional Arguments
--project-id <int> # override default project id from .env
```

#### Configuration
upload configuration can be  modified in 
- /upload/prep_and_upload/gui/config.yaml (for gui changes)
- /upload/prep_and_upload/config.yaml (workflow preferences)


## Auto Annotation
Tools for automatically annotating images using nuclio functions<br>
See [Nuclio Setup](/docs/nuclio_setup.md) for more info about setting up models

### Trigger Nuclio Auto-Annotation
run an auto-annotation for a task through cvat
```bash
python3 ./run/auto_annotate.py

# Required Arguments
--task-id <int>         # id of task to annotate
--mapping-file <path>   # file that defines mapping between model and cvat

# Optional Arguments
--project-id <int>      # override default project id from .env
--replace-existing      # replaces all existing annotation
```

### Local Annotation and Upload
for annotations beyond cvat's capabilities
(ie. running pose estimation on annotated bbox rather than per frame)

```bash
python3 ./run/manual_annotation_by_bbox.py 

# Required Arguments
--task-id <int>         # id of task to annotate
--mapping-file <path>   # file that defines mapping between model and cvat
--function_url <url>    # url where nuclio function is hosted

# Optional Arguments
--project-id <int>      # override default project id from .env
--dry-run               # returns results rather than trying to upload them
--replace-existing      # replaces all existing annotation
```

## Clean Up

### Delete All
Deletes all annotations for a task

```bash
python3 ./run/delete_all.py

# Required Arguments
--task-id <int>         # id of task to annotate

# Optional Arguments
--project-id <int>      # override default project id from .env
```

### Delete Object
Deletes all annotations of a specific object for a task
```bash
python3 ./run/delete_object.py

# Required Arguments
--task-id <int>         # id of task to annotate
--name                  # name of object

# Optional Arguments
--project-id <int>      # override default project id from .env
--dry-run               # returns results rather than trying to upload them
```

### Deleted Object Keep Tracks
Deletes all annotations of a specific object but keep tracks of the object
```bash
python3 ./run/delete_object_keep_tracks.py

# Required Arguments
--task-id <int>         # id of task to annotate
--name # name of object

# Optional Arguments
--project-id <int>      # override default project id from .env
--dry-run               # returns results rather than trying to upload them
```