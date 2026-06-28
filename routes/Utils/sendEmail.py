from flask import Blueprint, request, jsonify
from flask_mail import Message

from routes.Utils.mail_config import mail

send_email_bp = Blueprint("send_email", __name__)


def init_email_routes():

    @send_email_bp.route("/send-email", methods=["POST"])
    def send_email():
        try:
            # =========================
            # GET FORM DATA
            # =========================
            name = request.form.get("name")
            email = request.form.get("email")
            message = request.form.get("message")

            # =========================
            # VALIDATION
            # =========================
            if not name:
                return jsonify({
                    "success": False,
                    "error": "Name required"
                }), 400

            if not email:
                return jsonify({
                    "success": False,
                    "error": "Email required"
                }), 400

            if not message:
                return jsonify({
                    "success": False,
                    "error": "Message required"
                }), 400

            # =========================
            # CREATE EMAIL
            # =========================
            msg = Message(
                subject=f"Pesan Baru Dari {name}",
                sender="your_email@gmail.com",
                recipients=["tujuan@gmail.com"]
            )

            msg.body = f"""
=========================
PESAN WEBSITE
=========================

Nama   : {name}
Email  : {email}

Pesan:
{message}
"""

            # =========================
            # SEND EMAIL
            # =========================
            mail.send(msg)

            return jsonify({
                "success": True,
                "message": "Email berhasil dikirim"
            })

        except Exception as e:
            import traceback
            traceback.print_exc()

            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    return send_email_bp