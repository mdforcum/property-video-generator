"""Scene list builder.

Takes scraped listing data (address, price, photos, metadata) and
assembles an ordered list of Scene objects that define the video's
full storyboard.

The builder is the single place where scene ORDER, scene SELECTION,
and scene DATA binding happen.  Renderers don't know about the listing;
the builder packages what each renderer needs in scene.data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PIL import Image

from .models import Scene, SceneType, MotionProfile

logger = logging.getLogger(__name__)


def build_scene_list(
    *,
    address: str,
    price: str,
    photos: List[Image.Image],
    template: str = "new_listing",
    branding: Optional[Dict[str, str]] = None,
    branding_assets: Optional[Dict[str, Optional[Image.Image]]] = None,
    # --- Optional enrichment data (Phase 2) ---
    stats: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    features: Optional[List[str]] = None,
    schools: Optional[List[Dict[str, Any]]] = None,
    map_image: Optional[Image.Image] = None,
) -> List[Scene]:
    """Build the ordered scene list for a listing video.

    Required args produce the baseline video (hero + interior photos + outro)
    which matches the current auto-reel output.  Optional enrichment args
    unlock the new data-card scenes when available.

    Returns:
        Ordered list of Scene objects ready for rendering and video assembly.
    """
    branding = branding or {}
    branding_assets = branding_assets or {}
    scenes: List[Scene] = []

    if not photos:
        logger.warning("build_scene_list called with no photos — returning empty scene list")
        return scenes

    # Grab the first photo as potential blurred background for data cards
    bg_image = photos[0] if photos else None

    # ---------------------------------------------------------------
    # 1. HERO PHOTO  (always first)
    # ---------------------------------------------------------------
    scenes.append(Scene(
        scene_type=SceneType.HERO_PHOTO,
        motion=MotionProfile.KEN_BURNS,
        data={"photo_image": photos[0]},
    ))

    # ---------------------------------------------------------------
    # 2. STATS CARD  (if we have stats data)
    # ---------------------------------------------------------------
    if stats and any(stats.values()):
        scenes.append(Scene(
            scene_type=SceneType.STATS_CARD,
            has_own_overlay=True,
            data={
                **stats,
                "address": address,
                "price": price,
                "template": template,
                "bg_image": bg_image,
            },
        ))

    # ---------------------------------------------------------------
    # 3. INTERIOR PHOTOS  (photos 2..N, interleaved with data cards)
    # ---------------------------------------------------------------
    interior_photos = photos[1:]

    # Split interiors into two groups for interleaving
    mid = len(interior_photos) // 2
    first_batch = interior_photos[:mid] if mid > 0 else interior_photos
    second_batch = interior_photos[mid:] if mid > 0 else []

    # First batch of interior photos
    for photo in first_batch:
        scenes.append(Scene(
            scene_type=SceneType.INTERIOR_PHOTO,
            motion=MotionProfile.KEN_BURNS,
            data={"photo_image": photo},
        ))

    # ---------------------------------------------------------------
    # 4. DESCRIPTION CARD  (between photo batches if available)
    # ---------------------------------------------------------------
    if description and description.strip():
        scenes.append(Scene(
            scene_type=SceneType.DESCRIPTION_CARD,
            has_own_overlay=True,
            data={
                "description": description,
                "address": address,
                "price": price,
                "template": template,
                "bg_image": bg_image,
            },
        ))

    # Second batch of interior photos
    for photo in second_batch:
        scenes.append(Scene(
            scene_type=SceneType.INTERIOR_PHOTO,
            motion=MotionProfile.KEN_BURNS,
            data={"photo_image": photo},
        ))

    # ---------------------------------------------------------------
    # 5. FEATURES CARD  (if we have features)
    # ---------------------------------------------------------------
    if features and len(features) >= 2:
        scenes.append(Scene(
            scene_type=SceneType.FEATURES_CARD,
            has_own_overlay=True,
            data={
                "features": features,
                "address": address,
                "template": template,
                "bg_image": bg_image,
            },
        ))

    # ---------------------------------------------------------------
    # 6. SCHOOLS CARD  (if we have school data)
    # ---------------------------------------------------------------
    if schools and len(schools) >= 1:
        scenes.append(Scene(
            scene_type=SceneType.SCHOOLS_CARD,
            has_own_overlay=True,
            data={
                "schools": schools,
                "address": address,
                "template": template,
                "bg_image": bg_image,
            },
        ))

    # ---------------------------------------------------------------
    # 7. MAP CTA  (if we have a map image or always as placeholder)
    # ---------------------------------------------------------------
    if map_image is not None:
        scenes.append(Scene(
            scene_type=SceneType.MAP_CTA,
            has_own_overlay=True,
            data={
                "map_image": map_image,
                "address": address,
                "price": price,
                "template": template,
            },
        ))

    # ---------------------------------------------------------------
    # 8. OUTRO  (always last)
    # ---------------------------------------------------------------
    scenes.append(Scene(
        scene_type=SceneType.OUTRO,
        has_own_overlay=True,
        transition="fade",
        data={
            "address": address,
            "price": price,
            "branding": branding,
            "template": template,
            "branding_assets": branding_assets,
        },
    ))

    logger.info(
        "Built scene list: %d scenes (%s)",
        len(scenes),
        ", ".join(s.scene_type.value for s in scenes),
    )
    return scenes
