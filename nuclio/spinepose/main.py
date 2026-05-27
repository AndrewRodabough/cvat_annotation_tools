import json
import base64
from io import BytesIO
from PIL import Image
import numpy as np
from spinepose import SpinePoseEstimator

def init_context(context):
    context.logger.info("Init context... Loading SpinePose model")
    # Initialize the model once and keep it in cache
    model = SpinePoseEstimator(device='cpu')
    context.user_data.model = model

def handler(context, event):
    context.logger.info("Run SpinePose model")
    data = event.body
    buf = BytesIO(base64.b64decode(data['image']))
    image = Image.open(buf).convert('RGB')
    image_np = np.array(image)

    # 1. Inference (runs full body model)
    results = context.user_data.model(image_np)

    try:
        # Pull the data array out of potential wrapper objects or tuples
        if isinstance(results, tuple):
            raw_data = results[0]
        elif hasattr(results, 'keypoints'):
            raw_data = results.keypoints
        else:
            raw_data = results

        # Squeeze down to the raw keypoint matrix
        kpts = np.squeeze(np.asarray(raw_data, dtype=object))

        # If nobody detected, return empty payload
        if kpts.size == 0 or len(kpts) < 13:
            return context.Response(body=json.dumps([]), status_code=200)

        # Helper to convert dynamic numpy element values into pure floats
        def to_coord(val):
            flat = np.array(val).flatten()
            return float(flat[0]) if flat.size > 0 else 0.0

        # Extract underlying COCO indices:
        # 5: Left Shoulder, 6: Right Shoulder, 11: Left Hip, 12: Right Hip
        ls = np.array([to_coord(kpts[5][0]),  to_coord(kpts[5][1])])
        rs = np.array([to_coord(kpts[6][0]),  to_coord(kpts[6][1])])
        lh = np.array([to_coord(kpts[11][0]), to_coord(kpts[11][1])])
        rh = np.array([to_coord(kpts[12][0]), to_coord(kpts[12][1])])

        # Calculate Spine Vertebrae coordinates via midpoint interpolation
        c7 = (ls + rs) / 2.0   # Neck base
        l5 = (lh + rh) / 2.0   # Pelvic base / lower lumbar
        t10 = (c7 + l5 * 2) / 3.0 # Lower mid-back
        t6 = (c7 * 2 + l5) / 3.0  # Upper mid-back

        # Format points as pure list arrays for JSON serialization
        def fmt(p): 
            return [float(p[0]), float(p[1])]

        def fmt_from_idx(idx):
            if idx >= len(kpts):
                return [0.0, 0.0]
            return [to_coord(kpts[idx][0]), to_coord(kpts[idx][1])]

        keypoint_names = [
            "nose",
            "left_eye",
            "right_eye",
            "left_ear",
            "right_ear",
            "left_shoulder",
            "right_shoulder",
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hip",
            "right_hip",
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
            "head",
            "neck",
            "hip",
            "left_big_toe",
            "right_big_toe",
            "left_small_toe",
            "right_small_toe",
            "left_heel",
            "right_heel",
            "spine_01",
            "spine_02",
            "spine_03",
            "spine_04",
            "spine_05",
            "left_latissimus",
            "right_latissimus",
            "left_clavicle",
            "right_clavicle",
            "neck_02",
            "neck_03",
        ]

        elements = [
            {"label": "C7",  "type": "points", "points": fmt(c7)},
            {"label": "T6",  "type": "points", "points": fmt(t6)},
            {"label": "T10", "type": "points", "points": fmt(t10)},
            {"label": "L5",  "type": "points", "points": fmt(l5)},
        ]

        for idx, name in enumerate(keypoint_names):
            elements.append({"label": name, "type": "points", "points": fmt_from_idx(idx)})

        skeleton_data = {
            "confidence": 1.0,
            "label": "body",
            "type": "skeleton",
            "elements": elements
        }

        context.logger.info("Successfully extracted and scaled spine sequence.")
        return context.Response(body=json.dumps([skeleton_data]),
                                content_type='application/json',
                                status_code=200)

    except Exception as e:
        context.logger.error(f"Mapping error: {str(e)}")
        return context.Response(body=json.dumps([]), status_code=200)