from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app

from ..Utils.telegram import send_telegram_message

permission_bp = Blueprint("permission", __name__)

# =========================
# POST /api/izin-cuti
# =========================
@permission_bp.post("/izin-cuti")
def izin_cuti():
    try:
        supabase = current_app.supabase

        data = request.get_json()

        name = data.get("name")
        type_ = data.get("type")
        alasan = data.get("alasan")
        deskripsi = data.get("deskripsi")

        # =========================
        # VALIDASI
        # =========================
        if not name or not type_:
            return jsonify({"error": "Name dan type wajib"}), 400

        now = datetime.utcnow()

        # =========================
        # CEK PENGAJUAN HARI INI
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
        # INSERT DATA
        # =========================
        insert = supabase.table("not_present").insert({
            "name": name,
            "type": type_,
            "alasan": alasan,
            "deskripsi": deskripsi,
            "status": "proses",
            "created_at": now.isoformat()
        }).execute()

        record = insert.data[0]

        # =========================
        # TELEGRAM
        # =========================
        message = f"""
<b>📢 Pengajuan {type_.upper()}</b>

👤 Nama: {name}
📌 Tipe: {type_}
📝 Alasan: {alasan or "-"}
📄 Deskripsi: {deskripsi or "-"}

🕒 {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
"""

        try:
            send_telegram_message(message, record["id"])
        except Exception as e:
            print("❌ Telegram error:", str(e))

        return jsonify({
            "success": True,
            "id": record["id"]
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500