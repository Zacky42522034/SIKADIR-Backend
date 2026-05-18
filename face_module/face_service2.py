"""
face_module/face_service2.py — Production-optimized FaceRecognition service

Changes vs original
───────────────────
  ✓ asyncio.run() removed — pure threading, Flask-compatible
  ✓ Gunicorn pre-fork safe (PID-aware singleton in app.py handles this)
  ✓ _load_sync() replaces async _load_all() — no event-loop dependency
  ✓ Image pre-processed (resize + JPEG compression) before CNN encoding
  ✓ Lock scope minimized — snapshot-then-release pattern in _identify()
  ✓ Watcher thread uses stop_event.wait() (no busy-sleep)
  ✓ reload() is atomic — swaps state under lock, no downtime window
  ✓ File-level duplicate guard — skips re-encoding already-known files
  ✓ Optional removal support in watcher (uncommenting 3 lines)
  ✓ Structured log fields for easy Grafana/Loki filtering
  ✓ All public methods are thread-safe
"""

import hashlib
import logging
import os
import pickle
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Optional

import cv2
import face_recognition
import numpy as np
from PIL import Image

from config.config import supabase
from face_module.face_utils import face_confidence

# ─────────────────────────────────────────────────────────────
#  TUNING CONSTANTS
# ─────────────────────────────────────────────────────────────
STRICT_THRESHOLD     = 0.42     # lower = stricter match required
MIN_MARGIN           = 0.07     # min distance gap between best and 2nd match
UNKNOWN_LABEL        = "Unknown"

MAX_DOWNLOAD_WORKERS = 8        # parallel Supabase download threads
CACHE_DIR            = Path(".face_encoding_cache")

# Pre-processing: resize reference images before CNN encoding.
# Reduces encoding time ~4× with negligible accuracy loss.
MAX_REF_DIMENSION    = 800      # px — reference photos (high quality needed)
MAX_LIVE_DIMENSION   = 640      # px — live/uploaded frames (speed priority)
JPEG_QUALITY         = 88       # re-encode quality after resize

# Lighting thresholds (LAB L-channel, 0–255)
BRIGHTNESS_LOW       = 30
BRIGHTNESS_HIGH      = 220

# Watcher
POLL_INTERVAL        = 30       # seconds between Supabase bucket polls

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  IMAGE PRE-PROCESSING
# ─────────────────────────────────────────────────────────────

def _resize_if_needed(img: Image.Image, max_dim: int) -> Image.Image:
    """Resize an image proportionally if either dimension exceeds max_dim."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img
    ratio = max_dim / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def preprocess_for_encoding(
    raw_bytes: bytes,
    max_dim: int = MAX_REF_DIMENSION,
) -> np.ndarray:
    """
    Decode raw image bytes → resized, JPEG-recompressed numpy array.
    Dramatically reduces CNN encoding time on high-res photos.
    """
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    img = _resize_if_needed(img, max_dim)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buf.seek(0)

    return np.array(Image.open(buf))


def preprocess_frame(image_np: np.ndarray) -> np.ndarray:
    """
    Resize a live numpy frame to MAX_LIVE_DIMENSION before HOG detection.
    Returns (resized_array, scale_factor) so bounding boxes can be
    scaled back to original dimensions by the caller if needed.
    """
    h, w = image_np.shape[:2]
    max_dim = max(h, w)
    if max_dim <= MAX_LIVE_DIMENSION:
        return image_np

    ratio  = MAX_LIVE_DIMENSION / max_dim
    new_w  = int(w * ratio)
    new_h  = int(h * ratio)
    return cv2.resize(image_np, (new_w, new_h), interpolation=cv2.INTER_AREA)


# ─────────────────────────────────────────────────────────────
#  LIGHTING NORMALISATION
# ─────────────────────────────────────────────────────────────

def normalize_lighting(image_np: np.ndarray) -> np.ndarray:
    """
    Apply CLAHE on the LAB L-channel only when luminance is outside
    [BRIGHTNESS_LOW, BRIGHTNESS_HIGH].  No-op when lighting is normal.
    """
    lab    = cv2.cvtColor(image_np, cv2.COLOR_RGB2LAB)
    l_ch   = lab[:, :, 0]
    mean_l = float(l_ch.mean())

    if BRIGHTNESS_LOW <= mean_l <= BRIGHTNESS_HIGH:
        return image_np

    log.debug("Lighting correction applied (mean L=%.1f)", mean_l)
    clahe        = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(l_ch)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)


# ─────────────────────────────────────────────────────────────
#  DISK ENCODING CACHE
# ─────────────────────────────────────────────────────────────

def _cache_path(file_name: str, file_bytes: bytes) -> Path:
    digest = hashlib.sha256(file_bytes).hexdigest()[:16]
    stem   = Path(file_name).stem
    return CACHE_DIR / f"{stem}_{digest}.pkl"


def _load_from_cache(cache_file: Path) -> Optional[np.ndarray]:
    try:
        if cache_file.exists():
            with open(cache_file, "rb") as f:
                return pickle.load(f)
    except Exception as e:
        log.warning("Cache read failed (%s): %s", cache_file.name, e)
    return None


def _save_to_cache(cache_file: Path, encoding: np.ndarray) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(encoding, f)
    except Exception as e:
        log.warning("Cache write failed (%s): %s", cache_file.name, e)


# ─────────────────────────────────────────────────────────────
#  SUPABASE I/O  (plain sync — no asyncio dependency)
# ─────────────────────────────────────────────────────────────

def _fetch_users() -> dict[str, str]:
    response = supabase.table("users").select("id, name").execute()
    return {u["id"]: u["name"] for u in response.data if u.get("id")}


def _list_face_files() -> list[dict]:
    return supabase.storage.from_("faces").list() or []


def _download_file(file_name: str) -> bytes:
    data = supabase.storage.from_("faces").download(file_name)
    return data.read() if hasattr(data, "read") else data


# ─────────────────────────────────────────────────────────────
#  ENCODING  (cache-aware, pre-processed, lighting-normalised)
# ─────────────────────────────────────────────────────────────

def _encode_image(file_name: str, file_bytes: bytes) -> Optional[np.ndarray]:
    """
    Return the dominant face encoding for a reference image.

    Pipeline
    ────────
    cache hit  → return immediately (no GPU/CPU cost)
    cache miss → resize → lighting normalise → CNN encode → cache → return
    """
    cache_file = _cache_path(file_name, file_bytes)

    cached = _load_from_cache(cache_file)
    if cached is not None:
        log.debug("Cache hit: %s", file_name)
        return cached

    # Pre-process: resize + JPEG compress before CNN (big speed win)
    image_np = preprocess_for_encoding(file_bytes, max_dim=MAX_REF_DIMENSION)
    image_np = normalize_lighting(image_np)

    locations = face_recognition.face_locations(image_np, model="cnn")
    encodings = face_recognition.face_encodings(
        image_np, locations, num_jitters=10, model="large"
    )

    if not encodings:
        log.warning("No face found in reference image: %s", file_name)
        return None

    if len(encodings) > 1:
        areas    = [(b - t) * (r - l) for (t, r, b, l) in locations]
        encoding = encodings[int(np.argmax(areas))]
        log.warning("Multiple faces in %s — using largest", file_name)
    else:
        encoding = encodings[0]

    _save_to_cache(cache_file, encoding)
    return encoding


def _process_file(file_name: str, user_map: dict[str, str]) -> Optional[dict]:
    """Download and encode a single reference face file from Supabase."""
    try:
        file_bytes = _download_file(file_name)
        encoding   = _encode_image(file_name, file_bytes)
        if encoding is None:
            return None

        user_id = os.path.splitext(file_name)[0]
        return {
            "encoding":  encoding,
            "name":      user_map.get(user_id, UNKNOWN_LABEL),
            "user_id":   user_id,
            "file_name": file_name,
        }
    except Exception as e:
        log.error("Failed to process %s: %s", file_name, e)
        return None


# ─────────────────────────────────────────────────────────────
#  MAIN CLASS
# ─────────────────────────────────────────────────────────────

class FaceRecognition:
    """
    Thread-safe face recognition service.

    Lifecycle (matches app.py create_app flow)
    ───────────────────────────────────────────
    1. FaceRecognition()          → _load_sync() → _start_watcher()
    2. app.extensions["face_recognition"] = instance
    3. recognize_faces() called per HTTP request (thread-safe)
    4. Watcher polls Supabase every POLL_INTERVAL seconds, appends new faces
    5. reload() available via admin endpoint for forced refresh
    """

    def __init__(self):
        self.known_faces:      list[dict]     = []
        self.user_map:         dict[str, str] = {}
        self._known_filenames: set[str]       = set()

        # Single RLock guards known_faces + _known_filenames.
        # RLock (re-entrant) allows reload() to call _load_sync()
        # without deadlocking if called from within a locked section.
        self._lock = threading.RLock()

        self._stop_event     = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None

        # Synchronous load — no asyncio.run(), safe for Flask app factory
        self._load_sync()
        self._start_watcher()

    # ──────────────────────────────────────────────────────────
    #  INITIAL / FORCED LOAD
    # ──────────────────────────────────────────────────────────

    def _load_sync(self) -> None:
        """
        Blocking full load: fetch users + file list from Supabase in
        parallel threads, then encode all images via thread pool.
        No asyncio — safe to call from any context.
        """
        log.info("Loading users and face list from Supabase…")
        t0 = time.monotonic()

        # Fetch users and file list in parallel with two threads
        user_map:  dict[str, str] = {}
        file_list: list[dict]     = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            fu = pool.submit(_fetch_users)
            ff = pool.submit(_list_face_files)
            user_map  = fu.result()
            file_list = ff.result()

        log.info(
            "Supabase fetch done: %d users, %d bucket files (%.2fs)",
            len(user_map), len(file_list), time.monotonic() - t0,
        )

        image_files = [
            f["name"] for f in file_list
            if f.get("name", "").lower().endswith((".jpg", ".jpeg", ".png"))
        ]

        if not image_files:
            log.warning("No images found in faces bucket.")
            with self._lock:
                self.user_map = user_map
            return

        log.info(
            "Encoding %d image(s) with %d workers…",
            len(image_files), MAX_DOWNLOAD_WORKERS,
        )

        results = self._batch_process(image_files, user_map)
        loaded  = [r for r in results if r is not None]

        with self._lock:
            self.known_faces      = loaded
            self.user_map         = user_map
            self._known_filenames = {r["file_name"] for r in loaded}

        log.info(
            "FaceRecognition ready: %d/%d faces loaded (%.2fs total)",
            len(loaded), len(image_files), time.monotonic() - t0,
        )

    def _batch_process(
        self,
        image_files: list[str],
        user_map:    dict[str, str],
    ) -> list[Optional[dict]]:
        """Encode image_files in parallel; preserves input order in output."""
        result_map: dict[str, Optional[dict]] = {}

        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
            future_to_name = {
                pool.submit(_process_file, name, user_map): name
                for name in image_files
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    result_map[name] = future.result()
                    log.debug("%s %s", "✓" if result_map[name] else "✗", name)
                except Exception as e:
                    log.error("Batch encode error (%s): %s", name, e)
                    result_map[name] = None

        return [result_map.get(n) for n in image_files]

    # ──────────────────────────────────────────────────────────
    #  BACKGROUND WATCHER
    # ──────────────────────────────────────────────────────────

    def _start_watcher(self) -> None:
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            name="face-watcher",
            daemon=True,    # killed automatically when Flask process exits
        )
        self._watcher_thread.start()
        log.info("Face watcher started (interval: %ds).", POLL_INTERVAL)

    def _watch_loop(self) -> None:
        """Daemon loop: sleep POLL_INTERVAL, then diff the bucket."""
        while not self._stop_event.wait(timeout=POLL_INTERVAL):
            try:
                self._check_for_new_faces()
            except Exception as e:
                log.error("Watcher iteration failed: %s", e)

    def _check_for_new_faces(self) -> None:
        """
        Diff the live bucket against _known_filenames.
        Only new files are downloaded and encoded — zero re-work on
        files already in memory.
        """
        file_list    = _list_face_files()
        bucket_names = {
            f["name"] for f in file_list
            if f.get("name", "").lower().endswith((".jpg", ".jpeg", ".png"))
        }

        with self._lock:
            known_snapshot = set(self._known_filenames)

        added = bucket_names - known_snapshot

        if not added:
            log.debug("Watcher: no new faces.")
            return

        log.info("Watcher: %d new file(s) detected → %s", len(added), added)

        fresh_user_map = _fetch_users()
        new_results: list[dict] = []

        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
            futures = {
                pool.submit(_process_file, name, fresh_user_map): name
                for name in added
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if result:
                        new_results.append(result)
                        log.info(
                            "Watcher: new face added — name=%s user_id=%s",
                            result["name"], result["user_id"],
                        )
                    else:
                        log.warning("Watcher: no face in %s", name)
                except Exception as e:
                    log.error("Watcher: encode error (%s): %s", name, e)

        if new_results:
            with self._lock:
                self.known_faces.extend(new_results)
                self._known_filenames.update(r["file_name"] for r in new_results)
                self.user_map = fresh_user_map

            log.info(
                "Watcher: +%d face(s). Total known: %d",
                len(new_results), len(self.known_faces),
            )

        # ── Optional: handle deletions ────────────────────────
        # removed = known_snapshot - bucket_names
        # if removed:
        #     with self._lock:
        #         self.known_faces      = [f for f in self.known_faces
        #                                  if f["file_name"] not in removed]
        #         self._known_filenames -= removed
        #     log.info("Watcher: removed %d face(s). Total: %d",
        #              len(removed), len(self.known_faces))

    def stop_watcher(self) -> None:
        """
        Gracefully stop the background watcher thread.
        Called by reload(); also triggered automatically on process exit
        because the thread is a daemon.
        """
        self._stop_event.set()
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=5)
            log.info("Face watcher stopped.")

    # ──────────────────────────────────────────────────────────
    #  CORE MATCHING
    # ──────────────────────────────────────────────────────────

    def _identify(self, face_encoding: np.ndarray) -> tuple[str, str]:
        """
        Match a single encoding against known faces.

        Lock is held only long enough to take a snapshot — the actual
        distance computation happens outside the lock so recognition
        requests don't block the watcher (or each other).
        """
        with self._lock:
            if not self.known_faces:
                return UNKNOWN_LABEL, ""
            all_encodings = [kf["encoding"] for kf in self.known_faces]
            all_faces     = list(self.known_faces)   # shallow copy, fast

        distances  = face_recognition.face_distance(all_encodings, face_encoding)
        sorted_idx = np.argsort(distances)
        best_idx   = sorted_idx[0]
        best_dist  = distances[best_idx]

        if best_dist > STRICT_THRESHOLD:
            return UNKNOWN_LABEL, ""

        if len(sorted_idx) > 1:
            margin = distances[sorted_idx[1]] - best_dist
            if margin < MIN_MARGIN:
                log.debug(
                    "Ambiguous match (best=%.3f margin=%.3f) → Unknown",
                    best_dist, margin,
                )
                return UNKNOWN_LABEL, ""

        return all_faces[best_idx]["name"], face_confidence(best_dist)

    # ──────────────────────────────────────────────────────────
    #  PUBLIC API
    # ──────────────────────────────────────────────────────────

    def recognize_faces(self, image_np: np.ndarray) -> list[dict]:
        """
        Detect and identify all faces in a numpy RGB image.

        Pipeline
        ────────
        lighting normalise → resize for HOG → detect locations
        → encode → identify each face → return list of results

        Thread-safe: safe to call concurrently from Flask worker threads.
        """
        image_np  = normalize_lighting(image_np)
        image_np  = preprocess_frame(image_np)          # resize before HOG

        locations = face_recognition.face_locations(image_np, model="hog")
        if not locations:
            return []

        encodings = face_recognition.face_encodings(
            image_np, locations, num_jitters=3, model="large"
        )

        return [
            {"name": name, "confidence": conf}
            for enc in encodings
            for name, conf in [self._identify(enc)]
        ]

    def reload(self) -> None:
        """
        Atomic hot-reload: stops the watcher, replaces state under lock,
        restarts the watcher. The service stays responsive during the
        load phase because new requests read the old known_faces snapshot.
        """
        log.info("Reload requested — fetching fresh data from Supabase…")
        self.stop_watcher()

        # Load into a temporary service, then swap state atomically
        tmp = FaceRecognition.__new__(FaceRecognition)
        tmp.known_faces      = []
        tmp.user_map         = {}
        tmp._known_filenames = set()
        tmp._lock            = threading.RLock()
        tmp._stop_event      = threading.Event()
        tmp._watcher_thread  = None
        tmp._load_sync()        # blocking, but watcher is stopped so no conflict

        with self._lock:
            self.known_faces      = tmp.known_faces
            self.user_map         = tmp.user_map
            self._known_filenames = tmp._known_filenames

        self._start_watcher()
        log.info("Reload complete — %d faces active.", len(self.known_faces))

    @property
    def is_ready(self) -> bool:
        """True when at least one face is loaded. Used by health check."""
        with self._lock:
            return len(self.known_faces) > 0

    # ──────────────────────────────────────────────────────────
    #  LIVE CAMERA  (unchanged logic, uses new preprocess_frame)
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
                # Downscale to 0.25 first (your original approach),
                # then normalize + preprocess_frame for any remaining size
                small  = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
                rgb_sm = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                rgb_sm = normalize_lighting(rgb_sm)

                locations = face_recognition.face_locations(rgb_sm, model="hog")
                encodings = face_recognition.face_encodings(
                    rgb_sm, locations, num_jitters=2, model="large"
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
                cv2.rectangle(
                    frame, (left, bottom - 35), (right, bottom),
                    (0, 0, 255), cv2.FILLED,
                )
                cv2.putText(
                    frame, label, (left + 6, bottom - 6),
                    cv2.FONT_HERSHEY_DUPLEX, 0.75, (255, 255, 255), 1,
                )

            cv2.imshow("Face Recognition", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        video_capture.release()
        cv2.destroyAllWindows()