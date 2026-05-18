from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import requests


def wrap_text_by_pixel(draw, text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + " " + word if current_line else word

        bbox = draw.textbbox((0, 0), test_line, font=font)
        text_width = bbox[2] - bbox[0]

        if text_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return "\n".join(lines)


def generate_absence_image(
    image_file, title_location, street, latitude, longitude, time_value
):
    # =========================
    # LOAD IMAGE
    # =========================
    base = Image.open(image_file).convert("RGBA")
    canvas_width, canvas_height = base.size

    latitude_float = float(latitude)
    longitude_float = float(longitude)

    # =========================
    # DOWNLOAD MAP
    # =========================
    zoom = 16
    map_width = 75
    map_height = 75

    map_url = (
        f"https://static-maps.yandex.ru/1.x/"
        f"?ll={longitude},{latitude}"
        f"&z={zoom}"
        f"&size={map_width},{map_height}"
        f"&l=map"
        f"&pt={longitude},{latitude},pm2rdm"
    )

    map_response = requests.get(map_url, timeout=10)

    if map_response.status_code != 200:
        raise Exception("Gagal mengambil map")

    map_img = Image.open(BytesIO(map_response.content)).convert("RGBA")

    # =========================
    # OVERLAY BOX
    # =========================
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    margin = 14
    box_height = 100

    box_x0 = margin
    box_y0 = canvas_height - box_height - margin
    box_x1 = canvas_width - margin
    box_y1 = canvas_height - margin

    overlay_draw.rounded_rectangle(
        [box_x0, box_y0, box_x1, box_y1], radius=18, fill=(0, 0, 0, 145)
    )

    base = Image.alpha_composite(base, overlay)

    # =========================
    # MAP POSITION
    # =========================
    map_x = box_x0 + 12
    map_y = box_y0 + 12

    mask = Image.new("L", map_img.size, 0)
    mask_draw = ImageDraw.Draw(mask)

    mask_draw.rounded_rectangle([0, 0, map_width, map_height], radius=12, fill=255)

    base.paste(map_img, (map_x, map_y), mask)

    # =========================
    # TEXT
    # =========================
    draw = ImageDraw.Draw(base)

    try:
        title_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            13
        )

        text_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            10
        )

    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()

    # =========================
    # MAX WIDTH TEXT AREA
    # =========================
    text_x = map_x + map_width + 12
    text_area_width = canvas_width - text_x - 20

    # =========================
    # TITLE WRAP (IMPORTANT FIX)
    # =========================
    full_title = f"Kecamatan\n{title_location}"
    title = wrap_text_by_pixel(draw, full_title, title_font, text_area_width)

    # =========================
    # STREET WRAP (FIX UTAMA)
    # =========================
    wrapped_street = wrap_text_by_pixel(draw, street, text_font, text_area_width)

    body = (
        f"{wrapped_street}\n"
        f"{latitude_float:.5f}, {longitude_float:.5f}\n"
        f"{time_value}"
    )

    text_y = map_y + 2

    # TITLE
    draw.multiline_text(
        (text_x, text_y), title, font=title_font, fill="white", spacing=2
    )

    title_bbox = draw.multiline_textbbox(
        (text_x, text_y), title, font=title_font, spacing=2
    )

    body_y = title_bbox[3] + 6

    # BODY
    draw.multiline_text(
        (text_x, body_y), body, font=text_font, fill=(225, 225, 225), spacing=2
    )

    # =========================
    # SAVE BUFFER
    # =========================
    final_buffer = BytesIO()
    base = base.convert("RGB")

    base.save(final_buffer, format="JPEG", quality=90, optimize=True)

    final_buffer.seek(0)

    return final_buffer
