from flask import Blueprint, jsonify, current_app, make_response
import traceback

users_bp = Blueprint("users", __name__)

@users_bp.route("/users", methods=["GET"])
def get_users():
    try:
        supabase = current_app.supabase

        result = (
            supabase
            .table("users")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )

        data = result.data if result.data else []

        response = make_response(jsonify({
            "success": True,
            "data": data
        }))

        response.headers["Cache-Control"] = "no-store"

        return response

    except Exception as e:
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500