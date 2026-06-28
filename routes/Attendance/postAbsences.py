from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
import time

from config.config import supabase
from services.absence_image import generate_absence_image

absence_post_bp = Blueprint("absence_post", __name__)


def init_absence_routes():

    @absence_post_bp.route("/absence", methods=["POST"])
    def create_absence():
        try:
            # =========================
            # GET FORM DATA
            # =========================
            name = request.form.get("name")
            time_value = request.form.get("time")
            latitude = request.form.get("latitude")
            longitude = request.form.get("longitude")
            street = request.form.get("street")

            file = request.files.get("image")

            # =========================
            # VALIDATION
            # =========================
            if not file:
                return jsonify({"error": "Image required"}), 400

            if not name:
                return jsonify({"error": "Name required"}), 400

            # =========================
            # TIME NOW UTC
            # =========================
            now = datetime.now(timezone.utc)

            # awal hari UTC
            start_of_day = now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )

            # akhir hari UTC
            end_of_day = now.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999
            )

            # =========================
            # CHECK ABSENCE TODAY
            # =========================
            response = (
                supabase.table("absences")
                .select("id")
                .eq("name", name)
                .gte("created_at", start_of_day.isoformat())
                .lte("created_at", end_of_day.isoformat())
                .limit(1)
                .execute()
            )

            existing = response.data

            if existing:
                return jsonify({
                    "success": False,
                    "error": "Kamu sudah absen hari ini"
                }), 400

            # =========================
            # PARSE STREET
            # =========================
            parts = [p.strip() for p in street.split(",")]

            street_name = parts[0] if len(parts) > 0 else street

            district = parts[2] if len(parts) > 2 else ""
            province = parts[4] if len(parts) > 4 else ""
            country = parts[-1] if len(parts) > 0 else ""

            title_location = f"{district}, {province}, {country}"

            # =========================
            # GENERATE IMAGE
            # =========================
            final_buffer = generate_absence_image(
                image_file=file.stream,
                title_location=title_location,
                street=street_name,
                latitude=latitude,
                longitude=longitude,
                time_value=time_value,
            )

            # =========================
            # UPLOAD IMAGE
            # =========================
            filename = f"absence-{int(time.time())}.jpg"

            supabase.storage.from_("absence").upload(
                path=filename,
                file=final_buffer.read(),
                file_options={"content-type": "image/jpeg"},
            )

            # =========================
            # GET PUBLIC URL
            # =========================
            img_url = supabase.storage.from_("absence").get_public_url(filename)

            # =========================
            # INSERT DATABASE
            # =========================
            (
                supabase.table("absences")
                .insert(
                    {
                        "name": name,
                        "time": time_value,
                        "latitude": latitude,
                        "longitude": longitude,
                        "street": street,
                        "img_url": img_url,
                        "created_at": now.isoformat(),
                    }
                )
                .execute()
            )

            return jsonify({
                "success": True,
                "img_url": img_url
            })

        except Exception as e:
            import traceback
            traceback.print_exc()

            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    return absence_post_bp