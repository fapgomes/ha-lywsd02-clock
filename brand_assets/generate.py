#!/usr/bin/env python3
"""Generate HA brand icons for lywsd02_clock.

Produces icon.png / icon@2x.png in sizes required by home-assistant/brands.
Design: dark rounded-square clock body with a white e-Ink-style display
showing "12:34" and "23°C".
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
FONT_PATH = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed-Bold.ttf"

WHITE = (248, 248, 246, 255)
DARK = (32, 33, 37, 255)
TRANSPARENT = (0, 0, 0, 0)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int) -> ImageFont.FreeTypeFont:
    """Pick the largest font size such that text fits within max_width."""
    size = max_size
    while size > 8:
        font = ImageFont.truetype(FONT_PATH, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(FONT_PATH, 8)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    # Outer body: dark rounded square
    pad = size // 16
    corner = size // 7
    body_box = (pad, pad, size - pad - 1, size - pad - 1)
    draw.rounded_rectangle(body_box, radius=corner, fill=DARK)

    # Inner display: white rounded rectangle
    inner_pad = size // 9
    inner_left = pad + inner_pad
    inner_top = pad + inner_pad
    inner_right = size - pad - inner_pad - 1
    inner_bottom = size - pad - inner_pad - 1
    inner_w = inner_right - inner_left
    inner_h = inner_bottom - inner_top
    inner_corner = max(4, corner // 2)
    draw.rounded_rectangle(
        (inner_left, inner_top, inner_right, inner_bottom),
        radius=inner_corner,
        fill=WHITE,
    )

    # Usable text area (inside display with horizontal padding)
    text_pad = int(inner_w * 0.08)
    text_max_w = inner_w - 2 * text_pad

    # Time text fits ~65% of inner height
    time_text = "12:34"
    time_font = _fit_font(draw, time_text, text_max_w, int(inner_h * 0.62))
    bbox = draw.textbbox((0, 0), time_text, font=time_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = inner_left + (inner_w - tw) // 2 - bbox[0]
    ty = inner_top + int(inner_h * 0.12) - bbox[1]
    draw.text((tx, ty), time_text, font=time_font, fill=DARK)

    # Temperature text below time, smaller
    temp_text = "23°C"
    temp_font = _fit_font(draw, temp_text, int(text_max_w * 0.65), int(inner_h * 0.28))
    bbox2 = draw.textbbox((0, 0), temp_text, font=temp_font)
    tw2 = bbox2[2] - bbox2[0]
    tx2 = inner_left + (inner_w - tw2) // 2 - bbox2[0]
    ty2 = inner_top + int(inner_h * 0.68) - bbox2[1]
    draw.text((tx2, ty2), temp_text, font=temp_font, fill=DARK)

    return img


def main() -> None:
    draw_icon(256).save(OUT / "icon.png")
    draw_icon(512).save(OUT / "icon@2x.png")
    print("Generated:")
    for f in sorted(OUT.glob("*.png")):
        print(f"  {f.name}  {Image.open(f).size}")


if __name__ == "__main__":
    main()
