from dotenv import load_dotenv
import os
from flask import Flask, jsonify
from flask_cors import CORS
from supabase import create_client

# =========================
# LOAD ENV (ONLY ONCE)
# =========================
load_dotenv()

# =========================
# APP INIT
# =========================
app = Flask(__name__)

# =========================
# CORS SETUP (WAJIB DI SINI)
# =========================
CORS(
    app,
    supports_credentials=True,
    resources={
        r"/*": {
            "origins": ["https://frontss.loophole.site", "http://localhost:3000"],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
)

app.config["SECRET_KEY"] = os.getenv("JWT_SECRET")

# =========================
# SUPABASE INIT (GLOBAL)
# =========================
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
)

app.supabase = supabase

# =========================
# FACE RECOGNITION INIT
# =========================
from face_module.face_service2 import FaceRecognition

fr = FaceRecognition()

# =========================
# AUTH
# =========================
from routes.Auth.postLogin import auth_bp
from routes.Auth.postLogout import logout_bp
from routes.Auth.getusers import users_bp
from routes.Auth.postRegister import register_bp

# =========================
# ATTENDANCE
# =========================
from routes.Attendance.postAbsences import init_absence_routes
from routes.Attendance.getAbsences import absence_get_bp
from routes.Attendance.postSick import sick_bp
from routes.Attendance.postPermission import permission_bp
from routes.Attendance.getSickPermission import not_present_bp
from routes.recognize import init_routes
from face_module.face_service2 import FaceRecognition

# init absence route
absence_post_bp = init_absence_routes()
# =========================
# FACE RECOGNITION ROUTE
# =========================
from routes.recognize import init_routes

recognize_bp = init_routes(fr)

# =========================
# UTILS
# =========================
from routes.Utils.webhook import telegram_bp

# =========================
# REGISTER BLUEPRINTS
# =========================


# AUTH
app.register_blueprint(auth_bp, url_prefix="/api")
app.register_blueprint(logout_bp, url_prefix="/api/auth")
app.register_blueprint(users_bp, url_prefix="/api")
app.register_blueprint(register_bp, url_prefix="/api")

# ATTENDANCE
app.register_blueprint(absence_post_bp, url_prefix="/api/")
app.register_blueprint(absence_get_bp, url_prefix="/api/absences")

app.register_blueprint(sick_bp, url_prefix="/api")
app.register_blueprint(permission_bp, url_prefix="/api")
app.register_blueprint(not_present_bp, url_prefix="/api/not_present")

# FACE RECOGNITION
app.register_blueprint(recognize_bp, url_prefix="/api")

# UTILS
app.register_blueprint(telegram_bp, url_prefix="/api")


# =========================
# HEALTH CHECK
# =========================
@app.route("/")
def home():
    return jsonify({"status": "OK", "message": "Flask API aktif"})


# =========================
# ERROR HANDLER
# =========================
@app.errorhandler(Exception)
def error(e):
    return jsonify({"status": "ERROR", "message": str(e)}), 500


# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 Flask running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
