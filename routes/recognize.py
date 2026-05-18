from flask import Blueprint, request, jsonify
import base64
import numpy as np
import cv2

from io import BytesIO
from PIL import Image, ImageEnhance, ImageStat

recognize_bp = Blueprint("recognize", __name__)


# ==========================================
# AUTO BRIGHT FUNCTION
# ==========================================
def auto_brightness(image_pil):
    TARGET_BRIGHTNESS = 180
    MIN_FACTOR = 0.7
    MAX_FACTOR = 1.8

    grayscale = image_pil.convert("L")
    stat = ImageStat.Stat(grayscale)

    current_brightness = stat.mean[0]

    brightness_factor = TARGET_BRIGHTNESS / max(current_brightness, 1)

    brightness_factor = max(
        MIN_FACTOR,
        min(brightness_factor, MAX_FACTOR)
    )

    # Brightness
    enhancer = ImageEnhance.Brightness(image_pil)
    image_pil = enhancer.enhance(brightness_factor)

    # Contrast
    contrast = ImageEnhance.Contrast(image_pil)
    image_pil = contrast.enhance(1.1)

    return image_pil


def init_routes(fr):
    @recognize_bp.route("/recognize", methods=["POST"])
    def recognize():
        try:
            try:
                body = request.get_json(force=True, silent=True)
            except Exception:
                body = None

            if not body:
                return jsonify({
                    "success": False,
                    "error": "Invalid or missing JSON body"
                }), 400

            data = body.get("image")
            if not data:
                return jsonify({"success": False, "error": "No image"}), 400

            if "," not in data:
                return jsonify({"success": False, "error": "Invalid base64 format"}), 400

            header, encoded = data.split(",", 1)
            image_bytes = base64.b64decode(encoded)

            if len(image_bytes) > 2 * 1024 * 1024:
                return jsonify({"success": False, "error": "Image too large (max 2MB)"}), 413

            image = Image.open(BytesIO(image_bytes)).convert("RGB")
            image = auto_brightness(image)
            image_np = np.array(image)

            if image_np.shape[1] > 640:
                scale = 640 / image_np.shape[1]
                image_np = cv2.resize(image_np, (0, 0), fx=scale, fy=scale)

            results = fr.recognize_faces(image_np)
            return jsonify({"success": True, "faces": results})

        except Exception as e:
            print("❌ ERROR:", e)
            return jsonify({"success": False, "error": str(e)}), 500

    return recognize_bp