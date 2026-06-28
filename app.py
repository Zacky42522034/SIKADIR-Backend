from dotenv import load_dotenv
import os

from flask import Flask, jsonify
from flask_cors import CORS
from flask_mail import Mail
from supabase import create_client

# =========================
# LOAD ENV
# =========================
load_dotenv()

# =========================
# APP INIT
# =========================
app = Flask(__name__)

# =========================
# CORS
# =========================
CORS(
    app,
    supports_credentials=True,
    resources={
        r"/*": {
            "origins": [
                "https://frontss.loophole.site",
                "http://localhost:3000"
            ],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        }
    },
)

# =========================
# SECRET KEY
# =========================
app.config["SECRET_KEY"] = os.getenv("JWT_SECRET")

# =========================
# MAIL CONFIG
# =========================
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT"))
app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS") == "True"

app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

# =========================
# INIT MAIL
# =========================
from routes.Utils.mail_config import mail

mail.init_app(app)

# =========================
# SUPABASE INIT
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

# =========================
# FACE RECOGNITION
# =========================
from routes.recognize import init_routes

# =========================
# UTILS
# =========================
from routes.Utils.webhook import telegram_bp
from routes.Utils.sendEmail import init_email_routes

# =========================
# INIT ROUTES
# =========================
absence_post_bp = init_absence_routes()
recognize_bp = init_routes(fr)
send_email_bp = init_email_routes()

# =========================
# REGISTER BLUEPRINTS
# =========================

# AUTH
app.register_blueprint(auth_bp, url_prefix="/api")
app.register_blueprint(logout_bp, url_prefix="/api/auth")
app.register_blueprint(users_bp, url_prefix="/api")
app.register_blueprint(register_bp, url_prefix="/api")

# ATTENDANCE
app.register_blueprint(absence_post_bp, url_prefix="/api")
app.register_blueprint(absence_get_bp, url_prefix="/api/absences")

app.register_blueprint(sick_bp, url_prefix="/api")
app.register_blueprint(permission_bp, url_prefix="/api")
app.register_blueprint(not_present_bp, url_prefix="/api/not_present")

# FACE RECOGNITION
app.register_blueprint(recognize_bp, url_prefix="/api")

# EMAIL
app.register_blueprint(send_email_bp, url_prefix="/api")

# UTILS
app.register_blueprint(telegram_bp, url_prefix="/api")

# =========================
# HEALTH CHECK
# =========================
@app.route("/")
def home():
    return jsonify({
        "status": "OK",
        "message": "Flask API aktif"
    })

# =========================
# ERROR HANDLER
# =========================
@app.errorhandler(Exception)
def error(e):
    return jsonify({
        "status": "ERROR",
        "message": str(e)
    }), 500

# =========================
# RUN SERVER
# =========================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    print(f"🚀 Flask running on port {port}")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )