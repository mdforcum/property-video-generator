"""Scene frame renderers — v3 (PropertySimple-inspired infographic style).

Design philosophy — modelled after PropertySimple's social video output:
  • Photo scenes: full-bleed cropped photo, no overlay baked in (hero gets
    a separate FFmpeg text-reveal overlay).
  • Stats overlay: vibrant teal→amber gradient tint on the PHOTO itself
    with large icon-style stat callouts (sqft, beds, baths) — NOT a
    separate blurred-background card.
  • Description / features: large bold text directly over a lightly
    dimmed photo with a semi-transparent gradient strip.
  • Schools: clean white background infographic, gradient-bordered cards,
    distances in miles — professional, readable.
  • Map: white background, circular map crop, city/county header with
    location pin, price pin on map.
  • Outro: teal→amber gradient background, company logo, CTA text, agent
    contact info (circular headshot, name, phone, email).

Typography: Poppins Bold for headlines, Poppins Medium/Regular for body.
Colour identity: consistent teal (#0d9488) → amber (#f59e0b) gradient.
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

# Brand gradient colours (Deep Teal → Warm Amber)
GRAD_START = (13, 148, 136)     # #0d9488 teal-600
GRAD_END = (245, 158, 11)       # #f59e0b amber-500
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

def _gradient_bar(w: int, h: int, left_color: Tuple[int, ...] = GRAD_START,
                  right_color: Tuple[int, ...] = GRAD_END, alpha: int = 255) -> Image.Image:
    """Horizontal gradient bar."""
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(w):
        t = x / max(1, w - 1)
        r = int(left_color[0] * (1 - t) + right_color[0] * t)
        g = int(left_color[1] * (1 - t) + right_color[1] * t)
        b = int(left_color[2] * (1 - t) + right_color[2] * t)
        ImageDraw.Draw(bar).line([(x, 0), (x, h - 1)], fill=(r, g, b, alpha))
    return bar


def _gradient_bg(w: int = CANVAS_W, h: int = CANVAS_H, left_color: Tuple[int, ...] = GRAD_START,
                 right_color: Tuple[int, ...] = GRAD_END) -> Image.Image:
    """Full-canvas diagonal gradient teal→amber."""
    canvas = Image.new("RGBA", (w, h), (*left_color, 255))
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(left_color[0] * (1 - t) + right_color[0] * t)
        g = int(left_color[1] * (1 - t) + right_color[1] * t)
        b = int(left_color[2] * (1 - t) + right_color[2] * t)
        ImageDraw.Draw(canvas).line([(0, y), (w, y)], fill=(r, g, b, 255))
    return canvas


def _gradient_tint_on_photo(photo: Image.Image, w: int = CANVAS_W, h: int = CANVAS_H,
                            opacity: int = 160) -> Image.Image:
    """Teal→amber gradient tint overlaid on a photo (for stats scene)."""
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
    """White card with teal→amber gradient border."""
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    # Gradient border (draw slightly larger rounded rect, then white inside)
    # Use gradient bar as border color reference
    grad = _gradient_bar(w, h)
    # Outer border
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius,
                           fill=(*GRAD_START, 255), outline=None)
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
    a teal→amber gradient-tinted listing photo.
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
            icon_fn(draw, x_icon, cy, size=56, fill=(*GRAD_START, 255))
            draw.text((text_x, cy - 30), combined,
                      fill=(*GRAD_START, 255), font=stat_value_font)

    return canvas.convert("RGB")


def render_stats_video_clip(scene: Scene, temp_dir) -> Optional[Path]:
    """Render 4 progressive PNG frames and create animated MP4 clip.

    Frames:
      Frame 0: just the gradient-tinted photo (no text)
      Frame 1: photo + first stat
      Frame 2: photo + first 2 stats
      Frame 3: photo + all stats with pill

    Returns path to the .mp4 clip.
    """
    from pathlib import Path
    temp_path = Path(temp_dir)
    temp_path.mkdir(parents=True, exist_ok=True)

    w, h = CANVAS_W, CANVAS_H
    bg = scene.data.get("bg_image")
    if bg is not None:
        base_canvas = _gradient_tint_on_photo(bg, w, h, opacity=170)
    else:
        base_canvas = _gradient_bg(w, h)

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

    row_height = 160
    total_h = len(rows) * row_height
    start_y = (h - total_h) // 2

    # Frame 0: Just the base photo
    frame0_path = temp_path / "stats_f0.png"
    base_canvas.convert("RGB").save(str(frame0_path))

    # Frames 1-3: Progressive stat reveal
    frames_to_render = [1, 2, 3]
    frame_paths = [frame0_path]

    for frame_num in frames_to_render:
        if frame_num > len(rows):
            continue

        canvas = base_canvas.copy()
        draw = ImageDraw.Draw(canvas)

        # Draw first frame_num rows
        for i in range(frame_num):
            icon_fn, value, label = rows[i]
            cy = start_y + i * row_height + row_height // 2
            x_icon = 120

            icon_fn(draw, x_icon, cy, size=56, fill=(255, 255, 255, 240))

            combined = f"{value} {label}"
            text_x = x_icon + 60
            draw.text((text_x, cy - 30), combined, fill=(255, 255, 255, 255),
                      font=stat_value_font)

            # Draw pill on last visible row (only on frame 3)
            if frame_num == 3 and i == len(rows) - 1 and len(rows) > 1:
                tw = _text_w(draw, combined, stat_value_font)
                pill_pad = 16
                pill = Image.new("RGBA", (tw + pill_pad * 2 + 60, 80), (0, 0, 0, 0))
                pill_draw = ImageDraw.Draw(pill)
                pill_draw.rounded_rectangle((0, 0, pill.width - 1, pill.height - 1),
                                            radius=12, fill=(255, 255, 255, 220))
                canvas.alpha_composite(pill, (text_x - pill_pad - 60, cy - 36))
                # Redraw icon and text in dark on the pill
                draw = ImageDraw.Draw(canvas)
                icon_fn(draw, x_icon, cy, size=56, fill=(*GRAD_START, 255))
                draw.text((text_x, cy - 30), combined,
                          fill=(*GRAD_START, 255), font=stat_value_font)

        frame_path = temp_path / f"stats_f{frame_num}.png"
        canvas.convert("RGB").save(str(frame_path))
        frame_paths.append(frame_path)

    # Create MP4 with FFmpeg — concat each frame held for ~0.8s
    output_path = temp_path / "stats_animation.mp4"
    n_frames = len(frame_paths)

    if n_frames <= 1:
        # Single frame — just return the PNG path, no video needed
        return frame_paths[0] if frame_paths else None

    try:
        import subprocess
        hold_duration = max(0.5, scene.duration / n_frames)

        # Build ffmpeg command with concat demuxer
        concat_list = temp_path / "stats_concat.txt"
        with open(concat_list, "w") as f:
            for fp in frame_paths:
                f.write(f"file '{fp}'\n")
                f.write(f"duration {hold_duration:.2f}\n")
            # Repeat last file (ffmpeg concat demuxer quirk)
            f.write(f"file '{frame_paths[-1]}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-vf", f"scale={CANVAS_W}:{CANVAS_H},format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "28", "-r", "30", "-threads", "1",
            "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        logger.info("Stats animation clip created: %s", output_path)

    except Exception as e:
        logger.warning("FFmpeg animation failed, using last frame as fallback: %s", e)
        # Fallback: return last PNG so pipeline uses it as static frame
        return frame_paths[-1]

    return output_path


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
        # Subtle darken at bottom for text (reduced to 160px)
        shade_height = 160
        dark = Image.new("RGBA", (w, shade_height), (0, 0, 0, 140))
        canvas.alpha_composite(dark, (0, h - shade_height))
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
        bar_y = h - 140
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
            # Use gradient teal color for distance
            draw.text((w - 120 - dw, card_y + card_h // 2 - 24), dist_str,
                      fill=GRAD_START, font=dist_font)

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
    address = scene.data.get("address", "")

    # City header with location pin
    header_font = _font(72, "bold")
    sub_font = _font(36, "bold")

    _draw_icon_pin(draw, 100, 280, size=64, fill=DARK_TEXT)
    city_display = city if city else (address.split(",")[0] if address else "")

    # Wrap city text to avoid overflow, reduce font size if needed
    city_lines = _wrap(draw, city_display, header_font, w - 200, max_lines=2)
    if len(city_lines) > 1 or _text_w(draw, city_display, header_font) > w - 200:
        header_font = _font(56, "bold")
        city_lines = _wrap(draw, city_display, header_font, w - 200, max_lines=2)

    if city_lines:
        draw.text((150, 240), city_lines[0], fill=DARK_TEXT, font=header_font)
        if len(city_lines) > 1:
            draw.text((150, 310), city_lines[1], fill=DARK_TEXT, font=header_font)

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
                                       fill=(*GRAD_START, 230))
            # Triangle pointer
            tri_cx = pin_w // 2
            pin_draw.polygon([(tri_cx - 10, pin_h - 2), (tri_cx + 10, pin_h - 2),
                              (tri_cx, pin_h + 14)], fill=(*GRAD_START, 230))
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
# OUTRO — gradient background with company logo, CTA text, agent contact info
# ============================================================================

@_register(SceneType.OUTRO)
def _render_outro(scene: Scene) -> Image.Image:
    """Merged CTA + contact card with gradient background.

    Layout (top to bottom):
    - Teal→amber gradient background
    - Company logo (350px max width, 140px max height)
    - "Thinking of buying or selling?" text (white, bold 56px)
    - Location text (white, 36px)
    - Horizontal divider line (white, 50% opacity)
    - Circular agent headshot (320px diameter)
    - Agent name (white, bold 64px)
    - Brokerage name (white, regular 32px)
    - Phone number in white pill (solid white bg, dark text)
    - Email with envelope icon (white text)
    """
    w, h = CANVAS_W, CANVAS_H
    canvas = _gradient_bg(w, h, GRAD_START, GRAD_END)
    draw = ImageDraw.Draw(canvas)

    branding = scene.data.get("branding", {})
    branding_assets = scene.data.get("branding_assets", {})
    city = scene.data.get("city", "")
    county = scene.data.get("county", "")
    agent_name = scene.data.get("agent_name", "")

    # Fonts
    cta_font = _font(56, "bold")
    location_font = _font(36, "medium")
    name_font = _font(64, "bold")
    broker_font = _font(32, "regular")
    phone_font = _font(40, "bold")
    email_font = _font(28, "regular")
    divider_y = 400

    # Company logo at top
    broker_logo = branding_assets.get("broker_logo") if branding_assets else None
    if broker_logo is not None:
        logo = broker_logo.copy().convert("RGBA")
        logo.thumbnail((350, 140), Image.Resampling.LANCZOS)
        logo_x = (w - logo.width) // 2
        canvas.alpha_composite(logo, (logo_x, 80))

    # "Thinking of buying or selling?" text
    location = county if county else city
    cta_text = f"Thinking of buying or selling in {location}?" if location else "Thinking of buying or selling?"
    margin = 60
    cta_lines = _wrap(draw, cta_text, cta_font, w - margin * 2, max_lines=4)

    cta_y = 260
    for line in cta_lines:
        draw.text((margin, cta_y), line, fill=(255, 255, 255, 255), font=cta_font)
        cta_y += 70

    # Location display (county/city)
    if location:
        loc_w = _text_w(draw, location.upper(), location_font)
        draw.text(((w - loc_w) // 2, cta_y + 30), location.upper(),
                  fill=(255, 255, 255, 255), font=location_font)

    # Horizontal divider line (white, 50% opacity)
    divider_y = cta_y + 100
    divider = Image.new("RGBA", (w, 2), (0, 0, 0, 0))
    divider_draw = ImageDraw.Draw(divider)
    divider_draw.rectangle((0, 0, w - 1, 1), fill=(255, 255, 255, 128))
    canvas.alpha_composite(divider, (0, divider_y))

    # Circular agent headshot (320px diameter)
    agent_photo = branding_assets.get("agent_photo") if branding_assets else None
    photo_diameter = 320
    photo_y = divider_y + 80

    if agent_photo is not None:
        circular = _circular_crop(agent_photo, photo_diameter)
        canvas.alpha_composite(circular, ((w - photo_diameter) // 2, photo_y))
        draw = ImageDraw.Draw(canvas)

    # Agent name
    name_y = photo_y + photo_diameter + 60
    if agent_name:
        nw = _text_w(draw, agent_name, name_font)
        draw.text(((w - nw) // 2, name_y), agent_name, fill=(255, 255, 255, 255),
                  font=name_font)

    # Brokerage name
    broker_name = (branding.get("broker_name") or "").strip()
    broker_y = name_y + 90
    if broker_name:
        bw = _text_w(draw, broker_name, broker_font)
        draw.text(((w - bw) // 2, broker_y), broker_name, fill=(255, 255, 255, 255),
                  font=broker_font)

    # Phone number in solid white pill (dark text inside)
    agent_phone = (branding.get("agent_phone") or "").strip()
    phone_y = broker_y + 80
    if agent_phone:
        phone_display = agent_phone
        tw = _text_w(draw, phone_display, phone_font)
        pill_w = tw + 80
        pill_h = 68
        pill_x = (w - pill_w) // 2

        # Solid white pill background
        pill = Image.new("RGBA", (pill_w, pill_h), (255, 255, 255, 255))
        pill_mask = Image.new("L", (pill_w, pill_h), 0)
        ImageDraw.Draw(pill_mask).rounded_rectangle(
            (0, 0, pill_w - 1, pill_h - 1), radius=pill_h // 2, fill=255)
        pill.putalpha(pill_mask)
        canvas.alpha_composite(pill, (pill_x, phone_y))
        draw = ImageDraw.Draw(canvas)

        # Dark text on white pill
        draw.text((pill_x + 40, phone_y + 12), phone_display,
                  fill=DARK_TEXT, font=phone_font)
        info_y = phone_y + pill_h

    # Email with envelope icon
    agent_email = (branding.get("agent_email") or "").strip()
    if agent_email:
        email_y = info_y + 50
        ew = _text_w(draw, agent_email, email_font)
        total_w = ew + 44
        ex = (w - total_w) // 2

        # Envelope icon in white
        draw.rectangle((ex, email_y + 6, ex + 28, email_y + 22), outline=(255, 255, 255, 255), width=2)
        draw.line([(ex, email_y + 6), (ex + 14, email_y + 16), (ex + 28, email_y + 6)],
                  fill=(255, 255, 255, 255), width=2)

        # Email text in white
        draw.text((ex + 44, email_y), agent_email, fill=(255, 255, 255, 255), font=email_font)

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
