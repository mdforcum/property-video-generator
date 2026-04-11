"""Scene data models.

A Scene is the atomic unit of video composition. Each scene knows:
  - what TYPE of content it represents (photo, stats card, etc.)
  - how long it should last on screen
  - what DATA it needs to render its frame
  - what MOTION profile FFmpeg should apply (Ken Burns, static, slow zoom)
  - whether it carries its own overlay or relies on the global overlay
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image


class SceneType(str, Enum):
    """Every scene in the video is one of these types."""

    # --- Photo scenes (existing functionality) ---
    HERO_PHOTO = "hero_photo"          # First photo — gets the label chip + address
    INTERIOR_PHOTO = "interior_photo"  # Standard listing photo with Ken Burns

    # --- Data-card scenes (new) ---
    STATS_CARD = "stats_card"          # Beds / Baths / SqFt / Lot Size
    DESCRIPTION_CARD = "description_card"  # AI property description text
    FEATURES_CARD = "features_card"    # Key features / amenities list
    SCHOOLS_CARD = "schools_card"      # Nearby schools infographic
    MAP_CTA = "map_cta"               # Map image + call-to-action text

    # --- Branding scenes ---
    OUTRO = "outro"                    # Contact card / outro (existing)


class MotionProfile(str, Enum):
    """How FFmpeg should animate the rendered frame."""

    KEN_BURNS = "ken_burns"   # Zoom + pan  (for photos)
    STATIC = "static"         # No motion   (for data cards)
    SLOW_ZOOM = "slow_zoom"   # Gentle push-in (for outro / map)


# Default durations per scene type (seconds)
DEFAULT_DURATIONS: Dict[SceneType, float] = {
    SceneType.HERO_PHOTO: 3.0,
    SceneType.INTERIOR_PHOTO: 2.2,
    SceneType.STATS_CARD: 3.5,
    SceneType.DESCRIPTION_CARD: 4.0,
    SceneType.FEATURES_CARD: 3.5,
    SceneType.SCHOOLS_CARD: 3.5,
    SceneType.MAP_CTA: 3.0,
    SceneType.OUTRO: 3.0,
}

# Default motion profiles per scene type
DEFAULT_MOTION: Dict[SceneType, MotionProfile] = {
    SceneType.HERO_PHOTO: MotionProfile.KEN_BURNS,
    SceneType.INTERIOR_PHOTO: MotionProfile.KEN_BURNS,
    SceneType.STATS_CARD: MotionProfile.STATIC,
    SceneType.DESCRIPTION_CARD: MotionProfile.STATIC,
    SceneType.FEATURES_CARD: MotionProfile.STATIC,
    SceneType.SCHOOLS_CARD: MotionProfile.STATIC,
    SceneType.MAP_CTA: MotionProfile.SLOW_ZOOM,
    SceneType.OUTRO: MotionProfile.STATIC,
}


@dataclass
class Scene:
    """A single scene in a video composition.

    Attributes:
        scene_type:    What kind of content this scene shows.
        duration:      How long (seconds) this scene appears on screen.
        motion:        FFmpeg motion profile to apply.
        data:          Arbitrary payload the renderer needs (photo path,
                       stats dict, description text, etc.).
        rendered_frame: After rendering, the PIL Image for this scene.
                       Set by the renderer, not by the caller.
        frame_path:    After saving to disk, the file path of the rendered
                       frame.  Set by the pipeline, not by the caller.
        has_own_overlay: If True, the scene's rendered frame already contains
                        all overlay / text elements.  The pipeline will NOT
                        composite the global overlay on top.
        transition:    Optional transition override for the xfade into THIS
                       scene (e.g. "fade", "wipeleft").  None = auto-pick.
    """

    scene_type: SceneType
    duration: float = 0.0
    motion: MotionProfile = MotionProfile.STATIC
    data: Dict[str, Any] = field(default_factory=dict)

    # Set during rendering — not constructor args
    rendered_frame: Optional[Image.Image] = field(default=None, repr=False)
    frame_path: Optional[Path] = field(default=None, repr=False)

    has_own_overlay: bool = False
    transition: Optional[str] = None

    def __post_init__(self) -> None:
        if self.duration <= 0:
            self.duration = DEFAULT_DURATIONS.get(self.scene_type, 2.5)
        if self.motion == MotionProfile.STATIC and self.scene_type in DEFAULT_MOTION:
            self.motion = DEFAULT_MOTION[self.scene_type]
