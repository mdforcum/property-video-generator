"""Scene list builder — v3 (PropertySimple-inspired flow).

Scene order matches the PS video structure:
  1. Hero photo
  2. Stats overlay (gradient-tinted photo with sqft / beds / baths)
  3. Interior photos (first batch)
  4. Description card (bold text over dimmed photo)
  5. Interior photos (second batch)
  6. Features card (lot size / year built callout over photo)
  7. Map infographic (white bg, circular crop)
  8. Schools infographic (white bg, gradient-bordered cards)
  9. Outro (white bg, agent headshot, phone pill)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from PIL import Image

from .models import Scene, SceneType, MotionProfile

logger = logging.getLogger(__name__)


def _extract_city(address: str) -> str:
    """Best-effort city extraction from an address string."""
    parts = [p.strip() for p in address.split(",")]
    if len(parts) >= 2:
        # "801 Cleveland Street, Effingham, IL 62401" → "Effingham"
        return parts[-2] if len(parts) >= 3 else parts[1].split()[0]
    return ""


def _extract_county(address: str, schools: Optional[List[Dict[str, Any]]] = None) -> str:
    """Try to determine county from schools data or address."""
    # Schools often include district/county info
    if schools:
        for s in schools:
            district = s.get("district", "")
            if district:
                return district
    return ""


def build_scene_list(
    *,
    address: str,
    price: str,
    photos: List[Image.Image],
    template: str = "new_listing",
    branding: Optional[Dict[str, str]] = None,
    branding_assets: Optional[Dict[str, Optional[Image.Image]]] = None,
    # --- Optional enrichment data ---
    stats: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    features: Optional[List[str]] = None,
    schools: Optional[List[Dict[str, Any]]] = None,
    map_image: Optional[Image.Image] = None,
) -> List[Scene]:
    """Build the ordered scene list for a listing video."""
    branding = branding or {}
    branding_assets = branding_assets or {}
    scenes: List[Scene] = []

    if not photos:
        logger.warning("build_scene_list: no photos — returning empty list")
        return scenes

    bg_image = photos[0]
    city = _extract_city(address)
    county = _extract_county(address, schools)

    # ---------------------------------------------------------------
    # 1. HERO PHOTO  (always first)
    # ---------------------------------------------------------------
    scenes.append(Scene(
        scene_type=SceneType.HERO_PHOTO,
        motion=MotionProfile.KEN_BURNS,
        data={"photo_image": photos[0]},
    ))

    # ---------------------------------------------------------------
    # 2. STATS OVERLAY  (gradient-tinted photo with key stats)
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
    # 3. INTERIOR PHOTOS — first batch
    # ---------------------------------------------------------------
    interior_photos = photos[1:]
    mid = len(interior_photos) // 2
    first_batch = interior_photos[:mid] if mid > 0 else interior_photos
    second_batch = interior_photos[mid:] if mid > 0 else []

    for photo in first_batch:
        scenes.append(Scene(
            scene_type=SceneType.INTERIOR_PHOTO,
            motion=MotionProfile.KEN_BURNS,
            data={"photo_image": photo},
        ))

    # ---------------------------------------------------------------
    # 4. DESCRIPTION CARD  (bold text over dimmed photo)
    # ---------------------------------------------------------------
    if description and description.strip():
        # Use a different photo for visual variety if available
        desc_bg = photos[1] if len(photos) > 1 else bg_image
        scenes.append(Scene(
            scene_type=SceneType.DESCRIPTION_CARD,
            has_own_overlay=True,
            duration=4.5,
            data={
                "description": description,
                "address": address,
                "city": city,
                "sqft": (stats or {}).get("sqft", ""),
                "lot_size": (stats or {}).get("lot_size", ""),
                "template": template,
                "bg_image": desc_bg,
            },
        ))

    # ---------------------------------------------------------------
    # 5. INTERIOR PHOTOS — second batch
    # ---------------------------------------------------------------
    for photo in second_batch:
        scenes.append(Scene(
            scene_type=SceneType.INTERIOR_PHOTO,
            motion=MotionProfile.KEN_BURNS,
            data={"photo_image": photo},
        ))

    # ---------------------------------------------------------------
    # 6. FEATURES CARD  (lot size / year built callout on photo)
    # ---------------------------------------------------------------
    if stats and (stats.get("lot_size") or stats.get("year_built")):
        feat_bg = photos[0]
        scenes.append(Scene(
            scene_type=SceneType.FEATURES_CARD,
            has_own_overlay=True,
            data={
                "lot_size": stats.get("lot_size", ""),
                "year_built": stats.get("year_built", ""),
                "garage": stats.get("garage", ""),
                "features": features or [],
                "template": template,
                "bg_image": feat_bg,
            },
        ))

    # ---------------------------------------------------------------
    # 7. MAP INFOGRAPHIC  — REMOVED
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # 8. SCHOOLS INFOGRAPHIC  — REMOVED
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # 9. OUTRO  (white bg, agent headshot, gradient phone pill)
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
            "city": city,
            "county": county,
            "agent_name": (branding.get("agent_name") or "").strip(),
        },
    ))

    logger.info(
        "Built scene list: %d scenes (%s)",
        len(scenes),
        ", ".join(s.scene_type.value for s in scenes),
    )
    return scenes
