"""Scene frame renderers.

Each renderer takes a Scene and produces a full-resolution PIL Image
(1080x1920 for 9:16, or 1080x1080 for square).  Photo-type scenes
render just the cropped photo (the overlay is composited separately
by the pipeline).  Data-card scenes render complete frames with all
text and graphics baked in (has_own_overlay=True).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .models import Scene, SceneType

logger = logging.getLogger(__name__)

# Canvas defaults — overridden by format config when we add square support
CANVAS_W = 1080
CANVAS_H = 1920


# ---------------------------------------------------------------------------
# Font helper (mirrors main.py _load_font but self-contained)
# ---------------------------------------------------------------------------

_FONT_CACHE: Dict[Tuple[int, bool], ImageFont.ImageFont] = {}

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    # Try system fonts
    for path in _FONT_PATHS:
        if bold and "Bold" not in path:
            continue
        if not bold and "Bold" in path:
            continue
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue

    # Fallback — try any available font
    for path in _FONT_PATHS:
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue

    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 3,
) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
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


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_RENDERER_TABLE: Dict[SceneType, Callable[[Scene], Image.Image]] = {}


def _register(scene_type: SceneType):
    """Decorator to register a renderer for a scene type."""
    def decorator(fn: Callable[[Scene], Image.Image]):
        _RENDERER_TABLE[scene_type] = fn
        return fn
    return decorator


def render_scene_frame(scene: Scene) -> Image.Image:
    """Render a scene's frame using the appropriate type-specific renderer.

    After calling this, scene.rendered_frame is set.
    """
    renderer = _RENDERER_TABLE.get(scene.scene_type)
    if renderer is None:
        raise ValueError(f"No renderer registered for scene type: {scene.scene_type}")
    frame = renderer(scene)
    scene.rendered_frame = frame
    return frame


# ============================================================================
# PHOTO RENDERERS
# ============================================================================

@_register(SceneType.HERO_PHOTO)
def _render_hero_photo(scene: Scene) -> Image.Image:
    """Render the hero photo.

    For photo scenes, we just return the cropped photo image.
    The overlay (label chip, address, price) is composited separately
    by the pipeline, so this renderer only handles the photo itself.

    data keys:
        photo_image: PIL Image (already cropped to 9:16)
    """
    photo: Image.Image = scene.data["photo_image"]
    return photo.convert("RGB")


@_register(SceneType.INTERIOR_PHOTO)
def _render_interior_photo(scene: Scene) -> Image.Image:
    """Render a standard interior/listing photo.

    Same as hero — returns cropped photo; overlay applied by pipeline.

    data keys:
        photo_image: PIL Image (already cropped to 9:16)
    """
    photo: Image.Image = scene.data["photo_image"]
    return photo.convert("RGB")


# ============================================================================
# DATA CARD RENDERERS
# ============================================================================

@_register(SceneType.STATS_CARD)
def _render_stats_card(scene: Scene) -> Image.Image:
    """Render a property statistics infographic card.

    Shows beds, baths, sqft, lot size, year built in a clean grid layout
    over a dark background with the listing photo blurred behind.

    data keys:
        beds (str):       e.g. "4"
        baths (str):      e.g. "2.5"
        sqft (str):       e.g. "2,450"
        lot_size (str):   e.g. "0.25 acres"  (optional)
        year_built (str): e.g. "2018"  (optional)
        address (str):    Full address
        price (str):      e.g. "$349,900"
        template (str):   Color template key
        bg_image (Image): Optional blurred background photo
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (18, 20, 28, 255))

    # Optional blurred background
    bg = scene.data.get("bg_image")
    if bg is not None:
        bg_copy = bg.copy().convert("RGBA")
        bg_copy = bg_copy.resize((w, h), Image.Resampling.LANCZOS)
        from PIL import ImageFilter
        bg_copy = bg_copy.filter(ImageFilter.GaussianBlur(radius=25))
        # Darken
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 160))
        bg_copy.alpha_composite(dark)
        canvas = bg_copy

    draw = ImageDraw.Draw(canvas)
    template = scene.data.get("template", "new_listing")

    # Template colors
    from .constants import FRAME_TEMPLATES
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    # Title bar
    title_font = _load_font(52, bold=True)
    label_font = _load_font(36, bold=True)
    value_font = _load_font(64, bold=True)
    unit_font = _load_font(30, bold=False)

    # Draw label chip at top
    label = style.get("label", "NEW LISTING")
    chip_y = 180
    chip_bbox = draw.textbbox((0, 0), label, font=label_font)
    chip_w = (chip_bbox[2] - chip_bbox[0]) + 48
    chip_h = (chip_bbox[3] - chip_bbox[1]) + 24
    chip_x = (w - chip_w) // 2
    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
        radius=18,
        fill=(*primary, 230),
    )
    draw.text(
        (chip_x + 24, chip_y + 12),
        label,
        fill=(255, 255, 255, 255),
        font=label_font,
    )

    # Address below chip
    address = scene.data.get("address", "")
    addr_y = chip_y + chip_h + 40
    addr_lines = _wrap_text(draw, address, title_font, w - 140, max_lines=2)
    for line in addr_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        line_w = bbox[2] - bbox[0]
        draw.text(
            ((w - line_w) // 2, addr_y),
            line,
            fill=(255, 255, 255, 255),
            font=title_font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 200),
        )
        addr_y += 64

    # Stats grid — centered 2-column layout
    stats = []
    if scene.data.get("beds"):
        stats.append(("BEDS", scene.data["beds"]))
    if scene.data.get("baths"):
        stats.append(("BATHS", scene.data["baths"]))
    if scene.data.get("sqft"):
        stats.append(("SQ FT", scene.data["sqft"]))
    if scene.data.get("lot_size"):
        stats.append(("LOT", scene.data["lot_size"]))
    if scene.data.get("year_built"):
        stats.append(("BUILT", scene.data["year_built"]))
    if scene.data.get("garage"):
        stats.append(("GARAGE", scene.data["garage"]))

    if stats:
        grid_top = addr_y + 60
        cols = 2
        cell_w = (w - 160) // cols
        cell_h = 200
        grid_left = 80

        for idx, (unit_label, value) in enumerate(stats):
            col = idx % cols
            row = idx // cols
            cx = grid_left + col * cell_w + cell_w // 2
            cy = grid_top + row * cell_h

            # Card background
            card_pad = 20
            draw.rounded_rectangle(
                (cx - cell_w // 2 + card_pad, cy, cx + cell_w // 2 - card_pad, cy + cell_h - 20),
                radius=20,
                fill=(0, 0, 0, 140),
            )

            # Value
            val_bbox = draw.textbbox((0, 0), str(value), font=value_font)
            val_w = val_bbox[2] - val_bbox[0]
            draw.text(
                (cx - val_w // 2, cy + 30),
                str(value),
                fill=(255, 255, 255, 255),
                font=value_font,
                stroke_width=2,
                stroke_fill=(0, 0, 0, 180),
            )

            # Label
            lbl_bbox = draw.textbbox((0, 0), unit_label, font=unit_font)
            lbl_w = lbl_bbox[2] - lbl_bbox[0]
            draw.text(
                (cx - lbl_w // 2, cy + 110),
                unit_label,
                fill=(*primary, 255),
                font=unit_font,
            )

    # Price at bottom
    price = scene.data.get("price", "")
    if price:
        price_font = _load_font(72, bold=True)
        price_bbox = draw.textbbox((0, 0), price, font=price_font)
        price_w = price_bbox[2] - price_bbox[0]
        draw.text(
            ((w - price_w) // 2, h - 300),
            price,
            fill=(255, 255, 255, 255),
            font=price_font,
            stroke_width=3,
            stroke_fill=(0, 0, 0, 255),
        )

    return canvas.convert("RGB")


@_register(SceneType.DESCRIPTION_CARD)
def _render_description_card(scene: Scene) -> Image.Image:
    """Render an AI-generated property description card.

    data keys:
        description (str): The property description text
        address (str): Property address
        price (str): Price string
        template (str): Color template key
        bg_image (Image): Optional blurred background
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (18, 20, 28, 255))

    bg = scene.data.get("bg_image")
    if bg is not None:
        bg_copy = bg.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        from PIL import ImageFilter
        bg_copy = bg_copy.filter(ImageFilter.GaussianBlur(radius=30))
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 180))
        bg_copy.alpha_composite(dark)
        canvas = bg_copy

    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    # "About This Home" header
    header_font = _load_font(48, bold=True)
    body_font = _load_font(34, bold=False)

    header_y = 280
    header_text = "About This Home"
    hdr_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    hdr_w = hdr_bbox[2] - hdr_bbox[0]
    draw.text(
        ((w - hdr_w) // 2, header_y),
        header_text,
        fill=(*primary, 255),
        font=header_font,
    )

    # Accent line
    line_y = header_y + 70
    line_w = 120
    draw.rounded_rectangle(
        ((w - line_w) // 2, line_y, (w + line_w) // 2, line_y + 4),
        radius=2,
        fill=(*primary, 200),
    )

    # Description text block
    description = scene.data.get("description", "")
    text_top = line_y + 40
    margin = 80
    max_text_w = w - margin * 2

    # Word-wrap the description
    lines = _wrap_text(draw, description, body_font, max_text_w, max_lines=16)
    text_y = text_top
    line_spacing = 48
    for line in lines:
        if text_y + 40 > h - 350:
            break
        draw.text(
            (margin, text_y),
            line,
            fill=(240, 240, 240, 255),
            font=body_font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 120),
        )
        text_y += line_spacing

    # Price at bottom
    price = scene.data.get("price", "")
    if price:
        price_font = _load_font(72, bold=True)
        price_bbox = draw.textbbox((0, 0), price, font=price_font)
        price_w = price_bbox[2] - price_bbox[0]
        draw.text(
            ((w - price_w) // 2, h - 280),
            price,
            fill=(255, 255, 255, 255),
            font=price_font,
            stroke_width=3,
            stroke_fill=(0, 0, 0, 255),
        )

    return canvas.convert("RGB")


@_register(SceneType.FEATURES_CARD)
def _render_features_card(scene: Scene) -> Image.Image:
    """Render a key features / amenities card.

    data keys:
        features (list[str]): List of feature strings
        address (str): Property address
        template (str): Color template key
        bg_image (Image): Optional blurred background
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (18, 20, 28, 255))

    bg = scene.data.get("bg_image")
    if bg is not None:
        bg_copy = bg.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        from PIL import ImageFilter
        bg_copy = bg_copy.filter(ImageFilter.GaussianBlur(radius=28))
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 170))
        bg_copy.alpha_composite(dark)
        canvas = bg_copy

    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    header_font = _load_font(48, bold=True)
    feat_font = _load_font(36, bold=False)
    bullet_font = _load_font(36, bold=True)

    # Header
    header_y = 280
    header_text = "Key Features"
    hdr_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    hdr_w = hdr_bbox[2] - hdr_bbox[0]
    draw.text(((w - hdr_w) // 2, header_y), header_text, fill=(*primary, 255), font=header_font)

    # Features list
    features = scene.data.get("features", [])
    feat_y = header_y + 100
    margin = 100

    for feat in features[:10]:
        if feat_y > h - 350:
            break
        # Bullet dot
        draw.ellipse(
            (margin, feat_y + 12, margin + 16, feat_y + 28),
            fill=(*primary, 230),
        )
        # Feature text
        feat_lines = _wrap_text(draw, feat, feat_font, w - margin - 50 - margin, max_lines=2)
        for fl in feat_lines:
            draw.text(
                (margin + 36, feat_y),
                fl,
                fill=(240, 240, 240, 255),
                font=feat_font,
                stroke_width=1,
                stroke_fill=(0, 0, 0, 100),
            )
            feat_y += 50
        feat_y += 16

    return canvas.convert("RGB")


@_register(SceneType.SCHOOLS_CARD)
def _render_schools_card(scene: Scene) -> Image.Image:
    """Render a nearby schools infographic.

    data keys:
        schools (list[dict]): Each dict has name, rating, distance, grades
        address (str): Property address
        template (str): Color template key
        bg_image (Image): Optional blurred background
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (18, 20, 28, 255))

    bg = scene.data.get("bg_image")
    if bg is not None:
        bg_copy = bg.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        from PIL import ImageFilter
        bg_copy = bg_copy.filter(ImageFilter.GaussianBlur(radius=28))
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 170))
        bg_copy.alpha_composite(dark)
        canvas = bg_copy

    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    header_font = _load_font(48, bold=True)
    name_font = _load_font(34, bold=True)
    detail_font = _load_font(28, bold=False)
    rating_font = _load_font(42, bold=True)

    # Header
    header_y = 280
    header_text = "Nearby Schools"
    hdr_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    hdr_w = hdr_bbox[2] - hdr_bbox[0]
    draw.text(((w - hdr_w) // 2, header_y), header_text, fill=(*primary, 255), font=header_font)

    # School cards
    schools = scene.data.get("schools", [])
    card_y = header_y + 100
    margin = 70

    for school in schools[:5]:
        if card_y > h - 400:
            break

        card_h = 160
        draw.rounded_rectangle(
            (margin, card_y, w - margin, card_y + card_h),
            radius=18,
            fill=(0, 0, 0, 150),
        )

        # Rating circle
        rating = str(school.get("rating", "?"))
        circle_x = margin + 30
        circle_y = card_y + 25
        circle_r = 50
        # Color based on rating
        try:
            r_val = float(rating)
            if r_val >= 8:
                r_color = (34, 197, 94)
            elif r_val >= 6:
                r_color = (234, 179, 8)
            else:
                r_color = (239, 68, 68)
        except (ValueError, TypeError):
            r_color = (150, 150, 150)

        draw.ellipse(
            (circle_x, circle_y, circle_x + circle_r * 2, circle_y + circle_r * 2),
            fill=(*r_color, 230),
        )
        r_bbox = draw.textbbox((0, 0), rating, font=rating_font)
        r_w = r_bbox[2] - r_bbox[0]
        r_h = r_bbox[3] - r_bbox[1]
        draw.text(
            (circle_x + circle_r - r_w // 2, circle_y + circle_r - r_h // 2 - 4),
            rating,
            fill=(255, 255, 255, 255),
            font=rating_font,
        )

        # School name and details
        text_x = circle_x + circle_r * 2 + 24
        name = school.get("name", "School")
        name_lines = _wrap_text(draw, name, name_font, w - margin - text_x - 30, max_lines=1)
        if name_lines:
            draw.text(
                (text_x, card_y + 30),
                name_lines[0],
                fill=(255, 255, 255, 255),
                font=name_font,
            )

        details = []
        if school.get("grades"):
            details.append(f"Grades: {school['grades']}")
        if school.get("distance"):
            details.append(f"{school['distance']} mi")
        detail_text = "  |  ".join(details)
        if detail_text:
            draw.text(
                (text_x, card_y + 75),
                detail_text,
                fill=(200, 200, 200, 255),
                font=detail_font,
            )

        school_type = school.get("type", "")
        if school_type:
            draw.text(
                (text_x, card_y + 112),
                school_type,
                fill=(170, 170, 170, 255),
                font=detail_font,
            )

        card_y += card_h + 20

    return canvas.convert("RGB")


@_register(SceneType.MAP_CTA)
def _render_map_cta(scene: Scene) -> Image.Image:
    """Render a map image with call-to-action overlay.

    data keys:
        map_image (Image): Static map image (optional — will render placeholder if missing)
        address (str): Property address
        price (str): Price string
        cta_text (str): Call-to-action text (default: "Schedule a Showing")
        template (str): Color template key
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (30, 34, 42, 255))

    map_img = scene.data.get("map_image")
    if map_img is not None:
        map_copy = map_img.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        # Semi-transparent overlay to make text readable
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 100))
        map_copy.alpha_composite(dark)
        canvas = map_copy
    else:
        # Placeholder — dark gradient with grid pattern
        draw_bg = ImageDraw.Draw(canvas)
        grid_color = (50, 55, 65, 255)
        for x in range(0, w, 60):
            draw_bg.line([(x, 0), (x, h)], fill=grid_color, width=1)
        for y in range(0, h, 60):
            draw_bg.line([(0, y), (w, y)], fill=grid_color, width=1)

    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    # Location pin icon (simple circle + triangle)
    pin_cx = w // 2
    pin_cy = h // 2 - 200
    pin_r = 40
    draw.ellipse(
        (pin_cx - pin_r, pin_cy - pin_r, pin_cx + pin_r, pin_cy + pin_r),
        fill=(*primary, 240),
    )
    draw.polygon(
        [(pin_cx - 25, pin_cy + 30), (pin_cx + 25, pin_cy + 30), (pin_cx, pin_cy + 75)],
        fill=(*primary, 240),
    )
    # Inner dot
    draw.ellipse(
        (pin_cx - 14, pin_cy - 14, pin_cx + 14, pin_cy + 14),
        fill=(255, 255, 255, 230),
    )

    # Address
    addr_font = _load_font(44, bold=True)
    address = scene.data.get("address", "")
    addr_lines = _wrap_text(draw, address, addr_font, w - 120, max_lines=2)
    addr_y = pin_cy + 120
    for line in addr_lines:
        bbox = draw.textbbox((0, 0), line, font=addr_font)
        lw = bbox[2] - bbox[0]
        draw.text(
            ((w - lw) // 2, addr_y),
            line,
            fill=(255, 255, 255, 255),
            font=addr_font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 200),
        )
        addr_y += 56

    # CTA button
    cta_text = scene.data.get("cta_text", "Schedule a Showing")
    cta_font = _load_font(40, bold=True)
    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_w = (cta_bbox[2] - cta_bbox[0]) + 80
    cta_h = (cta_bbox[3] - cta_bbox[1]) + 40
    cta_x = (w - cta_w) // 2
    cta_y = h - 450

    draw.rounded_rectangle(
        (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h),
        radius=cta_h // 2,
        fill=(*primary, 240),
    )
    draw.text(
        (cta_x + 40, cta_y + 20),
        cta_text,
        fill=(255, 255, 255, 255),
        font=cta_font,
    )

    # Price
    price = scene.data.get("price", "")
    if price:
        price_font = _load_font(72, bold=True)
        price_bbox = draw.textbbox((0, 0), price, font=price_font)
        price_w = price_bbox[2] - price_bbox[0]
        draw.text(
            ((w - price_w) // 2, h - 300),
            price,
            fill=(255, 255, 255, 255),
            font=price_font,
            stroke_width=3,
            stroke_fill=(0, 0, 0, 255),
        )

    return canvas.convert("RGB")


@_register(SceneType.OUTRO)
def _render_outro(scene: Scene) -> Image.Image:
    """Render the outro / contact card.

    This delegates to the existing draw_outro_frame() in main.py
    so we don't duplicate that complex rendering logic.

    The import is lazy to avoid pulling in ffmpeg/supabase at module load.

    data keys:
        address (str)
        price (str)
        branding (dict)
        template (str)
        branding_assets (dict)
    """
    try:
        from ..main import draw_outro_frame as _draw_outro
        return _draw_outro(
            scene.data.get("address", ""),
            scene.data.get("price", ""),
            scene.data.get("branding", {}),
            template=scene.data.get("template", "new_listing"),
            branding_assets=scene.data.get("branding_assets"),
        )
    except ImportError:
        # Fallback when main.py can't be imported (e.g. missing ffmpeg in test)
        logger.warning("Cannot import draw_outro_frame from main — using fallback outro renderer")
        from .constants import FRAME_TEMPLATES
        w, h = CANVAS_W, CANVAS_H
        canvas = Image.new("RGB", (w, h), (14, 16, 20))
        draw = ImageDraw.Draw(canvas)
        template = scene.data.get("template", "new_listing")
        style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
        primary = style["primary"][:3]

        title_font = _load_font(52, bold=True)
        body_font = _load_font(38, bold=False)
        price_font = _load_font(72, bold=True)

        branding = scene.data.get("branding", {})
        address = scene.data.get("address", "")
        price = scene.data.get("price", "")

        draw.text((64, 300), "Contact Listing Agent", fill=(255, 255, 255), font=title_font)
        draw.rounded_rectangle((64, 420, 1016, 1100), radius=28, fill=(0, 0, 0, 200))

        y = 460
        agent_name = branding.get("agent_name", "Your Agent")
        draw.text((100, y), agent_name, fill=(255, 255, 255), font=body_font); y += 55
        if branding.get("agent_phone"):
            draw.text((100, y), f"Call/Text: {branding['agent_phone']}", fill=(220, 220, 220), font=body_font); y += 55
        if branding.get("broker_name"):
            draw.text((100, y), branding["broker_name"], fill=(200, 200, 200), font=body_font)

        draw.rounded_rectangle((64, 1200, 1016, 1700), radius=28, fill=(0, 0, 0, 200))
        addr_lines = _wrap_text(draw, address, body_font, 880, max_lines=2)
        ay = 1240
        for line in addr_lines:
            draw.text((100, ay), line, fill=(255, 255, 255), font=body_font); ay += 55
        draw.text((100, 1580), price, fill=(255, 255, 255), font=price_font)

        return canvas
