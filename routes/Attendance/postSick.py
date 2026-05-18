import os
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename

from ..Utils.telegram import send_telegram_photo

sick_bp = Blueprint("sick", __name__)

# =========================
# POST /api/sakit
# =========================
@sick_bp.post("/sakit")
def sick():
    try:
        supabase = current_app.supabase

        name = request.form.get("name")
        alasan = request.form.get("alasan")
        file = request.files.get("image")

        # =========================
        # VALIDASI
        # =========================
        if not file:
            return jsonify({"error": "Image required"}), 400

        if not name:
            return jsonify({"error": "Name required"}), 400

        now = datetime.utcnow()

        # =========================
        # CEK SUDAH ADA PENGAJUAN HARI INI
        # =========================
        start_of_day = datetime(now.year, now.month, now.day)
        end_of_day = start_of_day + timedelta(days=1)

        check = supabase.table("not_present") \
            .select("id, type") \
            .eq("name", name) \
            .gte("created_at", start_of_day.isoformat()) \
            .lt("created_at", end_of_day.isoformat()) \
            .limit(1) \
            .execute()

        existing = check.data

        if existing:
            return jsonify({
                "success": False,
                "error": f"Kamu sudah mengajukan {existing[0]['type']} hari ini"
            }), 400

        # =========================
        # UPLOAD IMAGE KE SUPABASE STORAGE
        # =========================
        bucket = "sick"
        file_name = f"sakit-{int(datetime.now().timestamp())}.jpg"

        supabase.storage.from_(bucket).upload(
            file_name,
            file.read(),
            {
                "content-type": file.content_type
            }
        )

        img_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{bucket}/{file_name}"

        # =========================
        # INSERT DATABASE
        # =========================
        data = supabase.table("not_present").insert({
            "name": name,
            "type": "sakit",
            "alasan": alasan,
            "img_url": img_url,
            "status": "proses",
            "created_at": now.isoformat()
        }).execute()

        # =========================
        # TELEGRAM NOTIF
        # =========================
        caption = f"""
<b>🤒 Pengajuan SAKIT</b>

👤 Nama: {name}
📝 Alasan: {alasan or "-"}

🕒 {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
"""

        try:
            send_telegram_photo(img_url, caption)
        except Exception as e:
            print("❌ Telegram error:", str(e))

        return jsonify({
            "success": True,
            "img_url": img_url
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500