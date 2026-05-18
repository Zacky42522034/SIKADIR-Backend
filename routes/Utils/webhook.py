import os
import uuid
import requests

from flask import Blueprint, request, jsonify, current_app

telegram_bp = Blueprint("telegram", __name__)


@telegram_bp.post("/telegram-webhook")
def telegram_webhook():

    try:

        data = request.get_json()

        print("📩 TELEGRAM HIT:", data)

        callback_query = data.get("callback_query")

        if not callback_query:
            return jsonify({
                "success": False
            }), 200

        callback_data = callback_query.get("data")

        if not callback_data:
            return jsonify({
                "success": False
            }), 400

        print("📌 CALLBACK:", callback_data)

        action, id_ = callback_data.split("|")

        print("🆔 UUID:", id_)

        # VALIDASI UUID
        uuid.UUID(id_)

        # =========================
        # STATUS
        # =========================
        if action == "approve":
            status = "approved"
            status_text = "✅ APPROVED"

        elif action == "reject":
            status = "rejected"
            status_text = "❌ REJECTED"

        else:
            return jsonify({
                "success": False,
                "error": "Invalid action"
            }), 400

        # =========================
        # TELEGRAM INFO
        # =========================
        token = os.getenv("TELEGRAM_BOT_TOKEN")

        message = callback_query["message"]

        chat_id = message["chat"]["id"]
        message_id = message["message_id"]

        old_text = message.get("text", "")

        # =========================
        # ANTI DOUBLE CLICK
        # =========================
        if "Status:" in old_text:

            # jawab callback cepat
            requests.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={
                    "callback_query_id": callback_query["id"],
                    "text": "Sudah diproses",
                    "show_alert": False
                },
                timeout=3
            )

            return jsonify({
                "success": True,
                "message": "Already processed"
            }), 200

        # =========================
        # JAWAB CALLBACK DULU
        # SUPER PENTING
        # =========================
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={
                "callback_query_id": callback_query["id"],
                "text": "Diproses...",
                "show_alert": False
            },
            timeout=3
        )

        # =========================
        # LANGSUNG HAPUS TOMBOL
        # =========================
        requests.post(
            f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {
                    "inline_keyboard": []
                }
            },
            timeout=5
        )

        # =========================
        # SUPABASE
        # =========================
        supabase = current_app.supabase

        updated = (
            supabase.table("not_present")
            .update({
                "status": status
            })
            .eq("id", str(id_))
            .execute()
        )

        print("🛠 UPDATE RESULT:", updated.data)

        # =========================
        # UPDATE MESSAGE TEXT
        # =========================
        new_text = f"{old_text}\n\nStatus: {status_text}"

        edit_response = requests.post(
            f"https://api.telegram.org/bot{token}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_text
            },
            timeout=5
        )

        print("✏️ EDIT RESPONSE:", edit_response.text)

        return jsonify({
            "success": True,
            "status": status
        }), 200

    except Exception as e:

        print("❌ WEBHOOK ERROR:", str(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500