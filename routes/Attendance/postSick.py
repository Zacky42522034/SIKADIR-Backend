import os
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
import time

from ..Utils.telegram import send_telegram_photo

sick_bp = Blueprint("sick", __name__)


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
        # CEK SUDAH ADA PENGAJUAN
        # =========================
        start_of_day = datetime(now.year, now.month, now.day)
        end_of_day = start_of_day + timedelta(days=1)

        check = (
            supabase.table("not_present")
            .select("id, type")
            .eq("name", name)
            .gte("created_at", start_of_day.isoformat())
            .lt("created_at", end_of_day.isoformat())
            .limit(1)
            .execute()
        )

        existing = check.data

        if existing:
            return jsonify({
                "success": False,
                "error": f"Kamu sudah mengajukan {existing[0]['type']} hari ini"
            }), 400

        # =========================
        # READ FILE SEKALI
        # =========================
        file_bytes = file.read()

        # =========================
        # UPLOAD IMAGE
        # =========================
        bucket = "sick"
        file_name = f"sakit-{int(time.time())}.jpg"

        supabase.storage.from_(bucket).upload(
            path=file_name,
            file=file_bytes,
            file_options={
                "content-type": file.content_type,
                "upsert": "true"
            }
        )

        # =========================
        # GET PUBLIC URL
        # =========================
        img_url = supabase.storage.from_(bucket).get_public_url(file_name)

        print("IMG URL:", img_url)

        # =========================
        # INSERT DATABASE
        # =========================
        supabase.table("not_present").insert({
            "name": name,
            "type": "sakit",
            "alasan": alasan,
            "img_url": img_url,
            "status": "proses",
            "created_at": now.isoformat()
        }).execute()

        supabase.table("absences").insert({
            "name": name,
            "type": "sakit",
            "alasan": alasan,
            "img_url": img_url,
            "created_at": now.isoformat()
        }).execute()

        # =========================
        # TELEGRAM NOTIFICATION
        # =========================
        caption = f"""
🤒 Pengajuan SAKIT

👤 Nama: {name}
📝 Alasan: {alasan or "-"}

🕒 {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
"""

        try:
            # KIRIM FILE LANGSUNG
            send_telegram_photo(file_bytes, caption)

            print("✅ Telegram success")

        except Exception as e:
            print("❌ Telegram error:", str(e))

        return jsonify({
            "success": True,
            "img_url": img_url
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500