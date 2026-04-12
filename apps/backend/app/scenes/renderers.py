"""Scene frame renderers — v3 (PropertySimple-inspired infographic style).

Design philosophy — modelled after PropertySimple's social video output:
  • Photo scenes: full-bleed cropped photo, no overlay baked in (hero gets
    a separate FFmpeg text-reveal overlay).
  • Stats overlay: vibrant purple→cyan gradient tint on the PHOTO itself
    with large icon-style stat callouts (sqft, beds, baths) — NOT a
    separate blurred-background card.
  • Description / features: large bold text directly over a lightly
    dimmed photo with a semi-transparent gradient strip.
  • Schools: clean white background infographic, gradient-bordered cards,
    distances in miles — professional, readable.
  • Map: white background, circular map crop, city/county header with
    location pin, price pin on map.
  • CTA: purple→cyan gradient background, large bold "Thinking of buying
    or selling?" text with agent CTA.
  • Outro: white background, circular headshot, name, license, brokerage,
    phone in gradient pill, email.

Typography: Poppins Bold for headlines, Poppins Medium/Regular for body.
Colour identity: consistent purple (#9333EA) → cyan (#06B6D4) gradient.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import Scene, SceneType

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920

# Brand gradient colours (PropertySimple-style purple → cyan)
GRAD_PURPLE = (147, 51, 234)   # #9333EA
GRAD_CYAN = (6, 182, 212)      # #06B6D4
DARK_TEXT = (30, 30, 30)
MID_TEXT = (80, 80, 80)
LIGHT_TEXT = (140, 140, 140)

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

# ---------------------------------------------------------------------------
# Font helper — Poppins first, DejaVu/Liberation fallback
# ---------------------------------------------------------------------------

_FONT_CACHE: Dict[Tuple[int, str], ImageFont.ImageFont] = {}

_FONT_PATHS: Dict[str, list] = {
    "bold": [
        str(ASSETS_DIR / "Poppins-Bold.ttf"),
        "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "medium": [
        str(ASSETS_DIR / "Poppins-Medium.ttf"),
        "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "regular": [
        str(ASSETS_DIR / "Poppins-Regular.ttf"),
        "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
}


def _font(size: int, weight: str = "bold") -> ImageFont.ImageFont:
    key = (size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for path in _FONT_PATHS.get(weight, _FONT_PATHS["bold"]):
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 99,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _text_h(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def _center_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, w: int = CANVAS_W) -> int:
    return (w - _text_w(draw, text, font)) // 2


# ---------------------------------------------------------------------------
# Gradient helpers
# ---------------------------------------------------------------------------

def _gradient_bar(w: int, h: int, left_color: Tuple[int, ...] = GRAD_PURPLE,
                  right_color: Tuple[int, ...] = GRAD_CYAN, alpha: int = 255) -> Image.Image:
    """Horizontal gradient bar."""
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w):
        t = x / max(1, w - 1)
        r = int(left_color[0] * (1 - t) + right_color[0] * t)
        g = int(left_color[1] * (1 - t) + right_color[1] * t)
        b = int(left_color[2] * (1 - t) + right_color[2] * t)
        ImageDraw.Draw(bar).line([(x, 0), (x, h - 1)], fill=(r, g, b, alpha))
    return bar


def _gradient_bg(w: int = CANVAS_W, h: int = CANVAS_H) -> Image.Image:
    """Full-canvas diagonal gradient purple→cyan."""
    canvas = Image.new("RGBA", (w, h), (*GRAD_PURPLE, 255))
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(GRAD_PURPLE[0] * (1 - t) + GRAD_CYAN[0] * t)
        g = int(GRAD_PURPLE[1] * (1 - t) + GRAD_CYAN[1] * t)
        b = int(GRAD_PURPLE[2] * (1 - t) + GRAD_CYAN[2] * t)
        ImageDraw.Draw(canvas).line([(0, y), (w, y)], fill=(r, g, b, 255))
    return canvas


def _gradient_tint_on_photo(photo: Image.Image, w: int = CANVAS_W, h: int = CANVAS_H,
                            opacity: int = 160) -> Image.Image:
    """Purple→cyan gradient tint overlaid on a photo (for stats scene)."""
    base = photo.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
    grad = _gradient_bg(w, h)
    # Set gradient alpha
    alpha = grad.split()[3] if grad.mode == "RGBA" else Image.new("L", (w, h), 255)
    grad.putalpha(Image.new("L", (w, h), opacity))
    base.alpha_composite(grad)
    return base


def _circular_crop(img: Image.Image, diameter: int) -> Image.Image:
    """Crop an image into a circle."""
    img = img.copy().convert("RGBA").resize((diameter, diameter), Image.Resampling.LANCZOS)
    mask = Image.new("L", (diameter, diameter), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    img.putalpha(mask)
    return img


# ---------------------------------------------------------------------------
# Gradient-bordered card for schools
# ---------------------------------------------------------------------------

def _gradient_bordered_card(w: int, h: int, border_width: int = 3, radius: int = 16) -> Image.Image:
    """White card with purple→cyan gradient border."""
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    # Gradient border (draw slightly larger rounded rect, then white inside)
    # Use gradient bar as border color reference
    grad = _gradient_bar(w, h)
    # Outer border
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius,
                           fill=(160, 80, 220, 255), outline=None)
    # Inner white fill
    draw.rounded_rectangle(
        (border_width, border_width, w - 1 - border_width, h - 1 - border_width),
        radius=max(1, radius - border_width),
        fill=(255, 255, 255, 255),
    )
    return card


# ---------------------------------------------------------------------------
# Icon drawing helpers (simple geometric icons)
# ---------------------------------------------------------------------------

def _draw_icon_sqft(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                    fill=(255, 255, 255, 255)):
    """Simple camera/sqft icon."""
    s = size // 2
    # Box
    draw.rounded_rectangle((cx - s, cy - s + 4, cx + s, cy + s - 4), radius=6,
                           outline=fill, width=3)
    # Lens circle
    draw.ellipse((cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2),
                 outline=fill, width=2)


def _draw_icon_bed(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                   fill=(255, 255, 255, 255)):
    """Simple bed icon."""
    s = size // 2
    # Bed frame
    draw.rounded_rectangle((cx - s, cy - 2, cx + s, cy + s - 6), radius=4,
                           outline=fill, width=3)
    # Headboard
    draw.line([(cx - s, cy - s + 6), (cx - s, cy + s - 6)], fill=fill, width=3)
    # Pillow
    draw.rounded_rectangle((cx - s + 6, cy - s + 10, cx - 2, cy - 4), radius=3,
                           fill=fill)


def _draw_icon_bath(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                    fill=(255, 255, 255, 255)):
    """Simple bathtub icon."""
    s = size // 2
    # Tub body
    draw.arc((cx - s, cy - 4, cx + s, cy + s), 0, 180, fill=fill, width=3)
    # Tub rim
    draw.line([(cx - s - 2, cy), (cx + s + 2, cy)], fill=fill, width=3)
    # Faucet
    draw.line([(cx - s + 4, cy - s + 2), (cx - s + 4, cy)], fill=fill, width=3)


def _draw_icon_tree(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                    fill=(255, 255, 255, 255)):
    """Simple tree/lot icon."""
    s = size // 2
    # Tree trunk
    draw.line([(cx, cy + 2), (cx, cy + s)], fill=fill, width=3)
    # Tree crown (triangle)
    draw.polygon([(cx, cy - s + 2), (cx - s + 4, cy + 4), (cx + s - 4, cy + 4)],
                 outline=fill, fill=None)
    draw.polygon([(cx, cy - s + 12), (cx - s + 10, cy + 2), (cx + s - 10, cy + 2)],
                 outline=fill, fill=None)


def _draw_icon_house(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                     fill=(255, 255, 255, 255)):
    """Simple house icon for description/CTA scenes."""
    s = size // 2
    # Roof
    draw.polygon([(cx, cy - s), (cx - s, cy - 2), (cx + s, cy - 2)],
                 outline=fill, width=3)
    # Body
    draw.rectangle((cx - s + 6, cy - 2, cx + s - 6, cy + s), outline=fill, width=3)
    # Door
    draw.rectangle((cx - 5, cy + 6, cx + 5, cy + s), outline=fill, width=2)


def _draw_icon_school(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                      fill: Tuple[int, ...] = DARK_TEXT):
    """Simple school/book icon."""
    s = size // 2
    # Open book shape
    draw.arc((cx - s, cy - s // 2, cx, cy + s // 2), 180, 360, fill=fill, width=3)
    draw.arc((cx, cy - s // 2, cx + s, cy + s // 2), 180, 360, fill=fill, width=3)
    draw.line([(cx, cy - s // 2), (cx, cy + s // 2 + 2)], fill=fill, width=2)


def _draw_icon_pin(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 48,
                   fill: Tuple[int, ...] = DARK_TEXT):
    """Location pin icon."""
    s = size // 2
    # Pin body (circle + triangle point)
    draw.ellipse((cx - s // 2, cy - s, cx + s // 2, cy), outline=fill, width=3)
    draw.polygon([(cx - s // 3, cy - 2), (cx + s // 3, cy - 2), (cx, cy + s // 2)],
                 fill=fill)
    draw.ellipse((cx - s // 5, cy - s // 2 - s // 5, cx + s // 5, cy - s // 2 + s // 5),
                 fill=(255, 255, 255, 255) if fill == DARK_TEXT else fill)


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_RENDERER_TABLE: Dict[SceneType, Callable[[Scene], Image.Image]] = {}


def _register(scene_type: SceneType):
    def decorator(fn: Callable[[Scene], Image.Image]):
        _RENDERER_TABLE[scene_type] = fn
        return fn
    return decorator


def render_scene_frame(scene: Scene) -> Image.Image:
    renderer = _RENDERER_TABLE.get(scene.scene_type)
    if renderer is None:
        raise ValueError(f"No renderer for scene type: {scene.scene_type}")
    frame = renderer(scene)
    scene.rendered_frame = frame
    return frame


# ============================================================================
# PHOTO SCENES  (return cropped photo — no overlay baked in)
# ============================================================================

@_register(SceneType.HERO_PHOTO)
def _render_hero_photo(scene: Scene) -> Image.Image:
    return scene.data["photo_image"].convert("RGB")


@_register(SceneType.INTERIOR_PHOTO)
def _render_interior_photo(scene: Scene) -> Image.Image:
    return scene.data["photo_image"].convert("RGB")


# ============================================================================
# STATS OVERLAY — gradient tint on photo with animated-style stat callouts
# ============================================================================

@_register(SceneType.STATS_CARD)
def _render_stats_card(scene: Scene) -> Image.Image:
    """Stats overlaid on gradient-tinted photo — PS style.

    Shows sqft, bedrooms, bathrooms as large icon+text rows over
    a purple→cyan gradient-tinted listing photo.
    """
    w, h = CANVAS_W, CANVAS_H
    bg = scene.data.get("bg_image")
    if bg is not None:
        canvas = _gradient_tint_on_photo(bg, w, h, opacity=170)
    else:
        canvas = _gradient_bg(w, h)
    draw = ImageDraw.Draw(canvas)

    # Large stat font
    stat_value_font = _font(72, "bold")
    stat_label_font = _font(48, "bold")

    # Build stat rows: icon_drawer, value, label
    rows: List[Tuple[Any, str, str]] = []
    if scene.data.get("sqft"):
        rows.append((_draw_icon_sqft, str(scene.data["sqft"]), "sqft"))
    if scene.data.get("beds"):
        rows.append((_draw_icon_bed, str(scene.data["beds"]), "bedrooms"))
    if scene.data.get("baths"):
        rows.append((_draw_icon_bath, str(scene.data["baths"]), "bathrooms"))

    # Center the stats vertically
    row_height = 160
    total_h = len(rows) * row_height
    start_y = (h - total_h) // 2

    for i, (icon_fn, value, label) in enumerate(rows):
        cy = start_y + i * row_height + row_height // 2
        x_icon = 120

        # Draw icon
        icon_fn(draw, x_icon, cy, size=56, fill=(255, 255, 255, 240))

        # Value + label as single line: "2,189 sqft"
        combined = f"{value} {label}"
        text_x = x_icon + 60
        draw.text((text_x, cy - 30), combined, fill=(255, 255, 255, 255),
                  font=stat_value_font)

        # Draw a white pill/highlight behind the last stat for emphasis
        if i == len(rows) - 1 and len(rows) > 1:
            tw = _text_w(draw, combined, stat_value_font)
            pill_pad = 16
            pill = Image.new("RGBA", (tw + pill_pad * 2 + 60, 80), (0, 0, 0, 0))
            pill_draw = ImageDraw.Draw(pill)
            pill_draw.rounded_rectangle((0, 0, pill.width - 1, pill.height - 1),
                                        radius=12, fill=(255, 255, 255, 220))
            canvas.alpha_composite(pill, (text_x - pill_pad - 60, cy - 36))
            # Redraw icon and text in dark on the pill
            draw = ImageDraw.Draw(canvas)
            icon_fn(draw, x_icon, cy, size=56, fill=(*GRAD_PURPLE, 255))
            draw.text((text_x, cy - 30), combined,
                      fill=(*GRAD_PURPLE, 255), font=stat_value_font)

    return canvas.convert("RGB")


# ============================================================================
# DESCRIPTION — large bold text over dimmed photo
# ============================================================================

@_register(SceneType.DESCRIPTION_CARD)
def _render_description_card(scene: Scene) -> Image.Image:
    """Property description as large bold text over a dimmed photo with house icon."""
    w, h = CANVAS_W, CANVAS_H
    bg = scene.data.get("bg_image")
    if bg is not None:
        canvas = bg.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        # Darken bottom half for text
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dark_draw = ImageDraw.Draw(dark)
        for y in range(h // 3, h):
            t = (y - h // 3) / (h * 2 // 3)
            alpha = int(200 * t)
            dark_draw.line([(0, y), (w, y)], fill=(0, 0, 0, min(alpha, 200)))
        canvas.alpha_composite(dark)
    else:
        canvas = Image.new("RGBA", (w, h), (20, 20, 30, 255))
    draw = ImageDraw.Draw(canvas)

    # House icon top-left
    _draw_icon_house(draw, 100, h // 2 - 40, size=64, fill=(255, 255, 255, 230))

    # Description text — large, bold, bottom half
    desc_font = _font(56, "bold")
    description = scene.data.get("description", "")

    # Build a short punchy summary from the description
    # Take first ~80 chars or to the first period
    sqft = scene.data.get("sqft", "")
    lot_size = scene.data.get("lot_size", "")
    address = scene.data.get("address", "")
    city = scene.data.get("city", "")

    # Create PS-style description: "This {sqft} sqft property with a {feature} is now on the"
    short_desc = description[:200] if description else ""
    # Wrap for large bold display
    margin = 80
    lines = _wrap(draw, short_desc, desc_font, w - margin * 2, max_lines=6)
    y = h // 2 + 20
    for line in lines:
        if y > h - 120:
            break
        draw.text((margin, y), line, fill=(255, 255, 255, 255), font=desc_font,
                  stroke_width=2, stroke_fill=(0, 0, 0, 120))
        y += 76

    return canvas.convert("RGB")


# ============================================================================
# FEATURES — stat callout strips over photos (acres, year built, etc.)
# ============================================================================

@_register(SceneType.FEATURES_CARD)
def _render_features_card(scene: Scene) -> Image.Image:
    """Individual stat callout on dimmed photo — PS style bottom bar."""
    w, h = CANVAS_W, CANVAS_H
    bg = scene.data.get("bg_image")
    if bg is not None:
        canvas = bg.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        # Subtle darken at bottom for text
        dark = Image.new("RGBA", (w, h // 3), (0, 0, 0, 140))
        canvas.alpha_composite(dark, (0, h - h // 3))
    else:
        canvas = Image.new("RGBA", (w, h), (20, 20, 30, 255))
    draw = ImageDraw.Draw(canvas)

    # Show lot size and year built as bottom-bar callouts (PS style)
    label_font = _font(52, "bold")
    value_font = _font(72, "bold")

    lot_size = scene.data.get("lot_size", "")
    year_built = scene.data.get("year_built", "")
    garage = scene.data.get("garage", "")

    # Build feature pairs
    features_display: List[Tuple[str, str, Any]] = []
    if lot_size:
        features_display.append(("acres", str(lot_size), _draw_icon_tree))
    if year_built:
        features_display.append(("built", str(year_built), _draw_icon_house))
    if garage:
        features_display.append(("garage", str(garage), _draw_icon_house))

    # Display as bottom bar with icon
    if features_display:
        label, value, icon_fn = features_display[0]  # Show primary feature
        bar_y = h - 220
        # Icon
        icon_fn(draw, 100, bar_y + 40, size=56, fill=(255, 255, 255, 230))
        # Label
        draw.text((170, bar_y), label, fill=(255, 255, 255, 255), font=label_font,
                  stroke_width=2, stroke_fill=(0, 0, 0, 120))
        # Value on right
        vw = _text_w(draw, value, value_font)
        draw.text((w - 100 - vw, bar_y - 10), value, fill=(255, 255, 255, 255),
                  font=value_font, stroke_width=2, stroke_fill=(0, 0, 0, 120))

    return canvas.convert("RGB")


# ============================================================================
# SCHOOLS — clean white infographic with gradient-bordered cards
# ============================================================================

@_register(SceneType.SCHOOLS_CARD)
def _render_schools_card(scene: Scene) -> Image.Image:
    """Nearby schools on white background — PS style infographic."""
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    county = scene.data.get("county", "")

    # Header
    header_font = _font(72, "bold")
    sub_font = _font(36, "bold")
    _draw_icon_school(draw, 100, 340, size=72, fill=DARK_TEXT)
    draw.text((160, 300), "Nearby Schools", fill=DARK_TEXT, font=header_font)
    if county:
        draw.text((160, 390), county.upper(), fill=LIGHT_TEXT, font=sub_font)

    # "MILES" header
    miles_font = _font(28, "medium")
    miles_x = w - 120
    draw.text((miles_x - 20, 460), "MILES", fill=LIGHT_TEXT, font=miles_font)

    # Divider line
    draw.line([(80, 500), (w - 80, 500)], fill=(220, 220, 220, 255), width=2)

    # School cards
    schools = scene.data.get("schools", [])
    name_font = _font(38, "medium")
    dist_font = _font(52, "bold")
    school_icon_font = _font(28, "regular")

    card_y = 540
    card_h = 120
    card_gap = 24

    for i, school in enumerate(schools[:5]):
        if card_y + card_h > h - 200:
            break

        # Gradient-bordered card
        card_w = w - 120
        card = _gradient_bordered_card(card_w, card_h, border_width=3, radius=16)
        canvas.alpha_composite(card, (60, card_y))
        draw = ImageDraw.Draw(canvas)  # refresh draw after composite

        # School icon (small building)
        icon_x = 100
        icon_cy = card_y + card_h // 2
        _draw_icon_school(draw, icon_x, icon_cy, size=36, fill=MID_TEXT)

        # School name
        name = school.get("name", "School")
        name_lines = _wrap(draw, name, name_font, card_w - 280, max_lines=1)
        if name_lines:
            draw.text((140, card_y + card_h // 2 - 18), name_lines[0],
                      fill=DARK_TEXT, font=name_font)

        # Distance (right side, large, gradient-colored)
        distance = school.get("distance", "")
        if distance:
            dist_str = str(distance)
            dw = _text_w(draw, dist_str, dist_font)
            # Use gradient purple color for distance
            draw.text((w - 120 - dw, card_y + card_h // 2 - 24), dist_str,
                      fill=GRAD_PURPLE, font=dist_font)

        card_y += card_h + card_gap

    return canvas.convert("RGB")


# ============================================================================
# MAP — white bg, circular map crop, city header, price pin
# ============================================================================

@_register(SceneType.MAP_CTA)
def _render_map_cta(scene: Scene) -> Image.Image:
    """Map infographic — PS style with circular map crop on white."""
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    city = scene.data.get("city", "")
    county = scene.data.get("county", "")
    price = scene.data.get("price", "")
    map_img = scene.data.get("map_image")

    # City header with location pin
    header_font = _font(72, "bold")
    sub_font = _font(36, "bold")

    _draw_icon_pin(draw, 100, 280, size=64, fill=DARK_TEXT)
    city_display = city if city else scene.data.get("address", "").split(",")[0] if scene.data.get("address") else ""
    draw.text((150, 240), city_display, fill=DARK_TEXT, font=header_font)
    if county:
        draw.text((150, 330), county.upper(), fill=LIGHT_TEXT, font=sub_font)

    # Circular map crop
    map_diameter = 700
    map_cx = w // 2
    map_cy = h // 2 + 120

    if map_img is not None:
        circular_map = _circular_crop(map_img, map_diameter)
        canvas.alpha_composite(circular_map,
                               (map_cx - map_diameter // 2, map_cy - map_diameter // 2))
        draw = ImageDraw.Draw(canvas)

        # Price pin on map center
        if price:
            # Compact price (e.g. "$405K" or "$1.2M")
            price_short = _compact_price(price)
            pin_font = _font(36, "bold")
            pw = _text_w(draw, price_short, pin_font)

            # Pin background
            pin_w = pw + 32
            pin_h = 52
            pin_x = map_cx - pin_w // 2
            pin_y = map_cy - pin_h // 2

            # Draw pin shape (rounded rect + triangle)
            pin_layer = Image.new("RGBA", (pin_w, pin_h + 16), (0, 0, 0, 0))
            pin_draw = ImageDraw.Draw(pin_layer)
            pin_draw.rounded_rectangle((0, 0, pin_w - 1, pin_h - 1), radius=10,
                                       fill=(*GRAD_PURPLE, 230))
            # Triangle pointer
            tri_cx = pin_w // 2
            pin_draw.polygon([(tri_cx - 10, pin_h - 2), (tri_cx + 10, pin_h - 2),
                              (tri_cx, pin_h + 14)], fill=(*GRAD_PURPLE, 230))
            canvas.alpha_composite(pin_layer, (pin_x, pin_y))
            draw = ImageDraw.Draw(canvas)

            draw.text((pin_x + 16, pin_y + 8), price_short,
                      fill=(255, 255, 255, 255), font=pin_font)
    else:
        # No map — draw a subtle circle placeholder
        draw.ellipse((map_cx - map_diameter // 2, map_cy - map_diameter // 2,
                      map_cx + map_diameter // 2, map_cy + map_diameter // 2),
                     fill=(245, 245, 245, 255), outline=(220, 220, 220, 255), width=2)
        # City name centered
        if city_display:
            cw = _text_w(draw, city_display, _font(48, "bold"))
            draw.text((map_cx - cw // 2, map_cy - 20), city_display,
                      fill=LIGHT_TEXT, font=_font(48, "bold"))

    return canvas.convert("RGB")


# ============================================================================
# CTA — gradient background with bold text
# ============================================================================

@_register(SceneType.CTA_CARD)
def _render_cta_card(scene: Scene) -> Image.Image:
    """Call-to-action with gradient background — PS style."""
    w, h = CANVAS_W, CANVAS_H

    # Gradient background with map underneath
    map_img = scene.data.get("map_image")
    if map_img is not None:
        canvas = map_img.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        # Gradient overlay
        grad = _gradient_bg(w, h)
        grad.putalpha(Image.new("L", (w, h), 180))
        canvas.alpha_composite(grad)
    else:
        canvas = _gradient_bg(w, h)
    draw = ImageDraw.Draw(canvas)

    county = scene.data.get("county", "")
    agent_name = scene.data.get("agent_name", "")
    city = scene.data.get("city", "")
    location = county if county else city

    # House icon
    _draw_icon_house(draw, 120, h // 2 - 200, size=80, fill=(255, 255, 255, 230))

    # Bold CTA text
    cta_font = _font(72, "bold")
    margin = 80

    cta_text = f"Thinking of buying or selling in {location}?" if location else "Thinking of buying or selling?"
    lines = _wrap(draw, cta_text, cta_font, w - margin * 2, max_lines=5)

    y = h // 2 - 160
    for line in lines:
        draw.text((margin, y), line, fill=(255, 255, 255, 255), font=cta_font)
        y += 90

    # Agent CTA pill
    if agent_name:
        first_name = agent_name.split()[0] if agent_name else ""
        call_text = f"Call {first_name}!"
        call_font = _font(56, "bold")
        tw = _text_w(draw, call_text, call_font)
        pill_w = tw + 48
        pill_h = 76
        pill_x = margin
        pill_y = y + 20
        draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
                               radius=pill_h // 2, fill=(255, 255, 255, 255))
        draw.text((pill_x + 24, pill_y + 10), call_text,
                  fill=DARK_TEXT, font=call_font)

    return canvas.convert("RGB")


# ============================================================================
# OUTRO — white bg, circular headshot, gradient phone pill — PS style
# ============================================================================

@_register(SceneType.OUTRO)
def _render_outro(scene: Scene) -> Image.Image:
    """Clean white agent contact card — PS style."""
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    branding = scene.data.get("branding", {})
    branding_assets = scene.data.get("branding_assets", {})

    name_font = _font(72, "bold")
    detail_font = _font(36, "regular")
    phone_font = _font(52, "bold")
    email_font = _font(36, "regular")

    # Agent photo — circular crop
    agent_photo = branding_assets.get("agent_photo") if branding_assets else None
    photo_diameter = 240
    photo_y = 480

    if agent_photo is not None:
        circular = _circular_crop(agent_photo, photo_diameter)
        canvas.alpha_composite(circular, ((w - photo_diameter) // 2, photo_y))
        draw = ImageDraw.Draw(canvas)

    # Agent name
    agent_name = (branding.get("agent_name") or "").strip()
    name_y = photo_y + photo_diameter + 60
    if agent_name:
        nw = _text_w(draw, agent_name, name_font)
        draw.text(((w - nw) // 2, name_y), agent_name, fill=DARK_TEXT, font=name_font)

    # License and brokerage
    info_y = name_y + 100
    license_num = (branding.get("license_number") or "").strip()
    broker_name = (branding.get("broker_name") or "").strip()

    if license_num:
        lic_text = f"License: {license_num}"
        lw = _text_w(draw, lic_text, detail_font)
        draw.text(((w - lw) // 2, info_y), lic_text, fill=MID_TEXT, font=detail_font)
        info_y += 52

    if broker_name:
        bw = _text_w(draw, broker_name, detail_font)
        draw.text(((w - bw) // 2, info_y), broker_name, fill=MID_TEXT, font=detail_font)
        info_y += 52

    # Phone number in gradient pill
    agent_phone = (branding.get("agent_phone") or "").strip()
    if agent_phone:
        phone_display = agent_phone
        pill_y = info_y + 50
        tw = _text_w(draw, phone_display, phone_font)
        pill_w = tw + 100
        pill_h = 80
        pill_x = (w - pill_w) // 2

        # Gradient pill
        pill = _gradient_bar(pill_w, pill_h)
        pill_mask = Image.new("L", (pill_w, pill_h), 0)
        ImageDraw.Draw(pill_mask).rounded_rectangle(
            (0, 0, pill_w - 1, pill_h - 1), radius=pill_h // 2, fill=255)
        pill.putalpha(pill_mask)
        canvas.alpha_composite(pill, (pill_x, pill_y))
        draw = ImageDraw.Draw(canvas)

        # Phone icon (simple circle with handset)
        icon_x = pill_x + 36
        icon_cy = pill_y + pill_h // 2
        draw.ellipse((icon_x - 12, icon_cy - 12, icon_x + 12, icon_cy + 12),
                     fill=(255, 255, 255, 255))

        draw.text((pill_x + 68, pill_y + 12), phone_display,
                  fill=(255, 255, 255, 255), font=phone_font)
        info_y = pill_y + pill_h

    # Email
    agent_email = (branding.get("agent_email") or "").strip()
    if agent_email:
        email_y = info_y + 30
        # Email icon (envelope)
        ew = _text_w(draw, agent_email, email_font)
        total_w = ew + 44
        ex = (w - total_w) // 2
        # Simple envelope
        draw.rectangle((ex, email_y + 6, ex + 28, email_y + 22), outline=DARK_TEXT, width=2)
        draw.line([(ex, email_y + 6), (ex + 14, email_y + 16), (ex + 28, email_y + 6)],
                  fill=DARK_TEXT, width=2)
        draw.text((ex + 44, email_y), agent_email, fill=DARK_TEXT, font=email_font)

    # Broker logo at top
    broker_logo = branding_assets.get("broker_logo") if branding_assets else None
    if broker_logo is not None:
        logo = broker_logo.copy().convert("RGBA")
        logo.thumbnail((280, 100), Image.Resampling.LANCZOS)
        canvas.alpha_composite(logo, ((w - logo.width) // 2, 200))

    return canvas.convert("RGB")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _compact_price(price: str) -> str:
    """Convert '$249,900' → '$250K', '$1,200,000' → '$1.2M'."""
    import re
    nums = re.sub(r'[^\d.]', '', price)
    try:
        val = float(nums)
        if val >= 1_000_000:
            m = val / 1_000_000
            return f"${m:.1f}M" if m != int(m) else f"${int(m)}M"
        elif val >= 1_000:
            k = round(val / 1_000)
            return f"${k}K"
        else:
            return price
    except (ValueError, TypeError):
        return price
