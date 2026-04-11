"""Shared constants for the scene engine.

These are extracted from main.py to avoid circular imports when
renderers need access to template colors without importing the
entire main module (which pulls in ffmpeg, supabase, etc.).
"""

from typing import Any, Dict

FRAME_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "new_listing": {
        "label": "NEW LISTING",
        "primary": (34, 130, 255, 230),
        "secondary": (100, 190, 255, 220),
        "chip_fill": (16, 84, 196, 220),
    },
    "price_update": {
        "label": "PRICE UPDATE",
        "primary": (245, 158, 11, 235),
        "secondary": (251, 191, 36, 220),
        "chip_fill": (180, 83, 9, 220),
    },
    "under_contract": {
        "label": "UNDER CONTRACT",
        "primary": (139, 92, 246, 235),
        "secondary": (196, 181, 253, 220),
        "chip_fill": (91, 33, 182, 220),
    },
    "sold": {
        "label": "SOLD",
        "primary": (239, 68, 68, 235),
        "secondary": (252, 165, 165, 220),
        "chip_fill": (153, 27, 27, 225),
    },
}
