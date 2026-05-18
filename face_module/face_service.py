import asyncio
import hashlib
import logging
import os
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import cv2
import face_recognition
import numpy as np
from PIL import Image

from config.config import supabase
from face_module.face_utils import face_confidence

# ─────────────────────────────────────────────────────────────
#  TUNING CONSTANTS
# ─────────────────────────────────────────────────────────────
STRICT_THRESHOLD   = 0.42
MIN_MARGIN         = 0.07
UNKNOWN_LABEL      = "Unknown"

MAX_DOWNLOAD_WORKERS = 8
CACHE_DIR = Path(".face_encoding_cache")

# Brightness thresholds (0–255 scale on L-channel mean)
BRIGHTNESS_LOW  = 30   # Below this → too dark
BRIGHTNESS_HIGH = 220  # Above this → too bright

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  LIGHTING NORMALISATION
# ─────────────────────────────────────────────────────────────

def normalize_lighting(image_np: np.ndarray) -> np.ndarray:
    """
    Detect and correct unstable lighting in an RGB numpy image.

    Strategy
    --------
    1. Convert to LAB colour space and measure mean L (luminance).
    2. If luminance is within normal range [BRIGHTNESS_LOW, BRIGHTNESS_HIGH],
       return the image unchanged — no unnecessary processing.
    3. Otherwise apply CLAHE on the L-channel only, preserving hue/saturation,
       then convert back to RGB.

    Parameters
    ----------
    image_np : np.ndarray
        RGB image as a uint8 numpy array (H × W × 3).

    Returns
    -------
    np.ndarray
        RGB image with corrected luminance (same shape/dtype as input).
    """
    lab = cv2.cvtColor(image_np, cv2.COLOR_RGB2LAB)
    l_channel = lab[:, :, 0]
    mean_l = float(l_channel.mean())

    if BRIGHTNESS_LOW <= mean_l <= BRIGHTNESS_HIGH:
        return image_np  # lighting is stable — skip normalisation

    if mean_l < BRIGHTNESS_LOW:
        log.debug("Image too dark (mean L=%.1f) — applying CLAHE", mean_l)
    else:
        log.debug("Image too bright (mean L=%.1f) — applying CLAHE", mean_l)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(l_channel)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


# ─────────────────────────────────────────────────────────────
#  ENCODING CACHE
# ─────────────────────────────────────────────────────────────

def _cache_path(file_name: str, file_bytes: bytes) -> Path:
    digest = hashlib.sha256(file_bytes).hexdigest()[:16]
    stem   = Path(file_name).stem
    return CACHE_DIR / f"{stem}_{digest}.pkl"


def _load_from_cache(cache_file: Path) -> np.ndarray | None:
    try:
        if cache_file.exists():
            with open(cache_file, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        log.warning("Cache read failed for %s: %s", cache_file, e)
    return None


def _save_to_cache(cache_file: Path, encoding: np.ndarray) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(encoding, f)
    except Exception as e:
        log.warning("Cache write failed for %s: %s", cache_file, e)


# ─────────────────────────────────────────────────────────────
#  SUPABASE I/O
# ─────────────────────────────────────────────────────────────

def _fetch_users() -> dict[str, str]:
    response = supabase.table("users").select("id, name").execute()
    return {
        u["id"]: u["name"]
        for u in response.data
        if u.get("id")
    }


def _list_face_files() -> list[dict]:
    return supabase.storage.from_("faces").list() or []


def _download_file(file_name: str) -> bytes:
    data = supabase.storage.from_("faces").download(file_name)
    return data.read() if hasattr(data, "read") else data


# ─────────────────────────────────────────────────────────────
#  ENCODING
# ─────────────────────────────────────────────────────────────

def _encode_image(file_name: str, file_bytes: bytes) -> np.ndarray | None:
    """
    Extract the dominant face encoding from raw image bytes.
    Lighting is normalised before encoding to improve accuracy on
    dark or overexposed reference photos.
    """
    cache_file = _cache_path(file_name, file_bytes)

    cached = _load_from_cache(cache_file)
    if cached is not None:
        log.debug("Cache hit: %s", file_name)
        return cached

    image_np  = np.array(Image.open(BytesIO(file_bytes)).convert("RGB"))

    # ── Normalise lighting before CNN encoding ────────────────
    image_np  = normalize_lighting(image_np)

    locations = face_recognition.face_locations(image_np, model="cnn")
    encodings = face_recognition.face_encodings(
        image_np, locations, num_jitters=10, model="large"
    )

    if not encodings:
        log.warning("No face found in %s", file_name)
        return None

    if len(encodings) > 1:
        areas     = [(b - t) * (r - l) for (t, r, b, l) in locations]
        encoding  = encodings[int(np.argmax(areas))]
        log.warning("Multiple faces in %s — using largest", file_name)
    else:
        encoding = encodings[0]

    _save_to_cache(cache_file, encoding)
    return encoding


def _process_file(
    file_name: str,
    user_map:  dict[str, str],
) -> dict | None:
    try:
        file_bytes = _download_file(file_name)
        encoding   = _encode_image(file_name, file_bytes)
        if encoding is None:
            return None

        user_id = os.path.splitext(file_name)[0]
        return {
            "encoding": encoding,
            "name":     user_map.get(user_id, UNKNOWN_LABEL),
            "user_id":  user_id,
        }
    except Exception as e:
        log.error("Failed to process %s: %s", file_name, e)
        return None


# ─────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────

class FaceRecognition:
    def __init__(self):
        self.known_faces: list[dict] = []
        self.user_map:    dict[str, str] = {}
        asyncio.run(self._load_all())

    async def _load_all(self) -> None:
        log.info("Loading users and face list in parallel…")
        loop = asyncio.get_running_loop()

        user_map_fut  = loop.run_in_executor(None, _fetch_users)
        file_list_fut = loop.run_in_executor(None, _list_face_files)

        self.user_map, file_list = await asyncio.gather(
            user_map_fut, file_list_fut
        )
        log.info("Users loaded: %d | Files in bucket: %d",
                 len(self.user_map), len(file_list))

        image_files = [
            f["name"] for f in file_list
            if f.get("name", "").lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if not image_files:
            log.warning("No images found in faces bucket.")
            return

        log.info("Processing %d face images with %d workers…",
                 len(image_files), MAX_DOWNLOAD_WORKERS)

        results = await loop.run_in_executor(
            None,
            lambda: self._batch_process(image_files),
        )

        self.known_faces = [r for r in results if r is not None]
        log.info("Ready — %d faces loaded.", len(self.known_faces))

    def _batch_process(self, image_files: list[str]) -> list[dict | None]:
        result_map: dict[str, dict | None] = {}

        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
            future_to_name = {
                pool.submit(_process_file, name, self.user_map): name
                for name in image_files
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result_map[name] = future.result()
                    status = "✓" if result_map[name] else "✗"
                    log.debug("%s %s", status, name)
                except Exception as e:
                    log.error("Unexpected error for %s: %s", name, e)
                    result_map[name] = None

        return [result_map.get(n) for n in image_files]

    # ──────────────────────────────────────────────────────────
    #  CORE MATCHING
    # ──────────────────────────────────────────────────────────

    def _identify(self, face_encoding: np.ndarray) -> tuple[str, str]:
        if not self.known_faces:
            return UNKNOWN_LABEL, ""

        all_encodings = [kf["encoding"] for kf in self.known_faces]
        distances     = face_recognition.face_distance(all_encodings, face_encoding)

        sorted_idx = np.argsort(distances)
        best_idx   = sorted_idx[0]
        best_dist  = distances[best_idx]

        if best_dist > STRICT_THRESHOLD:
            return UNKNOWN_LABEL, ""

        if len(sorted_idx) > 1:
            second_dist = distances[sorted_idx[1]]
            margin      = second_dist - best_dist
            if margin < MIN_MARGIN:
                log.debug(
                    "Similar faces detected (best=%.3f, 2nd=%.3f, margin=%.3f < %.2f) → Unknown",
                    best_dist, second_dist, margin, MIN_MARGIN,
                )
                return UNKNOWN_LABEL, ""

        return self.known_faces[best_idx]["name"], face_confidence(best_dist)

    # ──────────────────────────────────────────────────────────
    #  PUBLIC API
    # ──────────────────────────────────────────────────────────

    def recognize_faces(self, image_np: np.ndarray) -> list[dict]:
        """
        Detect and identify all faces in a numpy RGB image.
        Lighting is normalised before detection.
        """
        # ── Normalise lighting before HOG detection ───────────
        image_np  = normalize_lighting(image_np)

        # Image.fromarray(image_np).save("brightened.jpg")

        locations = face_recognition.face_locations(image_np, model="hog")
        encodings = face_recognition.face_encodings(
            image_np, locations, num_jitters=5, model="large"
        )

        return [
            {"name": name, "confidence": conf}
            for enc in encodings
            for name, conf in [self._identify(enc)]
        ]

    def reload(self) -> None:
        self.known_faces = []
        self.user_map    = {}
        asyncio.run(self._load_all())

    # ──────────────────────────────────────────────────────────
    #  LIVE CAMERA
    # ──────────────────────────────────────────────────────────

    def run_camera(self):
        video_capture = cv2.VideoCapture(0)
        if not video_capture.isOpened():
            log.error("Camera not found.")
            return

        PROCESS_EVERY_N = 2
        frame_count     = 0
        cached_results  = []

        while True:
            ret, frame = video_capture.read()
            if not ret:
                break

            frame_count += 1
            if frame_count % PROCESS_EVERY_N == 0:
                small  = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
                rgb_sm = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

                # ── Normalise lighting on the downscaled frame ─
                rgb_sm = normalize_lighting(rgb_sm)

                locations = face_recognition.face_locations(rgb_sm, model="hog")
                encodings = face_recognition.face_encodings(
                    rgb_sm, locations, num_jitters=3, model="large"
                )

                cached_results = []
                for (top, right, bottom, left), enc in zip(locations, encodings):
                    name, conf = self._identify(enc)
                    label = f"{name}  {conf}" if conf else name
                    cached_results.append(
                        (top * 4, right * 4, bottom * 4, left * 4, label)
                    )

            for (top, right, bottom, left, label) in cached_results:
                cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
                cv2.rectangle(frame, (left, bottom - 35), (right, bottom),
                              (0, 0, 255), cv2.FILLED)
                cv2.putText(frame, label, (left + 6, bottom - 6),
                            cv2.FONT_HERSHEY_DUPLEX, 0.75, (255, 255, 255), 1)

            cv2.imshow("Face Recognition", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        video_capture.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    face_recog = FaceRecognition()
    face_recog.run_camera()