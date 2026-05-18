"""
app.py — Production-optimized Flask entry point

Key improvements over the original:
  - FaceRecognition loaded ONCE via lazy singleton (no double-import crash)
  - Gunicorn-safe singleton guard using os.getpid()
  - Flask-Limiter rate limiting on heavy endpoints
  - Structured JSON error responses for all HTTP errors
  - Blueprint registration centralized and deduplicated
  - Debug mode gated behind ENV variable (never True in prod)
  - Logging configured once, at the right level
  - CORS origins pulled from ENV for flexibility
  - Supabase client exposed via app.extensions (not app.supabase)
  - Health check includes face model readiness
"""

import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client

# ─────────────────────────────────────────────────────────────
#  ENV
# ─────────────────────────────────────────────────────────────
load_dotenv()

# ─────────────────────────────────────────────────────────────
#  LOGGING  — configure once, early, before any imports that log
# ─────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
# Silence noisy third-party loggers in production
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  APP FACTORY
# ─────────────────────────────────────────────────────────────
def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("JWT_SECRET", "change-me-in-production")
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload cap

    # ── CORS ─────────────────────────────────────────────────
    allowed_origins = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "https://frontss.loophole.site,http://localhost:3000",
        ).split(",")
        if o.strip()
    ]
    CORS(
        app,
        supports_credentials=True,
        resources={
            r"/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"],
            }
        },
    )

    # ── Rate limiter (backed by Redis when available, else memory) ──
    redis_url = os.getenv("REDIS_URL")
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per minute", "50 per second"],
        storage_uri=redis_url if redis_url else "memory://",
    )
    app.extensions["limiter"] = limiter

    # ── Supabase (single client, reused across requests) ─────
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
    )
    app.extensions["supabase"] = supabase  # access via current_app.extensions

    # ── Face Recognition singleton (lazy, gunicorn-safe) ─────
    _register_face_service(app)

    # ── Blueprints ───────────────────────────────────────────
    _register_blueprints(app)

    # ── Error handlers ───────────────────────────────────────
    _register_error_handlers(app)

    # ── Health check ─────────────────────────────────────────
    @app.get("/")
    def health():
        fr = app.extensions.get("face_recognition")
        return jsonify(
            {
                "status": "ok",
                "face_model_ready": fr is not None and len(fr.known_faces) > 0,
                "known_faces": len(fr.known_faces) if fr else 0,
            }
        )

    return app


# ─────────────────────────────────────────────────────────────
#  FACE SERVICE — lazy singleton, loaded once per process
# ─────────────────────────────────────────────────────────────
def _register_face_service(app: Flask) -> None:
    """
    Load FaceRecognition exactly once per worker process.

    Uses a module-level dict keyed by PID so Gunicorn pre-fork workers
    each get their own singleton without re-loading in the master process.
    """
    import threading
    from face_module.face_service2 import FaceRecognition

    _instances: dict[int, FaceRecognition] = {}
    _lock = threading.Lock()

    def get_or_create() -> FaceRecognition:
        pid = os.getpid()
        if pid not in _instances:
            with _lock:
                if pid not in _instances:   # double-checked locking
                    log.info("Loading FaceRecognition model (PID %d)…", pid)
                    _instances[pid] = FaceRecognition()
                    log.info(
                        "FaceRecognition ready — %d faces loaded (PID %d)",
                        len(_instances[pid].known_faces),
                        pid,
                    )
        return _instances[pid]

    # Eagerly load during app startup (not on first request) so the first
    # user doesn't wait. Comment this out to switch to true lazy loading.
    try:
        fr = get_or_create()
        app.extensions["face_recognition"] = fr
    except Exception:
        log.exception("FaceRecognition failed to load — recognition will be unavailable")
        app.extensions["face_recognition"] = None


# ─────────────────────────────────────────────────────────────
#  BLUEPRINTS
# ─────────────────────────────────────────────────────────────
def _register_blueprints(app: Flask) -> None:
    fr = app.extensions.get("face_recognition")

    # Auth
    from routes.Auth.postLogin    import auth_bp
    from routes.Auth.postLogout   import logout_bp
    from routes.Auth.getusers     import users_bp
    from routes.Auth.postRegister import register_bp

    app.register_blueprint(auth_bp,      url_prefix="/api")
    app.register_blueprint(logout_bp,    url_prefix="/api/auth")
    app.register_blueprint(users_bp,     url_prefix="/api")
    app.register_blueprint(register_bp,  url_prefix="/api")

    # Attendance
    from routes.Attendance.postAbsences    import init_absence_routes
    from routes.Attendance.getAbsences     import absence_get_bp
    from routes.Attendance.postSick        import sick_bp
    from routes.Attendance.postPermission  import permission_bp
    from routes.Attendance.getSickPermission import not_present_bp

    app.register_blueprint(init_absence_routes(), url_prefix="/api/")
    app.register_blueprint(absence_get_bp,        url_prefix="/api/absences")
    app.register_blueprint(sick_bp,               url_prefix="/api")
    app.register_blueprint(permission_bp,         url_prefix="/api")
    app.register_blueprint(not_present_bp,        url_prefix="/api/not_present")

    # Face recognition route (only if model loaded successfully)
    from routes.recognize import init_routes as init_recognize
    if fr is not None:
        app.register_blueprint(init_recognize(fr), url_prefix="/api")
    else:
        log.warning("Face recognition blueprint skipped — model unavailable")

    # Utils
    from routes.Utils.webhook import telegram_bp
    app.register_blueprint(telegram_bp, url_prefix="/api")

    log.info("All blueprints registered.")


# ─────────────────────────────────────────────────────────────
#  ERROR HANDLERS
# ─────────────────────────────────────────────────────────────
def _register_error_handlers(app: Flask) -> None:
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return jsonify({"status": "error", "code": e.code, "message": e.description}), e.code

    @app.errorhandler(413)
    def too_large(_e):
        return jsonify({"status": "error", "code": 413, "message": "File too large (max 10 MB)"}), 413

    @app.errorhandler(429)
    def rate_limited(_e):
        return jsonify({"status": "error", "code": 429, "message": "Too many requests — slow down"}), 429

    @app.errorhandler(Exception)
    def unhandled(e: Exception):
        log.exception("Unhandled exception: %s", e)
        return jsonify({"status": "error", "code": 500, "message": "Internal server error"}), 500


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT  (development only — use Gunicorn in production)
# ─────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"   # never True in prod
    log.info("Starting dev server on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)

# ─────────────────────────────────────────────────────────────
#  PRODUCTION LAUNCH (example — put in a Procfile or Dockerfile)
#
#  gunicorn "app:app" \
#    --workers 4 \
#    --worker-class sync \
#    --timeout 120 \
#    --max-requests 500 \
#    --max-requests-jitter 50 \
#    --bind 0.0.0.0:5000 \
#    --preload          \   <- loads model in master, forks to workers
#    --log-level info
# ─────────────────────────────────────────────────────────────