import os
import textwrap

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


def add_text_to_image(image_path, text, font_key="1", color="black", output_path=None, position="top", size_correction=None):
    image = Image.open(image_path)
    draw = ImageDraw.Draw(image)

    font_path = font_key

    font_size = 72 if image.width < 2000 else 120
    if size_correction: # -2 -1 / +1 +2
        font_size += (size_correction * 20)

    print('current font size:', font_size)

    if not os.path.exists(font_path):
        font = ImageFont.load_default()
    else:
        font = ImageFont.truetype(font_path, font_size)

    margin = 50
    max_width = image.width - 2 * margin

    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        test_line_width = bbox[2] - bbox[0]
        if test_line_width <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    line_spacing = 10
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_height = bbox[3] - bbox[1]
        line_heights.append(line_height)
    total_text_height = sum(line_heights) + (len(lines) - 1) * line_spacing

    if position == "top":
        y = margin + image.height * 0.1
    elif position == "center":
        y = (image.height - total_text_height) // 2
    elif position == "bottom":
        y = image.height - total_text_height - margin - image.height * 0.08
    else:
        y = margin

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (image.width - line_width) // 2
        draw.text((x, y), line, fill=color, font=font)
        y += line_heights[i] + line_spacing

    if output_path is None:
        output_path = image_path
    image.save(output_path)
    return output_path


def add_watermark(input_image_path, output_image_path, watermark_text="Оплатите картинку перед сохранением <3"):
    image = Image.open(input_image_path).convert("RGBA")

    if image.width < 500:
        font_size = 32
    elif image.width < 1000:
        font_size = 64
    else:
        font_size = 100

    font_path = "resources/fonts/arial.ttf"
    if os.path.exists(font_path):
        font = ImageFont.truetype(font_path, font_size)
    else:
        font = ImageFont.load_default()

    tmp_img = Image.new("RGBA", (0, 0))
    tmp_draw = ImageDraw.Draw(tmp_img)
    bbox = tmp_draw.textbbox((0, 0), watermark_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    watermark = Image.new("RGBA", image.size, (0, 0, 0, 0))

    count = 2 if image.width < 1000 else 3
    alpha = 150
    angle = 45

    for i in range(count):
        frac = (i + 1) / (count + 1)
        x_c = int(image.width * frac)
        y_c = int(image.height * frac)

        text_layer = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_layer)
        draw.text((0, 0), watermark_text, font=font, fill=(255, 255, 255, alpha))

        text_rot = text_layer.rotate(angle, expand=True)
        tw, th = text_rot.size

        paste_x = x_c - tw // 2
        paste_y = y_c - th // 2

        watermark.paste(text_rot, (paste_x, paste_y), text_rot)

    result = Image.alpha_composite(image, watermark).convert("RGB")
    result.save(output_image_path)


def add_number_overlay(input_image_path: str, output_image_path: str, number: int):
    """
    Накладывает порядковый номер в левом верхнем углу изображения.
    Размер шрифта, отступы и цвета задаются по умолчанию внутри функции.
    """
    image = Image.open(input_image_path).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = 360

    font_path = "resources/fonts/1.ttf"
    if os.path.exists(font_path):
        font = ImageFont.truetype(font_path, font_size)
    else:
        font = ImageFont.load_default()

    text = str(number)
    margin = 50

    fill_color = (255, 255, 255, 255)
    outline_color = (0, 0, 0, 255)
    outline_width = 2

    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((margin + dx, margin + dy), text, font=font, fill=outline_color)

    draw.text((margin, margin), text, font=font, fill=fill_color)

    result = Image.alpha_composite(image, overlay).convert("RGB")
    result.save(output_image_path)


async def generate_font_sample(font_path: Path, sample_path: Path, size: int, text: str):
    img_size = 2048
    img = Image.new('RGB', (img_size, img_size), 'white')
    draw = ImageDraw.Draw(img)
    try:
        ft = ImageFont.truetype(str(font_path), size=size)
    except:
        ft = ImageFont.load_default()

    lines = textwrap.wrap(text, width=20)
    spacing = 10

    ascent, descent = ft.getmetrics()
    line_height = ascent + descent

    total_h = line_height * len(lines) + spacing * (len(lines) - 1)

    y = (img_size - total_h) / 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=ft)
        w = bbox[2] - bbox[0]
        x = (img_size - w) / 2
        draw.text((x, y), line, font=ft, fill='black')
        y += line_height + spacing

    img.save(sample_path)
