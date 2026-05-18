from flask import Blueprint, jsonify

logout_bp = Blueprint("logout", __name__)

# =========================
# POST /api/auth/logout
# =========================
@logout_bp.post("/logout")
def logout():
    return jsonify({
        "success": True,
        "message": "Logout berhasil (hapus token di frontend)"
    })