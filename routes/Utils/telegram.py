import os
import requests


# =========================
# SEND MESSAGE
# =========================
def send_telegram_message(text, id=None):

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    # DEBUG
    print("📌 TELEGRAM SEND ID:", id)

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Konfirmasi", "callback_data": f"approve|{id}"},
                    {"text": "❌ Tolak", "callback_data": f"reject|{id}"},
                ]
            ]
        },
    }

    response = requests.post(url, json=payload, timeout=10)

    # DEBUG
    print("📩 TELEGRAM RESPONSE:", response.text)

    return response.json()


# =========================
# SEND PHOTO
# =========================
def send_telegram_photo(file_bytes, caption):

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    files = {"photo": ("sakit.jpg", file_bytes, "image/jpeg")}

    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}

    response = requests.post(url, data=data, files=files, timeout=30)

    print(response.status_code)
    print(response.text)

    response.raise_for_status()

    return response.json()
