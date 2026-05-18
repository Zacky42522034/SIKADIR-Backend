from flask import Blueprint, jsonify, current_app
from datetime import datetime

not_present_bp = Blueprint("not_present", __name__)


@not_present_bp.get("/", strict_slashes=False)
def get_not_present():
    try:
        supabase = current_app.supabase

        result = (
            supabase.table("not_present")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )

        data = result.data or []

        safe_data = []

        for item in data:

            # =========================
            # SAFE CREATED_AT
            # =========================
            raw_time = item.get("created_at")

            if raw_time:
                try:
                    dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                    formatted_time = dt.strftime("%d-%m-%Y %H:%M:%S")
                except:
                    formatted_time = str(raw_time)
            else:
                formatted_time = ""   # 🔥 PENTING: jangan null

            # =========================
            # SAFE DATE (kalau frontend pakai date.split)
            # =========================
            raw_date = item.get("date")

            if raw_date is None:
                raw_date = ""  # 🔥 FIX split error

            # =========================
            # BUILD SAFE OBJECT
            # =========================
            safe_data.append({
                **item,

                # 🔥 KUNCI FIX UTAMA
                "created_at": raw_time or "",
                "created_at_local": formatted_time,

                # 🔥 ANTI SPLIT CRASH
                "date": raw_date
            })

        return jsonify({
            "success": True,
            "data": safe_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "data": []   # 🔥 jangan null
        }), 500