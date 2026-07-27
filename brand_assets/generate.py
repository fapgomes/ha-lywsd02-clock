#!/usr/bin/env python3
"""Generate HA brand images for lywsd02_clock.

Produces the PNG set expected by Home Assistant (icon, logo and dark_logo,
normal and @2x) in ``custom_components/lywsd02_clock/brand/``, which HA
2026.3.0+ serves locally in preference to the brands CDN.

Design: dark rounded-square clock body with a white e-Ink-style display
showing "12:34" and "23°C" — a neutral mark, no third-party trademarks.

Sizes follow https://github.com/home-assistant/brands#requirements:
  icon  -> 256x256 (1:1) and 512x512 for @2x
  logo  -> landscape, shortest side 128-256 (normal) and 256-512 (@2x)
Images are trimmed of empty edges, transparent, optimised and interlaced.

Usage: python3 brand_assets/generate.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "lywsd02_clock" / "brand"
FONT_PATH = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed-Bold.ttf"
FONT_BOLD = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"

WHITE = (248, 248, 246, 255)
DARK = (32, 33, 37, 255)
TRANSPARENT = (0, 0, 0, 0)

TEXT_LIGHT = ((0x1B, 0x2A, 0x33, 0xFF), (0x54, 0x6E, 0x7A, 0xFF))
TEXT_DARK = ((0xFF, 0xFF, 0xFF, 0xFF), (0xB0, 0xBE, 0xC5, 0xFF))

# Everything is drawn at this size and downscaled, for clean antialiasing.
RENDER = 1280


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


def draw_clock(size: int) -> Image.Image:
    """The clock glyph, drawn edge to edge (no margins) at ``size``."""
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    corner = size // 7
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=corner, fill=DARK)

    # Inner display: white rounded rectangle
    inner_pad = size // 9
    inner_left = inner_top = inner_pad
    inner_right = inner_bottom = size - inner_pad - 1
    inner_w = inner_right - inner_left
    inner_h = inner_bottom - inner_top
    draw.rounded_rectangle(
        (inner_left, inner_top, inner_right, inner_bottom),
        radius=max(4, corner // 2),
        fill=WHITE,
    )

    # Usable text area (inside display with horizontal padding)
    text_max_w = inner_w - 2 * int(inner_w * 0.08)

    # Time text fits ~65% of inner height
    time_text = "12:34"
    time_font = _fit_font(draw, time_text, text_max_w, int(inner_h * 0.62))
    bbox = draw.textbbox((0, 0), time_text, font=time_font)
    tx = inner_left + (inner_w - (bbox[2] - bbox[0])) // 2 - bbox[0]
    ty = inner_top + int(inner_h * 0.12) - bbox[1]
    draw.text((tx, ty), time_text, font=time_font, fill=DARK)

    # Temperature text below time, smaller
    temp_text = "23°C"
    temp_font = _fit_font(draw, temp_text, int(text_max_w * 0.65), int(inner_h * 0.28))
    bbox2 = draw.textbbox((0, 0), temp_text, font=temp_font)
    tx2 = inner_left + (inner_w - (bbox2[2] - bbox2[0])) // 2 - bbox2[0]
    ty2 = inner_top + int(inner_h * 0.68) - bbox2[1]
    draw.text((tx2, ty2), temp_text, font=temp_font, fill=DARK)

    return img


def trim(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    return image.crop(bbox) if bbox else image


def render_icon(size: int) -> Image.Image:
    return draw_clock(RENDER).resize((size, size), Image.Resampling.LANCZOS)


def render_logo(height: int, dark: bool) -> Image.Image:
    h = RENDER
    canvas = Image.new("RGBA", (h * 4, h), TRANSPARENT)
    canvas.alpha_composite(draw_clock(h))

    primary, secondary = TEXT_DARK if dark else TEXT_LIGHT
    top_font = ImageFont.truetype(FONT_BOLD, round(0.30 * h))
    bottom_font = ImageFont.truetype(FONT_REGULAR, round(0.21 * h))
    draw = ImageDraw.Draw(canvas)

    x = h + 0.16 * h
    top_bbox = draw.textbbox((0, 0), "LYWSD02", font=top_font)
    bottom_bbox = draw.textbbox((0, 0), "Clock", font=bottom_font)
    gap = 0.06 * h
    block = (top_bbox[3] - top_bbox[1]) + gap + (bottom_bbox[3] - bottom_bbox[1])
    y = (h - block) / 2

    draw.text((x - top_bbox[0], y - top_bbox[1]), "LYWSD02", font=top_font, fill=primary)
    y += (top_bbox[3] - top_bbox[1]) + gap
    draw.text(
        (x - bottom_bbox[0], y - bottom_bbox[1]),
        "Clock",
        font=bottom_font,
        fill=secondary,
    )

    logo = trim(canvas)
    width = round(logo.width * height / logo.height)
    return logo.resize((width, height), Image.Resampling.LANCZOS)


def save(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)
    # The brands guidelines ask for optimised, interlaced PNGs.
    subprocess.run(
        [
            "magick",
            str(path),
            "-strip",
            "-interlace",
            "PNG",
            "-define",
            "png:compression-level=9",
            "-define",
            "png:compression-filter=5",
            str(path),
        ],
        check=True,
    )


def main() -> None:
    images = {
        "icon.png": render_icon(256),
        "icon@2x.png": render_icon(512),
        "logo.png": render_logo(160, dark=False),
        "logo@2x.png": render_logo(320, dark=False),
        "dark_logo.png": render_logo(160, dark=True),
        "dark_logo@2x.png": render_logo(320, dark=True),
    }
    print("Generated:")
    for name, image in images.items():
        save(image, OUT / name)
        print(f"  {OUT / name}  {image.width}x{image.height}")


if __name__ == "__main__":
    main()
