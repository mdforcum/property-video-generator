"""Data enrichment for listing scenes.

Extracts structured data from the IDX listing's __PRELOADED_STATE__
JSON to populate scene data payloads:
  - Stats (beds, baths, sqft, lot size, year built, garage)
  - Description (MLS remarks / AI-generated)
  - Features (from detail_groups)
  - Schools (from GreatSchools API or detail_groups fallback)
  - Static map (from OpenStreetMap / MapBox / Google static maps)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image

logger = logging.getLogger(__name__)


# ============================================================================
# STATS EXTRACTION
# ============================================================================

def extract_stats(listing: Dict[str, Any]) -> Dict[str, str]:
    """Extract property stats from a listing dict (from __PRELOADED_STATE__).

    Returns a dict with keys: beds, baths, sqft, lot_size, year_built, garage.
    Empty string for any field not present.
    """
    stats: Dict[str, str] = {}

    beds = listing.get("beds")
    if beds is not None and str(beds).strip():
        stats["beds"] = str(int(beds)) if isinstance(beds, (int, float)) else str(beds)

    baths = listing.get("baths")
    if baths is not None and str(baths).strip():
        val = float(baths) if isinstance(baths, (int, float)) else baths
        # Show as integer if whole number
        if isinstance(val, float) and val == int(val):
            stats["baths"] = str(int(val))
        else:
            stats["baths"] = str(val)

    sqft = listing.get("sqft")
    if sqft is not None and str(sqft).strip():
        try:
            stats["sqft"] = f"{int(sqft):,}"
        except (ValueError, TypeError):
            stats["sqft"] = str(sqft)

    lot_size = listing.get("lotSize")
    if lot_size is not None and str(lot_size).strip():
        try:
            val = float(lot_size)
            if val >= 1:
                stats["lot_size"] = f"{val:.1f} acres"
            else:
                stats["lot_size"] = f"{val:.2f} acres"
        except (ValueError, TypeError):
            stats["lot_size"] = str(lot_size)

    year_built = listing.get("yearBuilt")
    if year_built is not None and str(year_built).strip():
        stats["year_built"] = str(int(year_built)) if isinstance(year_built, (int, float)) else str(year_built)

    garage = listing.get("garage")
    if garage is not None and int(garage) > 0:
        stats["garage"] = str(int(garage))

    stories = listing.get("stories")
    if stories is not None and str(stories).strip():
        try:
            s = int(stories)
            if s > 1:
                stats["stories"] = str(s)
        except (ValueError, TypeError):
            pass

    return stats


# ============================================================================
# DESCRIPTION EXTRACTION
# ============================================================================

def extract_description(listing: Dict[str, Any]) -> str:
    """Extract property description from listing data.

    Falls back to meta_description if main description is missing.
    Cleans up common MLS formatting artifacts.
    """
    desc = (listing.get("description") or "").strip()
    if not desc:
        desc = (listing.get("meta_description") or "").strip()
    if not desc:
        return ""

    # Clean up common MLS formatting
    desc = re.sub(r"\s+", " ", desc)  # collapse whitespace
    desc = re.sub(r"!{2,}", "!", desc)  # reduce multiple exclamation marks
    desc = desc.replace("  ", " ")

    # Truncate to ~500 chars for the video card (keeps it readable at 34px font)
    if len(desc) > 500:
        # Find a sentence break near 500
        cutoff = desc[:500].rfind(".")
        if cutoff > 300:
            desc = desc[:cutoff + 1]
        else:
            cutoff = desc[:500].rfind(" ")
            desc = desc[:cutoff] + "..." if cutoff > 0 else desc[:500] + "..."

    return desc


# ============================================================================
# FEATURES EXTRACTION
# ============================================================================

# Labels from detail_groups that make good video features
_FEATURE_LABELS = {
    "Appliances", "Cooling", "Heating", "Flooring", "Exterior Features",
    "Interior Features", "Parking Features", "Laundry Features",
    "Pool Features", "Spa Features", "Waterfront Features",
    "Community Features", "Security Features", "Accessibility Features",
    "Construction Materials", "Roof", "Basement", "Fireplace",
    "Water Source", "Utilities", "Style",
}

# Feature labels to skip (not visually interesting for video)
_SKIP_LABELS = {
    "Zoning", "Tax Annual Amount", "Tax Year", "Source System",
    "Foundation Details", "MLS Area Major", "Total Rooms",
    "Above Grade Finished Area", "Below Grade Finished Area",
    "Listing #", "Listing Date", "Source System Name",
}


def extract_features(listing: Dict[str, Any]) -> List[str]:
    """Extract key features from detail_groups for the features card.

    Returns a list of human-readable feature strings, e.g.:
      ["Central Air Conditioning", "Hardwood Floors", "Deck & Patio"]
    """
    features: List[str] = []
    detail_groups = listing.get("detail_groups", {})

    if not isinstance(detail_groups, dict):
        return features

    # Pull from specific groups
    for group_name in ["Additional Information", "Features", "Construction", "Highlights Info"]:
        group = detail_groups.get(group_name, {})
        items = group.get("items", [])
        if not isinstance(items, list):
            continue

        for item in items:
            label = str(item.get("label", "")).strip()
            value = str(item.get("value", "")).strip()

            if not label or not value or label in _SKIP_LABELS:
                continue

            if label in _FEATURE_LABELS:
                # Format nicely
                feature = _format_feature(label, value)
                if feature and feature not in features:
                    features.append(feature)

    # Also synthesize features from top-level fields if not already covered
    if listing.get("garage") and int(listing.get("garage", 0)) > 0:
        garage_feat = f"{int(listing['garage'])}-Car Garage"
        if garage_feat not in features:
            features.append(garage_feat)

    if listing.get("stories"):
        try:
            s = int(listing["stories"])
            story_feat = f"{s}-Story Home" if s > 1 else "Single-Story Ranch"
            if story_feat not in features and "Style" not in str(features):
                features.append(story_feat)
        except (ValueError, TypeError):
            pass

    return features[:10]  # Cap at 10 features for the card


def _format_feature(label: str, value: str) -> str:
    """Format a detail_group item into a readable feature string."""
    # Some values are comma-separated lists; pick the most interesting
    if label == "Cooling":
        return f"{value} Cooling" if "cooling" not in value.lower() else value
    if label == "Heating":
        return f"{value} Heating" if "heating" not in value.lower() else value
    if label == "Appliances":
        # Count appliances
        items = [x.strip() for x in value.split(",")]
        if len(items) > 3:
            return f"{len(items)} Appliances Included"
        return value
    if label == "Construction Materials":
        return f"{value} Construction"
    if label == "Style":
        return f"{value} Style"
    if label == "Basement":
        if value.lower() in ("none", "crawl space", "crawlspace"):
            return ""  # Not interesting
        return f"Basement: {value}"
    if label == "Roof":
        return f"{value} Roof"
    if label == "Flooring":
        return f"{value} Floors"
    if label in ("Exterior Features", "Interior Features"):
        return value  # Already descriptive
    return f"{value}" if label == value else f"{value}"


# ============================================================================
# SCHOOLS EXTRACTION
# ============================================================================

def extract_schools_from_listing(listing: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract school info from the listing's detail_groups.

    This is a fallback when no external schools API is available.
    """
    schools: List[Dict[str, str]] = []
    detail_groups = listing.get("detail_groups", {})

    if not isinstance(detail_groups, dict):
        return schools

    school_group = detail_groups.get("Schools", {})
    items = school_group.get("items", [])

    for item in items if isinstance(items, list) else []:
        label = str(item.get("label", "")).strip()
        value = str(item.get("value", "")).strip()
        if label and value:
            schools.append({
                "name": value,
                "type": label,
                "rating": "",
                "distance": "",
                "grades": "",
            })

    return schools


def fetch_schools_from_api(
    lat: float,
    lng: float,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch nearby schools from the GreatSchools API.

    Falls back gracefully if no API key or if the request fails.
    Uses the free GreatSchools /schools/nearby endpoint.

    Returns list of dicts with: name, rating, distance, grades, type
    """
    if not api_key:
        logger.info("No GreatSchools API key configured — skipping schools fetch")
        return []

    url = "https://gs-api.greatschools.org/schools"
    params = {
        "lat": lat,
        "lon": lng,
        "limit": 5,
        "distance": 5,  # miles
    }
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        schools = []
        for s in data.get("schools", [])[:5]:
            schools.append({
                "name": s.get("name", "Unknown School"),
                "rating": str(s.get("rating", "?")),
                "distance": str(round(s.get("distance", 0), 1)),
                "grades": s.get("grades", ""),
                "type": s.get("type", ""),
            })
        return schools

    except Exception as e:
        logger.warning("GreatSchools API request failed: %s", e)
        return []


# ============================================================================
# STATIC MAP GENERATION
# ============================================================================

def fetch_static_map(
    lat: float,
    lng: float,
    width: int = 1080,
    height: int = 1920,
    zoom: int = 15,
    mapbox_token: Optional[str] = None,
) -> Optional[Image.Image]:
    """Fetch a static map image centered on the listing's coordinates.

    Tries MapBox first (higher quality), then OpenStreetMap tiles as fallback.
    Returns a PIL Image or None on failure.
    """
    # Try MapBox Static API
    if mapbox_token:
        try:
            url = (
                f"https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/"
                f"pin-l+0d9488({lng},{lat})/"
                f"{lng},{lat},{zoom},0/"
                f"{width}x{height}@2x"
                f"?access_token={mapbox_token}"
            )
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            from io import BytesIO
            return Image.open(BytesIO(resp.content)).convert("RGB")
        except Exception as e:
            logger.warning("MapBox static map failed: %s", e)

    # Fallback: OpenStreetMap static tile (via staticmap-style URL)
    try:
        # Use a simple OSM tile approach — grab center tile and surrounding
        url = (
            f"https://staticmap.openstreetmap.de/staticmap.php"
            f"?center={lat},{lng}&zoom={zoom}&size={min(width, 1024)}x{min(height, 1024)}"
            f"&markers={lat},{lng},red-pushpin"
            f"&maptype=mapnik"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        from io import BytesIO
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        # Resize to target dimensions
        if img.size != (width, height):
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        logger.warning("OpenStreetMap static map failed: %s", e)

    return None


# ============================================================================
# MASTER ENRICHMENT FUNCTION
# ============================================================================

def enrich_listing_data(
    html: str,
    url: str,
    *,
    greatschools_api_key: Optional[str] = None,
    mapbox_token: Optional[str] = None,
    fetch_map: bool = True,
    fetch_schools: bool = True,
) -> Dict[str, Any]:
    """Extract all enrichment data from a Shelby IDX listing page.

    This is the single entry point that process_video_task_v2 calls.
    Returns a dict with keys: stats, description, features, schools, map_image, latLng

    All values are Optional — missing data returns empty/None gracefully.
    """
    result: Dict[str, Any] = {
        "stats": {},
        "description": "",
        "features": [],
        "schools": [],
        "map_image": None,
        "lat": None,
        "lng": None,
    }

    # Parse __PRELOADED_STATE__
    state_match = re.search(r"__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
    if not state_match:
        logger.info("No __PRELOADED_STATE__ found — enrichment unavailable")
        return result

    try:
        state = json.loads(state_match.group(1))
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse __PRELOADED_STATE__: %s", e)
        return result

    listings = state.get("listings", {})
    if not isinstance(listings, dict) or not listings:
        return result

    # Find the listing
    listing_key_match = re.search(r"/idx/listing/([^/]+)/([^/]+)(?:/|$)", url)
    listing = None
    if listing_key_match:
        mls_id = listing_key_match.group(1)
        mls_no = listing_key_match.group(2)
        listing = listings.get(f"{mls_id}-{mls_no}")
    if listing is None:
        listing = next(iter(listings.values()))

    if not isinstance(listing, dict):
        return result

    # --- Extract all enrichment data ---
    result["stats"] = extract_stats(listing)
    result["description"] = extract_description(listing)
    result["features"] = extract_features(listing)

    # Coordinates
    lat_lng = listing.get("latLng")
    if isinstance(lat_lng, (list, tuple)) and len(lat_lng) >= 2:
        result["lat"] = float(lat_lng[0])
        result["lng"] = float(lat_lng[1])

    # Schools
    if fetch_schools:
        if result["lat"] and result["lng"] and greatschools_api_key:
            result["schools"] = fetch_schools_from_api(
                result["lat"], result["lng"],
                api_key=greatschools_api_key,
            )
        if not result["schools"]:
            # Fallback to listing detail_groups
            result["schools"] = extract_schools_from_listing(listing)

    # Map
    if fetch_map and result["lat"] and result["lng"]:
        result["map_image"] = fetch_static_map(
            result["lat"], result["lng"],
            mapbox_token=mapbox_token,
        )

    logger.info(
        "Enrichment complete: stats=%d fields, desc=%d chars, features=%d, schools=%d, map=%s",
        len(result["stats"]),
        len(result["description"]),
        len(result["features"]),
        len(result["schools"]),
        result["map_image"] is not None,
    )

    return result
