import os
import jwt
import bcrypt
import datetime
from flask import Blueprint, request, jsonify
from supabase import create_client

# =========================
# BLUEPRINT
# =========================
auth_bp = Blueprint("auth", __name__)

# =========================
# SUPABASE INIT
# =========================
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# =========================
# POST /api/login
# =========================
@auth_bp.post("/login")
def login():
    try:
        data = request.get_json()

        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "Email dan password wajib"}), 400

        # =========================
        # GET USER FROM SUPABASE
        # =========================
        result = supabase.table("users") \
            .select("*") \
            .eq("email", email) \
            .limit(1) \
            .execute()

        users = result.data

        if not users:
            return jsonify({"error": "User tidak ditemukan"}), 404

        user = users[0]

        # =========================
        # CHECK PASSWORD
        # =========================
        is_valid = bcrypt.checkpw(
            password.encode("utf-8"),
            user["password"].encode("utf-8")
        )

        if not is_valid:
            return jsonify({"error": "Password salah"}), 401

        # =========================
        # JWT TOKEN
        # =========================
        payload = {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "img_url": user["img_url"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(days=1)
        }

        token = jwt.encode(
            payload,
            os.getenv("JWT_SECRET"),
            algorithm="HS256"
        )

        # =========================
        # RESPONSE
        # =========================
        return jsonify({
            "success": True,
            "token": token,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "img_url": user["img_url"],
                "role": user["role"]
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500