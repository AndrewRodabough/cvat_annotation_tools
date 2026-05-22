import base64
import json
import io
import sys
import numpy as np
from PIL import Image
import torch

sys.path.append('/opt/nuclio/ViTPose')
from mmpose.apis import inference_top_down_pose_model, init_pose_model

def init_context(context):
    context.logger.info("Initializing ViTPose++ WholeBody...")
    config_file = '/opt/nuclio/ViTPose/configs/wholebody/2d_kpt_sview_rgb_img/topdown_heatmap/coco-wholebody/ViTPose_large_wholebody_256x192.py'
    checkpoint_file = '/opt/nuclio/weights/vitpose_large.pth'
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    context.logger.info(f"Using device: {device}")
    model = init_pose_model(config_file, checkpoint_file, device=device)
    context.user_data.model = model
    context.logger.info("Model loaded successfully")

def handler(context, event):
    try:
        data = event.body
        if isinstance(data, (bytes, bytearray)):
            data = json.loads(data.decode("utf-8"))
        elif isinstance(data, str):
            data = json.loads(data)

        buf = io.BytesIO(base64.b64decode(data["image"]))
        image = Image.open(buf).convert("RGB")
        image_np = np.array(image)
        h, w = image_np.shape[:2]

        # Use bounding boxes from previous detection step if available
        regions = data.get("regions", [])
        if regions:
            person_results = []
            for r in regions:
                pts = r["points"]
                x1, y1, x2, y2 = pts[0], pts[1], pts[2], pts[3]
                person_results.append({'bbox': np.array([x1, y1, x2, y2, 1.0])})
            context.logger.info(f"Using {len(person_results)} bounding boxes from regions")
        else:
            # Fallback to full image if no boxes provided
            context.logger.info("No regions provided, using full image")
            person_results = [{'bbox': np.array([0, 0, w, h, 1.0])}]

        responses, _ = inference_top_down_pose_model(
            context.user_data.model,
            image_np,
            person_results,
            bbox_thr=None,
            format='xyxy'
        )

        skeletons = []
        for res in responses:
            kpts = res['keypoints']  # [133, 3]
            elements = []
            for i, kp in enumerate(kpts):
                elements.append({
                    "label": str(i),
                    "type": "points",
                    "points": [float(kp[0]), float(kp[1])]
                })
            skeletons.append({
                "confidence": float(np.mean(kpts[:, 2])),
                "label": "body",
                "type": "skeleton",
                "elements": elements
            })

        return context.Response(
            body=json.dumps(skeletons),
            content_type="application/json",
            status_code=200,
        )

    except Exception as e:
        context.logger.error(f"Inference error: {str(e)}")
        import traceback
        context.logger.error(traceback.format_exc())
        return context.Response(body=json.dumps([]), status_code=200)
