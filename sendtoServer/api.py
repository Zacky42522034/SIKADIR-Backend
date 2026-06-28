import requests
import os
import re

from PIL import Image, ImageOps
from io import BytesIO

# ==============================
# CONFIG
# ==============================
API_URL = "https://sikadir.web.id/api/register"

PHOTO_FOLDER = "photos"

# ==============================
# FIX IMAGE ORIENTATION
# ==============================
def fix_image_orientation(image_path):

    image = Image.open(image_path)

    # otomatis perbaiki rotation EXIF
    image = ImageOps.exif_transpose(image)

    # convert ke RGB
    image = image.convert("RGB")

    # simpan ke memory
    img_bytes = BytesIO()

    image.save(
        img_bytes,
        format="JPEG",
        quality=90
    )

    img_bytes.seek(0)

    return img_bytes

# ==============================
# DATA MANUAL
# ==============================
users = [
    {
        "nama": "andy",
        "telepon": "082271114597",
        "telegram": "@andymaulanamakmur",
        "role": "user",
    },
    {
        "nama": "kristin",
        "telepon": "085255479212",
        "telegram": "@iinonggg",
        "role": "user",
    },
    {
        "nama": "Ima",
        "telepon": "0811442906",
        "telegram": "@andirifaatulm",
        "role": "user",
    },
    {
        "nama": "zulfhami",
        "telepon": "081295375133",
        "telegram": "alert_defcon_1",
        "role": "user",
    },
    {
        "nama": "sugeng",
        "telepon": "081144702070",
        "telegram": "@Sugeng_Sulis",
        "role": "user",
    },
    {
        "nama": "maman",
        "telepon": "085104392361",
        "telegram": "mamankts",
        "role": "user",
    },
    {
        "nama": "teguh",
        "telepon": "081356045355",
        "telegram": "@teguhyogo",
        "role": "user",
    },
    {
        "nama": "Lea",
        "telepon": "085255222753",
        "telegram": "@leadaswati",
        "role": "user",
    },
]

# ==============================
# LOOP USER
# ==============================
for user in users:

    try:
        nama = user["nama"]
        telepon = user["telepon"]
        telegram = user["telegram"]
        role = user["role"]

        # ==============================
        # GENERATE USERNAME & EMAIL
        # ==============================
        username = telegram.replace("@", "").strip().lower()

        username = re.sub(
            r"[^a-zA-Z0-9._]",
            "",
            username
        )

        email = f"{username}@gmail.com"

        # password default
        password = "12345678"

        # ==============================
        # CARI FOTO
        # ==============================
        possible_files = [
            os.path.join(PHOTO_FOLDER, f"{username}.jpg"),
            os.path.join(PHOTO_FOLDER, f"{username}.jpeg"),
            os.path.join(PHOTO_FOLDER, f"{username}.png"),
        ]

        photo_path = None

        for file_path in possible_files:

            if os.path.exists(file_path):
                photo_path = file_path
                break

        print(f"\n🚀 REGISTER: {nama}")
        print("📧 EMAIL:", email)
        print("👤 ROLE:", role)

        # ==============================
        # VALIDASI FOTO
        # ==============================
        if not photo_path:
            print(f"❌ Foto {username} tidak ditemukan")
            continue

        print("🖼 FOTO:", photo_path)

        # ==============================
        # FIX IMAGE ORIENTATION
        # ==============================
        fixed_image = fix_image_orientation(photo_path)

        # ==============================
        # FORM DATA
        # ==============================
        data = {
            "nama": nama,
            "email": email,
            "password": password,
            "telepon": telepon,
            "role": role
        }

        # ==============================
        # FILE
        # ==============================
        files = {
            "photo": (
                f"{username}.jpg",
                fixed_image,
                "image/jpeg"
            )
        }

        # ==============================
        # REQUEST API
        # ==============================
        response = requests.post(
            API_URL,
            data=data,
            files=files,
            timeout=120
        )

        print("STATUS:", response.status_code)

        # ==============================
        # RESPONSE
        # ==============================
        try:
            print("RESPONSE:", response.json())
        except:
            print("TEXT:", response.text)

    except Exception as e:
        print("❌ ERROR:", str(e))