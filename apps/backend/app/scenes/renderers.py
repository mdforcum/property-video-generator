"""Scene frame renderers — v2 (glass panel style).

Each renderer takes a Scene and produces a full-resolution PIL Image
(1080x1920 for 9:16).  Photo-type scenes render just the cropped photo
(the hero overlay is composited separately by the pipeline with FFmpeg
fade-in/out).  Data-card scenes render complete frames with blurred
photo backgrounds and frosted-glass content panels.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .models import Scene, SceneType

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920


# ---------------------------------------------------------------------------
# Font helper
# ---------------------------------------------------------------------------

_FONT_CACHE: Dict[Tuple[int, bool], ImageFont.ImageFont] = {}

_FONT_PATHS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
_FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    paths = _FONT_PATHS_BOLD if bold else _FONT_PATHS_REGULAR
    for path in paths:
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue
    # Fallback
    for path in _FONT_PATHS_BOLD + _FONT_PATHS_REGULAR:
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
# Glass panel helper
# ---------------------------------------------------------------------------

def _make_glass_bg(
    bg_image: Optional[Image.Image],
    w: int = CANVAS_W,
    h: int = CANVAS_H,
    blur: int = 35,
    darken: int = 140,
) -> Image.Image:
    """Create a blurred, darkened background from a listing photo."""
    if bg_image is not None:
        bg = bg_image.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=blur))
        dark = Image.new("RGBA", (w, h), (0, 0, 0, darken))
        bg.alpha_composite(dark)
        return bg
    return Image.new("RGBA", (w, h), (18, 20, 28, 255))


def _draw_glass_panel(
    draw: ImageDraw.ImageDraw,
    canvas: Image.Image,
    x0: int, y0: int, x1: int, y1: int,
    radius: int = 28,
    fill_alpha: int = 45,
    border_alpha: int = 50,
) -> None:
    """Draw a frosted glass panel with subtle border via alpha compositing.

    PIL's ImageDraw doesn't alpha-blend on RGBA canvases — it replaces pixels.
    So we draw the panel on a separate transparent layer and composite it.
    """
    pw, ph = x1 - x0, y1 - y0
    panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle(
        (0, 0, pw - 1, ph - 1),
        radius=radius,
        fill=(255, 255, 255, fill_alpha),
        outline=(255, 255, 255, border_alpha),
        width=1,
    )
    canvas.alpha_composite(panel, (x0, y0))


def _center_text(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill=(255, 255, 255, 255),
    w: int = CANVAS_W,
    **kwargs,
) -> int:
    """Draw centered text, return y + line height."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((w - tw) // 2, y), text, fill=fill, font=font, **kwargs)
    return y + th + 8


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
        raise ValueError(f"No renderer registered for scene type: {scene.scene_type}")
    frame = renderer(scene)
    scene.rendered_frame = frame
    return frame


# ============================================================================
# PHOTO RENDERERS  (return cropped photo — no overlay baked in)
# ============================================================================

@_register(SceneType.HERO_PHOTO)
def _render_hero_photo(scene: Scene) -> Image.Image:
    photo: Image.Image = scene.data["photo_image"]
    return photo.convert("RGB")


@_register(SceneType.INTERIOR_PHOTO)
def _render_interior_photo(scene: Scene) -> Image.Image:
    photo: Image.Image = scene.data["photo_image"]
    return photo.convert("RGB")


# ============================================================================
# DATA CARD RENDERERS — glass panel style
# ============================================================================

@_register(SceneType.STATS_CARD)
def _render_stats_card(scene: Scene) -> Image.Image:
    """Property stats with frosted glass panel over blurred photo."""
    w, h = CANVAS_W, CANVAS_H
    canvas = _make_glass_bg(scene.data.get("bg_image"), w, h)
    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    # Fonts
    header_font = _load_font(44, bold=True)
    value_font = _load_font(64, bold=True)
    unit_font = _load_font(26, bold=False)
    price_font = _load_font(64, bold=True)
    addr_font = _load_font(34, bold=True)

    # Glass panel
    panel_x = 56
    panel_y = 320
    panel_w = w - panel_x * 2
    panel_bottom = h - 280
    _draw_glass_panel(draw, canvas, panel_x, panel_y, panel_x + panel_w, panel_bottom)

    # Header inside panel
    header_text = "Property Details"
    y = panel_y + 50
    y = _center_text(draw, y, header_text, header_font, fill=(255, 255, 255, 255))

    # Accent line
    line_w = 50
    draw.rounded_rectangle(
        ((w - line_w) // 2, y + 8, (w + line_w) // 2, y + 11),
        radius=2, fill=(*primary, 200),
    )
    y += 40

    # Address
    address = scene.data.get("address", "")
    addr_lines = _wrap_text(draw, address, addr_font, panel_w - 80, max_lines=2)
    for line in addr_lines:
        y = _center_text(draw, y, line, addr_font, fill=(220, 220, 220, 255))
    y += 30

    # Stats grid
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
        cols = 2
        cell_w = (panel_w - 40) // cols
        cell_h = 180
        grid_left = panel_x + 20

        for idx, (unit_label, value) in enumerate(stats):
            col = idx % cols
            row = idx // cols
            cx = grid_left + col * cell_w + cell_w // 2
            cy = y + row * cell_h

            # Stat cell background
            cell_pad = 12
            draw.rounded_rectangle(
                (cx - cell_w // 2 + cell_pad, cy + 8,
                 cx + cell_w // 2 - cell_pad, cy + cell_h - 12),
                radius=16,
                fill=(0, 0, 0, 70),
            )

            # Value
            val_bbox = draw.textbbox((0, 0), str(value), font=value_font)
            val_w = val_bbox[2] - val_bbox[0]
            draw.text(
                (cx - val_w // 2, cy + 28),
                str(value),
                fill=(255, 255, 255, 255),
                font=value_font,
            )

            # Unit label
            lbl_bbox = draw.textbbox((0, 0), unit_label, font=unit_font)
            lbl_w = lbl_bbox[2] - lbl_bbox[0]
            draw.text(
                (cx - lbl_w // 2, cy + 105),
                unit_label,
                fill=(*primary, 230),
                font=unit_font,
            )

    # Price at bottom of panel
    price = scene.data.get("price", "")
    if price:
        price_bbox = draw.textbbox((0, 0), price, font=price_font)
        price_w = price_bbox[2] - price_bbox[0]
        draw.text(
            ((w - price_w) // 2, panel_bottom - 100),
            price,
            fill=(255, 255, 255, 255),
            font=price_font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 80),
        )

    return canvas.convert("RGB")


@_register(SceneType.DESCRIPTION_CARD)
def _render_description_card(scene: Scene) -> Image.Image:
    """Property description with frosted glass panel."""
    w, h = CANVAS_W, CANVAS_H
    canvas = _make_glass_bg(scene.data.get("bg_image"), w, h, blur=40, darken=160)
    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    header_font = _load_font(42, bold=True)
    body_font = _load_font(32, bold=False)

    # Glass panel
    panel_x = 56
    panel_y = 340
    panel_bottom = h - 300
    _draw_glass_panel(draw, canvas, panel_x, panel_y, w - panel_x, panel_bottom)

    # Header
    y = panel_y + 50
    y = _center_text(draw, y, "About This Home", header_font)

    # Accent line
    line_w = 50
    draw.rounded_rectangle(
        ((w - line_w) // 2, y + 4, (w + line_w) // 2, y + 7),
        radius=2, fill=(*primary, 200),
    )
    y += 36

    # Description text
    description = scene.data.get("description", "")
    margin = panel_x + 36
    max_text_w = w - margin * 2
    lines = _wrap_text(draw, description, body_font, max_text_w, max_lines=18)
    line_spacing = 44

    for line in lines:
        if y + 40 > panel_bottom - 40:
            break
        draw.text(
            (margin, y),
            line,
            fill=(235, 235, 235, 255),
            font=body_font,
        )
        y += line_spacing

    return canvas.convert("RGB")


@_register(SceneType.FEATURES_CARD)
def _render_features_card(scene: Scene) -> Image.Image:
    """Key features with frosted glass panel."""
    w, h = CANVAS_W, CANVAS_H
    canvas = _make_glass_bg(scene.data.get("bg_image"), w, h, blur=32, darken=150)
    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    header_font = _load_font(42, bold=True)
    feat_font = _load_font(32, bold=False)

    # Glass panel
    panel_x = 56
    panel_y = 340
    panel_bottom = h - 300
    _draw_glass_panel(draw, canvas, panel_x, panel_y, w - panel_x, panel_bottom)

    # Header
    y = panel_y + 50
    y = _center_text(draw, y, "Key Features", header_font)

    # Accent line
    line_w = 50
    draw.rounded_rectangle(
        ((w - line_w) // 2, y + 4, (w + line_w) // 2, y + 7),
        radius=2, fill=(*primary, 200),
    )
    y += 40

    # Feature list
    features = scene.data.get("features", [])
    margin = panel_x + 40

    for feat in features[:10]:
        if y > panel_bottom - 60:
            break
        # Bullet dot
        dot_y = y + 12
        draw.ellipse(
            (margin, dot_y, margin + 10, dot_y + 10),
            fill=(*primary, 220),
        )
        # Feature text
        feat_lines = _wrap_text(draw, feat, feat_font, w - margin - 50 - panel_x, max_lines=2)
        for fl in feat_lines:
            draw.text(
                (margin + 26, y),
                fl,
                fill=(235, 235, 235, 255),
                font=feat_font,
            )
            y += 44
        y += 12

    return canvas.convert("RGB")


@_register(SceneType.SCHOOLS_CARD)
def _render_schools_card(scene: Scene) -> Image.Image:
    """Nearby schools with frosted glass cards."""
    w, h = CANVAS_W, CANVAS_H
    canvas = _make_glass_bg(scene.data.get("bg_image"), w, h, blur=32, darken=150)
    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    header_font = _load_font(42, bold=True)
    name_font = _load_font(30, bold=True)
    detail_font = _load_font(24, bold=False)
    rating_font = _load_font(36, bold=True)

    # Header area (no glass panel for header)
    y = 360
    y = _center_text(draw, y, "Nearby Schools", header_font)

    # Accent line
    line_w = 50
    draw.rounded_rectangle(
        ((w - line_w) // 2, y + 4, (w + line_w) // 2, y + 7),
        radius=2, fill=(*primary, 200),
    )
    y += 40

    # Individual glass cards for each school
    schools = scene.data.get("schools", [])
    margin = 56

    for school in schools[:5]:
        if y > h - 350:
            break

        card_h = 140
        _draw_glass_panel(draw, canvas, margin, y, w - margin, y + card_h, radius=18)

        # Rating circle
        rating = str(school.get("rating", "?"))
        circle_x = margin + 24
        circle_cy = y + card_h // 2
        circle_r = 38
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
            (circle_x, circle_cy - circle_r, circle_x + circle_r * 2, circle_cy + circle_r),
            fill=(*r_color, 220),
        )
        r_bbox = draw.textbbox((0, 0), rating, font=rating_font)
        r_w = r_bbox[2] - r_bbox[0]
        r_h = r_bbox[3] - r_bbox[1]
        draw.text(
            (circle_x + circle_r - r_w // 2, circle_cy - r_h // 2 - circle_r // 2),
            rating,
            fill=(255, 255, 255, 255),
            font=rating_font,
        )

        # School name and details
        text_x = circle_x + circle_r * 2 + 20
        name = school.get("name", "School")
        name_lines = _wrap_text(draw, name, name_font, w - margin - text_x - 20, max_lines=1)
        if name_lines:
            draw.text((text_x, y + 24), name_lines[0], fill=(255, 255, 255, 255), font=name_font)

        details = []
        if school.get("grades"):
            details.append(f"Grades: {school['grades']}")
        if school.get("distance"):
            details.append(f"{school['distance']} mi")
        detail_text = "  ·  ".join(details)
        if detail_text:
            draw.text((text_x, y + 62), detail_text, fill=(200, 200, 200, 255), font=detail_font)

        school_type = school.get("type", "")
        if school_type:
            draw.text((text_x, y + 92), school_type, fill=(170, 170, 170, 255), font=detail_font)

        y += card_h + 16

    return canvas.convert("RGB")


@_register(SceneType.MAP_CTA)
def _render_map_cta(scene: Scene) -> Image.Image:
    """Map with call-to-action — glass panel style."""
    w, h = CANVAS_W, CANVAS_H
    canvas = Image.new("RGBA", (w, h), (24, 28, 36, 255))

    map_img = scene.data.get("map_image")
    if map_img is not None:
        map_copy = map_img.copy().convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)
        dark = Image.new("RGBA", (w, h), (0, 0, 0, 80))
        map_copy.alpha_composite(dark)
        canvas = map_copy
    else:
        # Subtle grid placeholder
        draw_bg = ImageDraw.Draw(canvas)
        grid_color = (40, 44, 52, 255)
        for x in range(0, w, 80):
            draw_bg.line([(x, 0), (x, h)], fill=grid_color, width=1)
        for y_pos in range(0, h, 80):
            draw_bg.line([(0, y_pos), (w, y_pos)], fill=grid_color, width=1)

    draw = ImageDraw.Draw(canvas)

    from .constants import FRAME_TEMPLATES
    template = scene.data.get("template", "new_listing")
    style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
    primary = style["primary"][:3]

    # Glass panel in center
    panel_x = 80
    panel_y = h // 2 - 200
    panel_bottom = h // 2 + 260
    _draw_glass_panel(draw, canvas, panel_x, panel_y, w - panel_x, panel_bottom, fill_alpha=55)

    # Location pin
    pin_cx = w // 2
    pin_cy = panel_y + 70
    pin_r = 28
    draw.ellipse(
        (pin_cx - pin_r, pin_cy - pin_r, pin_cx + pin_r, pin_cy + pin_r),
        fill=(*primary, 230),
    )
    draw.polygon(
        [(pin_cx - 16, pin_cy + 22), (pin_cx + 16, pin_cy + 22), (pin_cx, pin_cy + 52)],
        fill=(*primary, 230),
    )
    draw.ellipse(
        (pin_cx - 10, pin_cy - 10, pin_cx + 10, pin_cy + 10),
        fill=(255, 255, 255, 220),
    )

    # Address
    addr_font = _load_font(36, bold=True)
    addr_small = _load_font(28, bold=False)
    address = scene.data.get("address", "")
    addr_lines = _wrap_text(draw, address, addr_font, w - 160, max_lines=2)
    addr_y = pin_cy + 70
    for line in addr_lines:
        addr_y = _center_text(draw, addr_y, line, addr_font)

    # CTA button
    cta_text = scene.data.get("cta_text", "Schedule a Showing")
    cta_font = _load_font(34, bold=True)
    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_w = (cta_bbox[2] - cta_bbox[0]) + 64
    cta_h = (cta_bbox[3] - cta_bbox[1]) + 32
    cta_x = (w - cta_w) // 2
    cta_y = panel_bottom - cta_h - 40
    draw.rounded_rectangle(
        (cta_x, cta_y, cta_x + cta_w, cta_y + cta_h),
        radius=cta_h // 2,
        fill=(*primary, 230),
    )
    draw.text(
        (cta_x + 32, cta_y + 16),
        cta_text,
        fill=(255, 255, 255, 255),
        font=cta_font,
    )

    # Price below panel
    price = scene.data.get("price", "")
    if price:
        price_font = _load_font(60, bold=True)
        price_bbox = draw.textbbox((0, 0), price, font=price_font)
        price_w = price_bbox[2] - price_bbox[0]
        draw.text(
            ((w - price_w) // 2, panel_bottom + 40),
            price,
            fill=(255, 255, 255, 255),
            font=price_font,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 140),
        )

    return canvas.convert("RGB")


@_register(SceneType.OUTRO)
def _render_outro(scene: Scene) -> Image.Image:
    """Outro / contact card — the only scene with agent branding.

    Delegates to draw_outro_frame() in main.py for full branding layout.
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
        logger.warning("Cannot import draw_outro_frame from main — using fallback")
        from .constants import FRAME_TEMPLATES
        w, h = CANVAS_W, CANVAS_H
        canvas = Image.new("RGB", (w, h), (14, 16, 20))
        draw = ImageDraw.Draw(canvas)
        template = scene.data.get("template", "new_listing")
        style = FRAME_TEMPLATES.get(template, FRAME_TEMPLATES["new_listing"])
        primary = style["primary"][:3]

        title_font = _load_font(48, bold=True)
        body_font = _load_font(34, bold=False)
        price_font = _load_font(64, bold=True)

        branding = scene.data.get("branding", {})
        address = scene.data.get("address", "")
        price = scene.data.get("price", "")

        draw.text((64, 400), "Contact Agent", fill=(255, 255, 255), font=title_font)

        y = 500
        agent_name = branding.get("agent_name", "Your Agent")
        draw.text((100, y), agent_name, fill=(255, 255, 255), font=body_font)
        y += 50
        if branding.get("agent_phone"):
            draw.text((100, y), branding["agent_phone"], fill=(200, 200, 200), font=body_font)
            y += 50
        if branding.get("broker_name"):
            draw.text((100, y), branding["broker_name"], fill=(180, 180, 180), font=body_font)

        draw.text((100, h - 300), price, fill=(255, 255, 255), font=price_font)

        return canvas
