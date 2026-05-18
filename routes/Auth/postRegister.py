import os
import bcrypt
import traceback
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image
from flask import Blueprint, request, jsonify, current_app

register_bp = Blueprint("register", __name__)


def get_supabase():
    return current_app.supabase


# =========================
# IMAGE COMPRESSION (IMPORTANT)
# =========================
def compress_image(file):
    img = Image.open(file)

    img = img.convert("RGB")
    img.thumbnail((800, 800))  # resize biar upload cepat

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=70, optimize=True)
    buffer.seek(0)

    return buffer


@register_bp.post("/register")
def register():
    try:
        print("\n🚀 ===== REGISTER START =====")
        supabase = get_supabase()

        # =========================
        # INPUT
        # =========================
        nama = request.form.get("nama")
        email = request.form.get("email")
        password = request.form.get("password")
        telepon = request.form.get("telepon")

        role = "user"
        file = request.files.get("photo")

        if not all([nama, email, password, telepon]):
            return jsonify({"success": False, "error": "Data tidak lengkap"}), 400

        if not file:
            return jsonify({"success": False, "error": "Foto wajib diupload"}), 400

        # =========================
        # CHECK EMAIL EXIST
        # =========================
        print("\n🔍 Checking email...")

        try:
            supabase.auth.admin.get_user_by_email(email)
            return jsonify({"success": False, "error": "Email sudah terdaftar"}), 409
        except:
            pass

        # =========================
        # COMPRESS IMAGE (FAST UPLOAD)
        # =========================
        print("\n🖼 Compressing image...")
        file_bytes = compress_image(file)

        # =========================
        # CREATE AUTH USER
        # =========================
        print("\n🔥 Creating Supabase user...")

        auth_response = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {
                "display_name": nama,
                "phone": telepon
            }
        })

        user = getattr(auth_response, "user", None)

        if not user:
            return jsonify({"success": False, "error": "Gagal membuat user Auth"}), 400

        user_id = user.id
        print("✅ User ID:", user_id)

        # =========================
        # UPLOAD PHOTO (FAST)
        # =========================
        print("\n📤 Uploading photo...")

        file_name = f"{user_id}.jpg"

        supabase.storage.from_("faces").upload(
            file_name,
            file_bytes.read(),
            {"content-type": "image/jpeg"}
        )

        # direct URL (lebih cepat dari get_public_url)
        image_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/faces/{file_name}"

        # =========================
        # HASH PASSWORD
        # =========================
        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # =========================
        # INSERT DATABASE
        # =========================
        print("\n💾 Inserting into database...")

        result = supabase.table("users").insert({
            "id": user_id,
            "name": nama,
            "nomor": telepon,
            "email": email,
            "password": hashed_password,
            "img_url": image_url,
            "role" : role,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()

        if hasattr(result, "error") and result.error:
            print("❌ DB ERROR:", result.error)
            return jsonify({
                "success": False,
                "error": "Gagal insert ke database",
                "detail": str(result.error)
            }), 500

        print("\n🎉 REGISTER SUCCESS")

        return jsonify({
            "success": True,
            "message": "Registrasi berhasil",
            "userId": user_id,
            "image_url": image_url
        })

    except Exception as e:
        print("\n❌ REGISTER ERROR")
        print("TYPE:", type(e).__name__)
        print("MESSAGE:", str(e))
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e),
            "type": type(e).__name__
        }), 500