from flask import Blueprint, jsonify, current_app, Response

absence_get_bp = Blueprint("absence_get", __name__)

# =========================
# GET /api/absence
# =========================
@absence_get_bp.get("/", strict_slashes=False)
def get_absences():
    try:
        # =========================
        # NO CACHE (set header)
        # =========================
        response = Response()
        response.headers["Cache-Control"] = "no-store"

        supabase = current_app.supabase

        # =========================
        # QUERY SUPABASE
        # =========================
        result = supabase.table("absences") \
            .select("*") \
            .order("created_at", desc=True) \
            .execute()

        data = result.data

        return jsonify({
            "success": True,
            "data": data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500