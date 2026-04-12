import gc
import os
import re
import shutil
import tempfile
import json
import logging
import time
import subprocess
import threading
import random
import hashlib
from functools import lru_cache
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ffmpeg
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from supabase import create_client

load_dotenv(override=False)

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "videos")
FRONTEND_ORIGINS = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000")
DEFAULT_FRONTEND_ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)*vercel\.app$|^http://localhost(:\d+)?$|^http://127\.0\.0\.1(:\d+)?$"
FRONTEND_ORIGIN_REGEX = (os.getenv("FRONTEND_ORIGIN_REGEX") or "").strip() or DEFAULT_FRONTEND_ORIGIN_REGEX

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
LOGO_PATH = ASSETS_DIR / "shelby_logo.png"
MUSIC_PATH = ASSETS_DIR / "background.mp3"
AGENT_DIRECTORY_PATH = Path(os.getenv("AGENT_DIRECTORY_PATH", str(Path(__file__).resolve().parent / "data" / "agent_directory.json")))

OFFICE_PHONE_BY_CITY = {
    "shelbyville": "217-774-5596",
    "effingham": "217-342-2775",
    "sullivan": "217-728-0728",
}
OFFICE_ADDRESS_BY_CITY = {
    "shelbyville": "615 W Main St, Shelbyville, IL 62565",
    "effingham": "901 N Keller Dr, Effingham, IL 62401",
    "sullivan": "5 West Jefferson, Sullivan, IL 61951",
}
TOLL_FREE_PHONE = "855-215-3400"
ENABLE_BACKGROUND_AUDIO = os.getenv("ENABLE_BACKGROUND_AUDIO", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_SOURCE_IMAGES = max(1, int(os.getenv("MAX_SOURCE_IMAGES", "5")))
MAX_JOB_SECONDS = max(60, int(os.getenv("MAX_JOB_SECONDS", "420")))
FFMPEG_TIMEOUT_SECONDS = max(30, int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "360")))
MAX_CONCURRENT_GENERATIONS = max(1, int(os.getenv("MAX_CONCURRENT_GENERATIONS", "1")))
STALE_JOB_SECONDS = max(
    MAX_JOB_SECONDS + 60,
    int(os.getenv("STALE_JOB_SECONDS", str(MAX_JOB_SECONDS + 120))),
)

REEL_WIDTH = 1080
REEL_HEIGHT = 1920
REEL_MARGIN_X = 64
REEL_PHOTO_TOP = 184
REEL_PHOTO_HEIGHT = 1140
REEL_PHOTO_WIDTH = REEL_WIDTH - (REEL_MARGIN_X * 2)
REEL_CARD_TOP = 1360
REEL_CARD_BOTTOM = 1728
REEL_CARD_LEFT = REEL_MARGIN_X
REEL_CARD_RIGHT = REEL_WIDTH - REEL_MARGIN_X
REEL_PER_IMAGE_SECONDS = max(1.4, float(os.getenv("REEL_PER_IMAGE_SECONDS", "2.2")))
REEL_TRANSITION_SECONDS = max(0.2, float(os.getenv("REEL_TRANSITION_SECONDS", "0.45")))
REEL_OUTRO_SECONDS = max(2.0, float(os.getenv("REEL_OUTRO_SECONDS", "3.0")))

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

JOB_PROGRESS_LOCK = threading.Lock()
JOB_PROGRESS: Dict[str, int] = {}

SOCIAL_PROFILE = (os.getenv("SOCIAL_PROFILE", "facebook").strip().lower() or "facebook")
SOCIAL_PROFILE_DEFAULTS: Dict[str, Dict[str, int]] = {
    "facebook": {
        "top": 160,
        "bottom": 380,
        "side": 56,
        "right_gutter": 220,
    },
    "instagram": {
        "top": 190,
        "bottom": 340,
        "side": 64,
        "right_gutter": 170,
    },
    "tiktok": {
        "top": 210,
        "bottom": 420,
        "side": 56,
        "right_gutter": 240,
    },
}
_safe_defaults = SOCIAL_PROFILE_DEFAULTS.get(SOCIAL_PROFILE, SOCIAL_PROFILE_DEFAULTS["facebook"])

SOCIAL_SAFE_TOP = max(80, int(os.getenv("SOCIAL_SAFE_TOP", str(_safe_defaults["top"])) ))
SOCIAL_SAFE_BOTTOM = max(200, int(os.getenv("SOCIAL_SAFE_BOTTOM", str(_safe_defaults["bottom"])) ))
SOCIAL_SAFE_SIDE = max(24, int(os.getenv("SOCIAL_SAFE_SIDE", str(_safe_defaults["side"])) ))
SOCIAL_SAFE_RIGHT_GUTTER = max(120, int(os.getenv("SOCIAL_SAFE_RIGHT_GUTTER", str(_safe_defaults["right_gutter"])) ))

HARDCODED_AGENT_OFFICE_CITY: Dict[str, str] = {
    "matt forcum": "all",
    "cathrine craig": "sullivan",
    "catherine craig": "sullivan",
    "cathy craig": "sullivan",
    "debbie cruit": "shelbyville",
    "dbbie cruit": "shelbyville",
    "penny hood": "shelbyville",
    "amanda isley": "shelbyville",
    "amber jones": "shelbyville",
    "bruce steinke": "shelbyville",
    "sandy steinke": "shelbyville",
    "snady steinke": "shelbyville",
    "cassandra baumgarten": "effingham",
    "theresa nuxoll": "effingham",
    "sherree oliver": "effingham",
    "stephanie osborne": "effingham",
}

MATT_MULTI_OFFICE_LABEL = "Effingham | Shelbyville | Sullivan"

_AGENT_DIRECTORY_CACHE: Optional[Dict[str, Dict[str, str]]] = None
GENERATION_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_GENERATIONS)

GREATSCHOOLS_API_KEY = os.getenv("GREATSCHOOLS_API_KEY", "").strip()
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "").strip()

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in backend env")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI(title="Property Video Generator API")

# ============================================================================
# SCENE-BASED IMPORTS
# ============================================================================

from app.scenes import Scene, SceneType, MotionProfile, render_scene_frame, build_scene_list
from app.scenes.enrichment import enrich_listing_data


def _normalize_origin(origin: str) -> str:
    normalized = origin.strip()
    if not normalized:
        return ""
    return normalized.rstrip("/")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[_normalize_origin(x) for x in FRONTEND_ORIGINS.split(",") if _normalize_origin(x)],
    allow_origin_regex=FRONTEND_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    url: HttpUrl
    include_music: bool = False
    template: str = "new_listing"


def _normalize_template(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in FRAME_TEMPLATES else "new_listing"


def _set_job_progress(job_id: str, value: int) -> None:
    bounded = max(0, min(100, int(value)))
    with JOB_PROGRESS_LOCK:
        existing = JOB_PROGRESS.get(job_id, 0)
        JOB_PROGRESS[job_id] = max(existing, bounded)


def _get_job_progress(job_id: str, status: str) -> int:
    with JOB_PROGRESS_LOCK:
        current = JOB_PROGRESS.get(job_id, 0)
    status_value = (status or "").lower()
    if status_value == "completed":
        return 100
    if status_value == "failed":
        return max(0, current)
    if status_value in {"processing", "pending"}:
        return max(5, min(99, current))
    return max(0, current)


def update_job(
    job_id: str,
    status: str,
    download_url: Optional[str] = None,
    error_message: Optional[str] = None,
    branding: Optional[Dict[str, str]] = None,
) -> None:
    payload: Dict[str, Any] = {"status": status}
    if download_url is not None:
        payload["download_url"] = download_url
    if error_message is not None:
        payload["error_message"] = error_message[:1000]
    if branding:
        payload.update(
            {
                "agent_name": branding.get("agent_name"),
                "agent_phone": branding.get("agent_phone"),
                "agent_email": branding.get("agent_email"),
                "agent_photo_url": branding.get("agent_photo_url"),
                "broker_name": branding.get("broker_name"),
                "broker_phone": branding.get("broker_phone"),
                "broker_logo_url": branding.get("broker_logo_url"),
                "office_address": branding.get("office_address"),
            }
        )

    branding_keys = {
        "agent_name",
        "agent_phone",
        "agent_email",
        "agent_photo_url",
        "broker_name",
        "broker_phone",
        "broker_logo_url",
        "office_address",
    }

    payload_variants: List[Dict[str, Any]] = [payload]
    if branding:
        payload_variants.append({k: v for k, v in payload.items() if k not in branding_keys})
    if "error_message" in payload:
        payload_variants.append({k: v for k, v in payload.items() if k != "error_message" and k not in branding_keys})
    payload_variants.append({"status": status, "download_url": download_url})
    payload_variants.append({"status": status})

    last_error: Optional[Exception] = None
    seen = set()
    for candidate in payload_variants:
        normalized = tuple(sorted(candidate.items()))
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            supabase.table("videos").update(candidate).eq("id", job_id).execute()
            return
        except Exception as error:
            last_error = error
            if any(k in candidate for k in branding_keys):
                logger.warning("Branding update failed for job %s with payload keys %s: %s", job_id, list(candidate.keys()), error)

    if last_error:
        raise last_error


def _parse_utc_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _mark_job_stale_if_needed(job_id: str, job_data: Dict[str, Any]) -> Dict[str, Any]:
    status = str(job_data.get("status") or "").lower()
    if status not in {"pending", "processing"}:
        return job_data

    updated_at = _parse_utc_datetime(job_data.get("updated_at"))
    if updated_at is None:
        return job_data

    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds <= STALE_JOB_SECONDS:
        return job_data

    stale_message = (
        f"processing_timeout: job exceeded {STALE_JOB_SECONDS}s without progress; "
        "likely interrupted by worker restart or platform recycle"
    )
    try:
        update_job(job_id, "failed", None, stale_message)
        job_data["status"] = "failed"
        job_data["error_message"] = stale_message
    except Exception as error:
        logger.warning("Failed to mark stale job %s as failed: %s", job_id, error)

    return job_data


def _first_present(mapping: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _extract_http_url(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value if value.startswith("http") else None
    if isinstance(value, dict):
        for key in ["url", "original", "large", "medium", "small", "src"]:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith("http"):
                return candidate
    return None


def _extract_email(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
    if not match:
        return None
    return match.group(0)


def _extract_phone(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    match = re.search(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", value)
    if not match:
        return None
    return match.group(0)


def _extract_zip(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
    return match.group(0) if match else ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_person_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", value.strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _split_name_tokens(value: str) -> List[str]:
    normalized = _normalize_person_name(value)
    return [token for token in normalized.split(" ") if token]


def _matches_first_last_name(input_name: str, candidate_name: str) -> bool:
    input_tokens = _split_name_tokens(input_name)
    candidate_tokens = _split_name_tokens(candidate_name)
    if len(input_tokens) < 2 or len(candidate_tokens) < 2:
        return False
    return input_tokens[0] == candidate_tokens[0] and input_tokens[-1] == candidate_tokens[-1]


def _find_agent_directory_profile(agent_name: str, directory: Dict[str, Dict[str, str]]) -> Optional[Dict[str, str]]:
    normalized = _normalize_person_name(agent_name)
    exact = directory.get(normalized)
    if exact:
        return exact

    # Tolerate omitted middle names: "Theresa Nuxoll" should match "Theresa Ann Nuxoll".
    for key, profile in directory.items():
        if _matches_first_last_name(normalized, key):
            return profile

    return None


def _find_agent_profile_by_name(agent_profiles: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    if not agent_name or not isinstance(agent_profiles, dict):
        return {}

    normalized_target = _normalize_person_name(agent_name)
    if not normalized_target:
        return {}

    first_last_fallback: Dict[str, Any] = {}
    for profile in agent_profiles.values():
        if not isinstance(profile, dict):
            continue

        profile_name = _first_present(profile, ["name", "fullName", "fname"])
        if not profile_name:
            continue

        normalized_profile_name = _normalize_person_name(str(profile_name))
        if normalized_profile_name == normalized_target:
            return profile

        if not first_last_fallback and _matches_first_last_name(normalized_target, normalized_profile_name):
            first_last_fallback = profile

    return first_last_fallback


def _load_agent_directory() -> Dict[str, Dict[str, str]]:
    global _AGENT_DIRECTORY_CACHE
    if _AGENT_DIRECTORY_CACHE is not None:
        return _AGENT_DIRECTORY_CACHE

    if not AGENT_DIRECTORY_PATH.exists():
        _AGENT_DIRECTORY_CACHE = {}
        return _AGENT_DIRECTORY_CACHE

    try:
        raw = json.loads(AGENT_DIRECTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Agent directory must be a JSON list")

        directory: Dict[str, Dict[str, str]] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue

            canonical_name = str(entry.get("agent_name") or "").strip()
            if not canonical_name:
                continue

            normalized_names = {_normalize_person_name(canonical_name)}
            aliases = entry.get("aliases")
            if isinstance(aliases, list):
                for alias in aliases:
                    if isinstance(alias, str) and alias.strip():
                        normalized_names.add(_normalize_person_name(alias))

            profile = {
                "agent_name": canonical_name,
                "agent_phone": str(entry.get("agent_phone") or "").strip(),
                "agent_email": str(entry.get("agent_email") or "").strip(),
                "agent_photo_url": str(entry.get("agent_photo_url") or "").strip(),
                "agent_city": str(entry.get("agent_city") or "").strip(),
                "agent_state": str(entry.get("agent_state") or "").strip(),
                "broker_name": str(entry.get("broker_name") or "").strip(),
                "broker_phone": str(entry.get("broker_phone") or "").strip(),
                "broker_toll_free": str(entry.get("broker_toll_free") or "").strip(),
                "broker_logo_url": str(entry.get("broker_logo_url") or "").strip(),
                "office_address": str(entry.get("office_address") or "").strip(),
            }

            for normalized in normalized_names:
                if normalized:
                    directory[normalized] = profile

        _AGENT_DIRECTORY_CACHE = directory
        logger.info("Loaded %s agent directory entries from %s", len(directory), AGENT_DIRECTORY_PATH)
        return _AGENT_DIRECTORY_CACHE
    except Exception as error:
        logger.warning("Failed loading agent directory from %s: %s", AGENT_DIRECTORY_PATH, error)
        _AGENT_DIRECTORY_CACHE = {}
        return _AGENT_DIRECTORY_CACHE


def _apply_agent_directory_fallback(branding: Dict[str, str]) -> Dict[str, str]:
    agent_name = str(branding.get("agent_name") or "").strip()
    if not agent_name:
        return branding

    directory = _load_agent_directory()
    if not directory:
        return branding

    profile = _find_agent_directory_profile(agent_name, directory)
    if not profile:
        return branding

    merged = {key: _clean_text(value) for key, value in branding.items()}

    canonical_agent_keys = [
        "agent_phone",
        "agent_email",
        "agent_photo_url",
    ]
    for key in canonical_agent_keys:
        profile_value = _clean_text(profile.get(key))
        if profile_value:
            merged[key] = profile_value

    for key in [
        "agent_city",
        "agent_state",
        "broker_name",
        "broker_phone",
        "broker_toll_free",
        "broker_logo_url",
        "office_address",
    ]:
        current_value = _clean_text(merged.get(key))
        profile_value = _clean_text(profile.get(key))
        if not profile_value:
            continue

        if not current_value:
            merged[key] = profile_value
            continue

        if key == "office_address" and len(profile_value) > len(current_value) + 6:
            if profile_value.lower().startswith(current_value.lower()):
                merged[key] = profile_value

    if merged.get("broker_phone"):
        normalized_broker_phone = _extract_phone(merged.get("broker_phone"))
        merged["broker_phone"] = normalized_broker_phone or _clean_text(merged.get("broker_phone"))
    if merged.get("broker_toll_free"):
        normalized_toll_free = _extract_phone(merged.get("broker_toll_free"))
        merged["broker_toll_free"] = normalized_toll_free or _clean_text(merged.get("broker_toll_free"))
    if merged.get("agent_phone"):
        normalized_agent_phone = _extract_phone(merged.get("agent_phone"))
        merged["agent_phone"] = normalized_agent_phone or _clean_text(merged.get("agent_phone"))

    merged = _apply_hardcoded_office_relationships(merged)

    logger.info("Applied static agent directory fallback for agent '%s'", agent_name)
    return merged


def _extract_office_city_state(office_address: str) -> Tuple[str, str]:
    text = (office_address or "").strip()
    if not text:
        return "", ""

    match = re.search(r",\s*([A-Za-z .'-]+),\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", text)
    if match:
        city = match.group(1).strip()
        state = match.group(2).strip()
        return city, state

    state_match = re.search(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\s*$", text)
    inferred_state = state_match.group(1).strip() if state_match else ""

    for known_city in OFFICE_ADDRESS_BY_CITY.keys():
        if re.search(rf"\b{re.escape(known_city)}\b", text, flags=re.IGNORECASE):
            return known_city.title(), inferred_state or "IL"

    fallback_match = re.search(r"\b([A-Za-z][A-Za-z.'-]*)\s+([A-Z]{2})\s+\d{5}(?:-\d{4})?\s*$", text)
    if fallback_match:
        city = fallback_match.group(1).strip()
        state = fallback_match.group(2).strip()
        return city, state

    return "", ""


def _apply_hardcoded_office_relationships(branding: Dict[str, str]) -> Dict[str, str]:
    merged = {key: _clean_text(value) for key, value in branding.items()}
    normalized_name = _normalize_person_name(merged.get("agent_name", ""))
    office_key = HARDCODED_AGENT_OFFICE_CITY.get(normalized_name)
    if not office_key:
        return merged

    if office_key == "all":
        merged["office_address"] = MATT_MULTI_OFFICE_LABEL
        merged["agent_city"] = MATT_MULTI_OFFICE_LABEL
        merged["agent_state"] = "IL"
        merged["broker_phone"] = ""
        if not merged.get("broker_toll_free"):
            merged["broker_toll_free"] = TOLL_FREE_PHONE
        return merged

    office_address = OFFICE_ADDRESS_BY_CITY.get(office_key, "")
    office_phone = OFFICE_PHONE_BY_CITY.get(office_key, "")
    if office_address:
        merged["office_address"] = office_address
    if office_phone:
        merged["broker_phone"] = office_phone
    merged["agent_city"] = office_key.title()
    merged["agent_state"] = "IL"
    if not merged.get("broker_toll_free"):
        merged["broker_toll_free"] = TOLL_FREE_PHONE
    return merged


def _format_price(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"${int(value):,}"
    if isinstance(value, str) and value.strip():
        cleaned = value.strip()
        if cleaned.startswith("$"):
            return cleaned
        if cleaned.replace(",", "").isdigit():
            return f"${int(cleaned.replace(',', '')):,}"
        return cleaned
    return "Contact for Price"


def _extract_shelby_idx_listing(url: str, html: str) -> Optional[Tuple[str, str, List[str], Dict[str, str]]]:
    if "shelbyrealty.com" not in url or "/idx/listing/" not in url:
        return None

    state_match = re.search(r"__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
    if not state_match:
        return None

    state = json.loads(state_match.group(1))
    listings = state.get("listings") or {}
    if not isinstance(listings, dict) or not listings:
        return None

    listing_key_match = re.search(r"/idx/listing/([^/]+)/([^/]+)(?:/|$)", url)
    listing = None
    if listing_key_match:
        mls_id = listing_key_match.group(1)
        mls_no = listing_key_match.group(2)
        listing = listings.get(f"{mls_id}-{mls_no}")
    if listing is None:
        listing = next(iter(listings.values()))

    if not isinstance(listing, dict):
        return None

    street = (listing.get("streetAddress") or "").strip()
    city = (listing.get("city") or "").strip()
    state_code = (listing.get("state") or "").strip()
    postal = (listing.get("zip") or "").strip()
    address = " ".join([x for x in [street, city, state_code, postal] if x]).strip() or "Property Listing"

    price = _format_price(listing.get("price"))

    mls_id = (listing.get("mlsId") or "").strip()
    mls_no = str(listing.get("mlsNo") or "").strip()
    photo_codes = [str(code).strip() for code in (listing.get("photos") or []) if str(code).strip()]

    version = ""
    photos_date = str(listing.get("photosDate") or "").strip()
    if photos_date:
        version = photos_date.replace(" ", "_").replace(":", "")

    image_urls: List[str] = []
    if mls_id and mls_no and photo_codes:
        base = f"https://idx-photos-ihouseprd.b-cdn.net/{mls_id}/{mls_no}/org"
        for code in photo_codes:
            img_url = f"{base}/{code}.jpg"
            if version:
                img_url = f"{img_url}?v={version}&width=1280&height=960"
            image_urls.append(img_url)

    if not image_urls:
        return None

    agent_profiles = ((state.get("agentProfiles") or {}).get("byId") or {})
    listed_by = listing.get("listedBy") or {}
    agent_record: Dict[str, Any] = {}
    listed_agent: Dict[str, Any] = listed_by.get("agent") if isinstance(listed_by, dict) else {}
    listed_broker: Dict[str, Any] = listed_by.get("broker") if isinstance(listed_by, dict) else {}

    if isinstance(agent_profiles, dict):
        candidate_ids: List[str] = []
        if isinstance(listed_agent, dict):
            for key in ["id", "agentId", "profileId", "code"]:
                value = listed_agent.get(key)
                if value not in (None, ""):
                    candidate_ids.append(str(value))
        elif isinstance(listed_by, list):
            candidate_ids.extend([str(raw_id) for raw_id in listed_by])

        for str_id in candidate_ids:
            if str_id in agent_profiles and isinstance(agent_profiles[str_id], dict):
                agent_record = agent_profiles[str_id]
                break

    listed_agent_name_hint = _first_present(listed_agent, ["name", "fullName"]) if isinstance(listed_agent, dict) else ""
    if not listed_agent_name_hint:
        listed_agent_name_hint = _first_present(listing, ["listedByName", "listingAgent", "listingAgentName", "agentName"])

    if not agent_record and listed_agent_name_hint:
        agent_record = _find_agent_profile_by_name(agent_profiles, str(listed_agent_name_hint))

    website_settings = state.get("websiteSettings") if isinstance(state.get("websiteSettings"), dict) else {}

    contact_info = _first_present(agent_record, ["contactInfo", "miscInfo"])

    agent_name = _first_present(listed_agent, ["name", "fullName"])
    if not agent_name:
        agent_name = _first_present(agent_record, ["name", "fullName", "fname"])

    agent_phone = _first_present(listed_agent, ["phone", "mobile", "cell", "cellPhone"])
    if not agent_phone:
        agent_phone = _first_present(agent_record, ["phone", "cellPhone", "mobilePhone"])
    if not agent_phone:
        agent_phone = _extract_phone(contact_info)

    agent_email = _first_present(listed_agent, ["email"])
    if not agent_email:
        agent_email = _first_present(agent_record, ["email"])
    if not agent_email:
        agent_email = _extract_email(contact_info)

    agent_photo_url = _extract_http_url(_first_present(agent_record, ["photo", "headshot", "image"]))

    broker_name = _first_present(listed_broker, ["name", "brokerName", "companyName"])
    if not broker_name:
        broker_name = _first_present(website_settings, ["companyName", "brokerName", "brokerageName", "name"])

    broker_phone = _first_present(listed_broker, ["phone", "officePhone", "contactPhone"])
    if not broker_phone:
        broker_phone = _first_present(website_settings, ["companyPhone", "phone", "officePhone", "contactPhone"])

    broker_logo_url = _extract_http_url(
        _first_present(website_settings, ["logo", "logoUrl", "brandLogo", "headerLogo"])
    )

    office_address_parts = [
        _first_present(website_settings, ["officeAddress", "address", "streetAddress"]),
        website_settings.get("city"),
        website_settings.get("state"),
        website_settings.get("zip"),
    ]
    office_address = " ".join([str(part).strip() for part in office_address_parts if str(part).strip()])

    listing_city_key = city.lower().strip()
    location_office_phone = OFFICE_PHONE_BY_CITY.get(listing_city_key)
    location_office_address = OFFICE_ADDRESS_BY_CITY.get(listing_city_key)

    toll_free_phone = _extract_phone(_first_present(listed_broker, ["phone", "officePhone", "contactPhone"]))
    if not toll_free_phone:
        toll_free_phone = _extract_phone(_first_present(website_settings, ["companyPhone", "phone", "officePhone", "contactPhone"]))
    if not toll_free_phone:
        toll_free_phone = TOLL_FREE_PHONE

    if location_office_phone:
        broker_phone = location_office_phone
    if location_office_address:
        office_address = location_office_address

    logger.info(
        "Shelby scrape: photos=%s branding(agent=%s, agent_phone=%s, agent_email=%s, broker=%s, broker_phone=%s)",
        len(image_urls),
        bool(agent_name),
        bool(agent_phone),
        bool(agent_email),
        bool(broker_name),
        bool(broker_phone),
    )

    normalized_agent_phone = _extract_phone(agent_phone) if agent_phone else None
    normalized_broker_phone = _extract_phone(broker_phone) if broker_phone else None

    branding = {
        "agent_name": _clean_text(agent_name),
        "agent_phone": _clean_text(normalized_agent_phone or agent_phone),
        "agent_email": _clean_text(agent_email),
        "agent_photo_url": _clean_text(agent_photo_url),
        "agent_city": _clean_text(city),
        "agent_state": _clean_text(state_code),
        "broker_name": _clean_text(broker_name),
        "broker_phone": _clean_text(normalized_broker_phone or broker_phone),
        "broker_toll_free": _clean_text(toll_free_phone),
        "broker_logo_url": _clean_text(broker_logo_url),
        "office_address": _clean_text(office_address),
    }

    branding = _apply_agent_directory_fallback(branding)

    return address, price, image_urls, branding


def scrape_listing(url: str) -> Tuple[str, str, List[str], Dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    html = response.text

    shelby_data = _extract_shelby_idx_listing(url, html)
    if shelby_data:
        return shelby_data

    soup = BeautifulSoup(html, "html.parser")

    address = "Property Listing"[:100]
    og_title = soup.find("meta", {"property": "og:title"})
    if og_title and og_title.get("content"):
        address = og_title["content"].strip()
    elif soup.title and soup.title.string:
        address = soup.title.string.strip()

    txt = soup.get_text(" ", strip=True)
    price_match = re.search(r"\$\s?[0-9][0-9,]*(?:\.[0-9]{2})?", txt)
    price = price_match.group(0).replace(" ", "") if price_match else "Contact for Price"

    images: List[str] = []
    og_image = soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        images.append(og_image["content"])

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http"):
            images.append(src)

    seen = set()
    unique = []
    for image_url in images:
        if image_url not in seen:
            seen.add(image_url)
            unique.append(image_url)

    if not unique:
        raise ValueError("No images found")
    branding = _apply_agent_directory_fallback({
        "agent_name": "",
        "agent_phone": "",
        "agent_email": "",
        "agent_photo_url": "",
        "agent_city": "",
        "agent_state": "",
        "broker_name": "",
        "broker_phone": "",
        "broker_toll_free": TOLL_FREE_PHONE,
        "broker_logo_url": "",
        "office_address": "",
    })
    return address, price, unique, branding


def download_image(url: str, out_path: Path) -> None:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    response.raise_for_status()
    out_path.write_bytes(response.content)


def upload_video_to_supabase(storage_path: str, video_bytes: bytes) -> None:
    if not video_bytes:
        raise RuntimeError("Video render produced an empty file")

    escaped_path = quote(storage_path, safe="/")
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{escaped_path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "content-type": "video/mp4",
        "x-upsert": "true",
    }

    transient_status_codes = {408, 425, 429, 500, 502, 503, 504}
    methods = ("post", "put")

    last_error: Optional[Exception] = None
    for attempt in range(1, 5):
        for method in methods:
            try:
                response = requests.request(
                    method,
                    upload_url,
                    data=video_bytes,
                    headers=headers,
                    timeout=(20, 240),
                )
                if response.status_code in (200, 201):
                    return

                response_text = (response.text or "")[:400]
                response_text_lower = response_text.lower()
                is_transient = (
                    response.status_code in transient_status_codes
                    or (response.status_code == 400 and "<html" in response_text_lower)
                )

                error = RuntimeError(
                    f"Supabase upload failed ({response.status_code}): {response_text}"
                )
                last_error = error

                if not is_transient:
                    raise error
            except Exception as error:
                last_error = error
                message = str(error)
                is_transient = (
                    "SSLWantWriteError" in message
                    or "WriteError" in message
                    or "timed out" in message.lower()
                    or "connection" in message.lower()
                )
                if not is_transient:
                    raise

        if attempt < 4:
            time.sleep(attempt * 2)

    if last_error:
        raise last_error


def crop_9_16(img: Image.Image) -> Image.Image:
    source = img.convert("RGB")
    source_width, source_height = source.size

    cover_scale = max(REEL_PHOTO_WIDTH / source_width, REEL_PHOTO_HEIGHT / source_height)
    scaled_width = int(source_width * cover_scale)
    scaled_height = int(source_height * cover_scale)
    scaled = source.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

    left = max(0, (scaled_width - REEL_PHOTO_WIDTH) // 2)
    top = max(0, (scaled_height - REEL_PHOTO_HEIGHT) // 2)
    cropped = scaled.crop((left, top, left + REEL_PHOTO_WIDTH, top + REEL_PHOTO_HEIGHT))
    return cropped.convert("RGB")


@lru_cache(maxsize=64)
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    asset_font_candidates = []
    if bold:
        asset_font_candidates.extend(
            [
                ASSETS_DIR / "fonts" / "Montserrat-Bold.ttf",
                ASSETS_DIR / "fonts" / "Inter-Bold.ttf",
            ]
        )
    asset_font_candidates.extend(
        [
            ASSETS_DIR / "fonts" / "Montserrat-Regular.ttf",
            ASSETS_DIR / "fonts" / "Inter-Regular.ttf",
        ]
    )

    system_font_candidates: List[str] = []
    if bold:
        system_font_candidates.extend(
            [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "DejaVuSans-Bold.ttf",
                "Arial Bold.ttf",
            ]
        )
    system_font_candidates.extend(
        [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "DejaVuSans.ttf",
            "Arial.ttf",
        ]
    )

    for font_path in asset_font_candidates:
        try:
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            continue

    for font_name_or_path in system_font_candidates:
        try:
            return ImageFont.truetype(font_name_or_path, size=size)
        except Exception:
            continue

    logger.warning("Falling back to default bitmap font; no TrueType font found for size=%s bold=%s", size, bold)
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
    append_ellipsis: bool = True,
) -> List[str]:
    words = [w for w in text.split() if w]
    if not words:
        return []

    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        trial_width = draw.textbbox((0, 0), trial, font=font)[2]
        if trial_width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break
    lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines and append_ellipsis:
        while draw.textbbox((0, 0), lines[-1], font=font)[2] > max_width and len(lines[-1]) > 1:
            lines[-1] = lines[-1][:-1]
        if not lines[-1].endswith("…"):
            lines[-1] = lines[-1].rstrip(" .,") + "…"
    return lines


def _load_remote_overlay_image(url: str, max_size: Tuple[int, int]) -> Optional[Image.Image]:
    if not url or not url.startswith("http"):
        return None
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        from io import BytesIO
        image = Image.open(BytesIO(response.content)).convert("RGBA")
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        return image
    except Exception:
        return None


def _prepare_branding_assets(branding: Dict[str, str]) -> Dict[str, Optional[Image.Image]]:
    assets: Dict[str, Optional[Image.Image]] = {
        "agent_photo": None,
        "broker_logo": None,
    }

    assets["agent_photo"] = _load_remote_overlay_image(
        branding.get("agent_photo_url", ""),
        (180, 180),
    )

    broker_logo = _load_remote_overlay_image(
        branding.get("broker_logo_url", ""),
        (320, 140),
    )
    if broker_logo is None and LOGO_PATH.exists():
        try:
            broker_logo = Image.open(LOGO_PATH).convert("RGBA")
            broker_logo.thumbnail((320, 140), Image.Resampling.LANCZOS)
        except Exception:
            broker_logo = None
    assets["broker_logo"] = broker_logo

    return assets


def _draw_template_frame(base: Image.Image, template: str) -> None:
    template_key = _normalize_template(template)
    style = FRAME_TEMPLATES[template_key]

    draw = ImageDraw.Draw(base)
    width, height = base.size
    frame_padding = 16
    safe_left = frame_padding
    safe_right = width - frame_padding

    outer_rect = (
        frame_padding,
        frame_padding,
        width - frame_padding - 1,
        height - frame_padding - 1,
    )
    inner_rect = (
        outer_rect[0] + 16,
        outer_rect[1] + 16,
        outer_rect[2] - 16,
        outer_rect[3] - 16,
    )

    draw.rounded_rectangle(outer_rect, radius=32, outline=style["primary"], width=10)
    draw.rounded_rectangle(inner_rect, radius=26, outline=style["secondary"], width=3)

    label = style["label"]
    label_font = _load_font(40, bold=True)
    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_width = label_bbox[2]
    label_height = label_bbox[3]
    chip_padding_x = 26
    chip_padding_y = 10
    chip_width = label_width + (chip_padding_x * 2)
    chip_height = label_height + (chip_padding_y * 2)
    centered_chip_x = (safe_left + safe_right - chip_width) // 2
    chip_x = max(safe_left + 12, min(centered_chip_x, safe_right - chip_width - 12))
    chip_y = 52

    draw.rounded_rectangle(
        (chip_x, chip_y, chip_x + chip_width, chip_y + chip_height),
        radius=22,
        fill=style["chip_fill"],
        outline=style["secondary"],
        width=2,
    )
    draw.text(
        (chip_x + chip_padding_x, chip_y + chip_padding_y),
        label,
        fill=(255, 255, 255, 255),
        font=label_font,
        stroke_width=2,
        stroke_fill=(0, 0, 0, 220),
    )


def draw_overlay_layer(
    width: int,
    height: int,
    address: str,
    price: str,
    template: str = "new_listing",
    branding: Optional[Dict[str, str]] = None,
    branding_assets: Optional[Dict[str, Optional[Image.Image]]] = None,
) -> Image.Image:
    base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    branding = branding or {}
    branding_assets = branding_assets or {}

    gradient_height = 500
    alpha = Image.new("L", (1, gradient_height))
    for y in range(gradient_height):
        alpha.putpixel((0, y), int(220 * (y / gradient_height)))
    alpha = alpha.resize((width, gradient_height))

    black = Image.new("RGBA", (width, gradient_height), (0, 0, 0, 0))
    black.putalpha(alpha)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.paste(black, (0, height - gradient_height), black)
    base.alpha_composite(layer)
    _draw_template_frame(base, template)

    draw = ImageDraw.Draw(base)
    panel_left = REEL_CARD_LEFT
    panel_right = REEL_CARD_RIGHT
    panel_top = REEL_CARD_TOP
    panel_bottom = REEL_CARD_BOTTOM
    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        radius=28,
        fill=(0, 0, 0, 220),
    )

    font_address = _load_font(50, bold=True)
    font_price = _load_font(72, bold=True)
    font_brand_heading = _load_font(34, bold=True)
    font_brand_text = _load_font(28, bold=False)

    text_x = panel_left + 34
    agent_photo = branding_assets.get("agent_photo")
    if agent_photo is not None:
        floating_photo = agent_photo.copy()
        floating_photo.thumbnail((190, 190), Image.Resampling.LANCZOS)
        px = panel_left + 24
        py = panel_top - (floating_photo.height // 2)
        frame = Image.new("RGBA", (floating_photo.width + 16, floating_photo.height + 16), (0, 0, 0, 0))
        frame_draw = ImageDraw.Draw(frame)
        frame_draw.rounded_rectangle((0, 0, frame.width - 1, frame.height - 1), radius=12, fill=(255, 255, 255, 235))
        base.alpha_composite(frame, (px - 8, py - 8))
        base.alpha_composite(floating_photo, (px, py))
        text_x = px + floating_photo.width + 24

    max_text_width = max(220, panel_right - text_x - 26)
    address_lines = _wrap_text(draw, address, font_address, max_text_width, max_lines=2, append_ellipsis=False)

    text_y = panel_top + 24
    for line in address_lines:
        draw.text(
            (text_x, text_y),
            line,
            fill=(255, 255, 255, 255),
            font=font_address,
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )
        text_y += 54

    agent_name = (branding.get("agent_name") or "").strip()
    agent_phone = (branding.get("agent_phone") or "").strip()
    broker_name = (branding.get("broker_name") or "").strip()
    broker_phone = (branding.get("broker_phone") or "").strip()
    broker_toll_free = (branding.get("broker_toll_free") or "").strip()

    price_text = price
    price_height = draw.textbbox((0, 0), price_text, font=font_price)[3]
    text_limit_y = panel_bottom - price_height - 24

    def _draw_wrapped(text_value: str, font_obj: ImageFont.ImageFont, fill: Tuple[int, int, int, int], spacing: int) -> bool:
        nonlocal text_y
        if not text_value:
            return True
        lines = _wrap_text(draw, text_value, font_obj, max_text_width, max_lines=2, append_ellipsis=False)
        for line in lines:
            line_height = draw.textbbox((0, 0), line, font=font_obj)[3]
            if text_y + line_height > text_limit_y:
                return False
            draw.text(
                (text_x, text_y),
                line,
                fill=fill,
                font=font_obj,
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255),
            )
            text_y += line_height + spacing
        return True

    if agent_name:
        _draw_wrapped(f"Agent: {agent_name}", font_brand_heading, (255, 255, 255, 255), 10)
    if agent_phone:
        _draw_wrapped(f"Call/Text: {agent_phone}", font_brand_text, (235, 235, 235, 255), 8)
    if broker_name:
        broker_line = broker_name if not broker_phone else f"{broker_name} {broker_phone}"
        _draw_wrapped(broker_line, font_brand_text, (235, 235, 235, 255), 8)

    if broker_toll_free:
        small_font = _load_font(26, bold=False)
        _draw_wrapped(f"Toll-Free: {broker_toll_free}", small_font, (220, 220, 220, 255), 6)

    draw.text(
        (text_x, panel_bottom - price_height - 10),
        price_text,
        fill=(255, 255, 255, 255),
        font=font_price,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )

    broker_logo = branding_assets.get("broker_logo")
    if broker_logo is not None:
        broker_logo = broker_logo.copy()
        broker_logo.thumbnail((340, 130), Image.Resampling.LANCZOS)
        frame_padding = 16
        broker_x = min(width - frame_padding - broker_logo.width, panel_right - broker_logo.width)
        broker_y = 148
        base.alpha_composite(broker_logo, (broker_x, broker_y))

    return base


def draw_overlay(
    img: Image.Image,
    address: str,
    price: str,
    template: str = "new_listing",
    branding: Optional[Dict[str, str]] = None,
    branding_assets: Optional[Dict[str, Optional[Image.Image]]] = None,
) -> Image.Image:
    base = img.convert("RGBA")
    width, height = base.size
    overlay_layer = draw_overlay_layer(
        width,
        height,
        address,
        price,
        template=template,
        branding=branding,
        branding_assets=branding_assets,
    )
    base.alpha_composite(overlay_layer)

    return base.convert("RGB")


def draw_outro_frame(
    address: str,
    price: str,
    branding: Dict[str, str],
    template: str = "new_listing",
    branding_assets: Optional[Dict[str, Optional[Image.Image]]] = None,
) -> Image.Image:
    branding_assets = branding_assets or {}
    width, height = 1080, 1920
    canvas = Image.new("RGBA", (width, height), (14, 16, 20, 255))

    gradient = Image.new("L", (1, height))
    for y in range(height):
        gradient.putpixel((0, y), int(180 * (y / height)))
    gradient = gradient.resize((width, height))
    top_tint = Image.new("RGBA", (width, height), (24, 32, 48, 180))
    top_tint.putalpha(gradient)
    canvas.alpha_composite(top_tint)
    _draw_template_frame(canvas, template)

    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(58, bold=True)
    subtitle_font = _load_font(48, bold=True)
    body_font = _load_font(38, bold=False)
    small_font = _load_font(32, bold=False)

    title_rect = (REEL_MARGIN_X, 220, REEL_WIDTH - REEL_MARGIN_X, 340)
    contact_rect = (REEL_MARGIN_X, 380, REEL_WIDTH - REEL_MARGIN_X, 1180)
    listing_rect = (REEL_MARGIN_X, 1240, REEL_WIDTH - REEL_MARGIN_X, 1728)
    display_address = (address or "").strip()
    if not _extract_zip(display_address):
        fallback_zip = _extract_zip((branding.get("office_address") or "").strip())
        if fallback_zip:
            display_address = f"{display_address} {fallback_zip}".strip()

    broker_logo = branding_assets.get("broker_logo")
    logo_bottom = 0
    if broker_logo is not None:
        logo = broker_logo.copy()
        logo.thumbnail((360, 130), Image.Resampling.LANCZOS)
        logo_x = REEL_WIDTH - REEL_MARGIN_X - logo.width
        logo_y = 144
        chip = (logo_x - 12, logo_y - 8, logo_x + logo.width + 12, logo_y + logo.height + 8)
        draw.rounded_rectangle(chip, radius=14, fill=(255, 255, 255, 210))
        canvas.alpha_composite(logo, (logo_x, logo_y))
        logo_bottom = logo_y + logo.height

    title = "Contact Listing Agent"
    title_y = max(title_rect[1], logo_bottom + 26)
    draw.text((title_rect[0], title_y), title, fill=(255, 255, 255, 255), font=title_font, stroke_width=2, stroke_fill=(0, 0, 0, 255))

    draw.rounded_rectangle(contact_rect, radius=30, fill=(0, 0, 0, 205))

    text_x = contact_rect[0] + 26
    text_y = contact_rect[1] + 28
    agent_photo = branding_assets.get("agent_photo")
    if agent_photo is not None:
        photo = agent_photo.copy()
        photo.thumbnail((132, 132), Image.Resampling.LANCZOS)
        photo_x = contact_rect[0] + 26
        photo_y = contact_rect[1] + 24
        photo_frame = Image.new("RGBA", (photo.width + 14, photo.height + 14), (0, 0, 0, 0))
        photo_frame_draw = ImageDraw.Draw(photo_frame)
        photo_frame_draw.rounded_rectangle((0, 0, photo_frame.width - 1, photo_frame.height - 1), radius=10, fill=(255, 255, 255, 225))
        canvas.alpha_composite(photo_frame, (photo_x - 7, photo_y - 7))
        canvas.alpha_composite(photo, (photo_x, photo_y))
        text_x = photo_x + photo.width + 24

    max_text_width = contact_rect[2] - text_x - 26
    contact_blocks: List[Tuple[ImageFont.ImageFont, Tuple[int, int, int, int], int, List[str]]] = []

    def _collect(text_value: str, font_obj: ImageFont.ImageFont, color: Tuple[int, int, int, int], spacing: int, max_lines: int = 1) -> None:
        if not text_value:
            return
        lines = _wrap_text(draw, text_value, font_obj, max_text_width, max_lines=max_lines, append_ellipsis=False)
        if lines:
            contact_blocks.append((font_obj, color, spacing, lines))

    _collect((branding.get("agent_name") or "").strip() or "Your Listing Agent", subtitle_font, (255, 255, 255, 255), 12, max_lines=1)
    _collect(f"Call/Text: {(branding.get('agent_phone') or '').strip()}" if (branding.get("agent_phone") or "").strip() else "", body_font, (245, 245, 245, 255), 10)
    _collect((branding.get("agent_email") or "").strip(), body_font, (235, 235, 235, 255), 10)

    broker_line = (branding.get("broker_name") or "").strip()
    broker_phone = (branding.get("broker_phone") or "").strip()
    if broker_line and broker_phone:
        broker_line = f"{broker_line} {broker_phone}"
    _collect(broker_line, body_font, (235, 235, 235, 255), 10, max_lines=2)
    _collect(
        f"Toll-Free: {(branding.get('broker_toll_free') or '').strip()}" if (branding.get("broker_toll_free") or "").strip() else "",
        small_font,
        (220, 220, 220, 255),
        8,
    )
    _collect((branding.get("office_address") or "").strip(), small_font, (220, 220, 220, 255), 8, max_lines=2)

    total_height = 0
    for font_obj, _, spacing, lines in contact_blocks:
        for line in lines:
            total_height += draw.textbbox((0, 0), line, font=font_obj)[3] + spacing
    if total_height > 0:
        total_height -= contact_blocks[-1][2]

    line_y = max(contact_rect[1] + 22, contact_rect[1] + ((contact_rect[3] - contact_rect[1] - total_height) // 2))
    for font_obj, color, spacing, lines in contact_blocks:
        for line in lines:
            line_height = draw.textbbox((0, 0), line, font=font_obj)[3]
            if line_y + line_height > contact_rect[3] - 18:
                break
            draw.text((text_x, line_y), line, fill=color, font=font_obj, stroke_width=2, stroke_fill=(0, 0, 0, 255))
            line_y += line_height + spacing

    draw.rounded_rectangle(listing_rect, radius=30, fill=(0, 0, 0, 205))
    listing_text_width = listing_rect[2] - listing_rect[0] - 52
    listing_lines = _wrap_text(draw, display_address, subtitle_font, listing_text_width, max_lines=2, append_ellipsis=False)
    list_y = listing_rect[1] + 28
    for line in listing_lines:
        draw.text((listing_rect[0] + 26, list_y), line, fill=(255, 255, 255, 255), font=subtitle_font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        list_y += 58

    price_font = _load_font(72, bold=True)
    draw.text(
        (listing_rect[0] + 26, listing_rect[3] - 110),
        price,
        fill=(255, 255, 255, 255),
        font=price_font,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )

    return canvas.convert("RGB")


def build_video(
    scenes: List["Scene"],
    out_path: Path,
    overlay_frame: Optional[Path] = None,
    include_music: bool = True,
    motion_seed: str = "",
) -> None:
    """Build a video from a list of Scene objects.

    This is the scene-aware replacement for the flat-photo pipeline.  Instead of
    a flat list of photo paths, it accepts typed scenes.  Each scene knows its own
    duration, motion profile, and whether it carries its own overlay.

    Photo scenes (HERO_PHOTO, INTERIOR_PHOTO) still get the global overlay
    composited on top.  Data-card scenes (STATS_CARD, etc.) have
    has_own_overlay=True and skip the global overlay step.
    """
    max_video_seconds = 150.0
    transition_duration = min(REEL_TRANSITION_SECONDS, 1.0)

    # Separate outro from content scenes
    content_scenes = [s for s in scenes if s.scene_type != SceneType.OUTRO]
    outro_scene = next((s for s in scenes if s.scene_type == SceneType.OUTRO), None)

    if not content_scenes and not outro_scene:
        raise ValueError("No scenes to render")

    # Cap total content length
    reserve_for_outro = outro_scene.duration if outro_scene else 0.0
    max_content = max_video_seconds - reserve_for_outro

    # Trim content scenes if total exceeds budget
    running = 0.0
    trimmed: List["Scene"] = []
    for sc in content_scenes:
        if running + sc.duration > max_content and trimmed:
            break
        trimmed.append(sc)
        running += sc.duration
    content_scenes = trimmed

    # Build FFmpeg stream for each content scene
    streams = []
    durations: List[float] = []
    transition_candidates = ["fade", "wipeleft", "wiperight", "slideleft", "slideright", "smoothleft", "smoothright"]

    def _rng_for_scene(index: int, scene: "Scene") -> random.Random:
        seed_value = f"{motion_seed}:scene:{index}:{scene.scene_type.value}"
        if scene.frame_path:
            seed_value += f":{scene.frame_path.name}"
        seed_hash = hashlib.sha256(seed_value.encode("utf-8")).hexdigest()[:16]
        return random.Random(int(seed_hash, 16))

    def _ken_burns_expr(index: int, scene: "Scene") -> Tuple[str, str, str, int]:
        rng = _rng_for_scene(index, scene)
        frame_count = max(2, int(round(scene.duration * 30)))
        denominator = max(1, frame_count - 1)

        motion_type = rng.choice(["push_in", "push_out", "push_in", "pan_mix"])
        if motion_type == "push_out":
            z_start = rng.uniform(1.14, 1.22)
            z_end = rng.uniform(1.00, 1.06)
            z_step = max(0.00005, (z_start - z_end) / denominator)
            z_expr = f"if(lte(on,1),{z_start:.4f},max({z_end:.4f},zoom-{z_step:.6f}))"
        elif motion_type == "pan_mix":
            z_start = rng.uniform(1.06, 1.12)
            z_end = rng.uniform(1.14, 1.20)
            z_step = max(0.00005, (z_end - z_start) / denominator)
            z_expr = f"if(lte(on,1),{z_start:.4f},min({z_end:.4f},zoom+{z_step:.6f}))"
        else:
            z_start = rng.uniform(1.00, 1.06)
            z_end = rng.uniform(1.14, 1.22)
            z_step = max(0.00005, (z_end - z_start) / denominator)
            z_expr = f"if(lte(on,1),{z_start:.4f},min({z_end:.4f},zoom+{z_step:.6f}))"

        x_start = rng.uniform(0.20, 0.45)
        y_start = rng.uniform(0.20, 0.45)
        x_delta = rng.uniform(-0.14, 0.14)
        y_delta = rng.uniform(-0.10, 0.10)
        x_end = max(0.15, min(0.85, x_start + x_delta))
        y_end = max(0.15, min(0.85, y_start + y_delta))

        x_expr = f"(iw-iw/zoom)*({x_start:.4f}+({x_end - x_start:.4f})*on/{denominator})"
        y_expr = f"(ih-ih/zoom)*({y_start:.4f}+({y_end - y_start:.4f})*on/{denominator})"
        return z_expr, x_expr, y_expr, frame_count

    def _slow_zoom_expr(index: int, scene: "Scene") -> Tuple[str, str, str, int]:
        frame_count = max(2, int(round(scene.duration * 30)))
        denominator = max(1, frame_count - 1)
        z_expr = f"if(lte(on,1),1.0000,min(1.0800,zoom+{0.08 / denominator:.6f}))"
        x_expr = "(iw-iw/zoom)*0.5000"
        y_expr = "(ih-ih/zoom)*0.5000"
        return z_expr, x_expr, y_expr, frame_count

    for index, scene in enumerate(content_scenes):
        frame_path = scene.frame_path
        if frame_path is None:
            raise ValueError(f"Scene {index} ({scene.scene_type}) has no frame_path set")

        if scene.has_own_overlay:
            # Full-frame data card — render at full canvas size, static or slow zoom
            if scene.motion == MotionProfile.KEN_BURNS:
                z_expr, x_expr, y_expr, frame_count = _ken_burns_expr(index, scene)
                stream = (
                    ffmpeg
                    .input(str(frame_path), loop=1, t=scene.duration + 0.2)
                    .filter("zoompan", z=z_expr, x=x_expr, y=y_expr,
                            d=frame_count, s=f"{REEL_WIDTH}x{REEL_HEIGHT}", fps=30)
                    .filter("setsar", "1")
                    .filter("fps", 30)
                    .filter("trim", duration=scene.duration)
                    .filter("setpts", "PTS-STARTPTS")
                )
            elif scene.motion == MotionProfile.SLOW_ZOOM:
                z_expr, x_expr, y_expr, frame_count = _slow_zoom_expr(index, scene)
                stream = (
                    ffmpeg
                    .input(str(frame_path), loop=1, t=scene.duration + 0.2)
                    .filter("zoompan", z=z_expr, x=x_expr, y=y_expr,
                            d=frame_count, s=f"{REEL_WIDTH}x{REEL_HEIGHT}", fps=30)
                    .filter("setsar", "1")
                    .filter("fps", 30)
                    .filter("trim", duration=scene.duration)
                    .filter("setpts", "PTS-STARTPTS")
                )
            else:
                # STATIC — just scale and hold
                stream = (
                    ffmpeg
                    .input(str(frame_path), loop=1, t=scene.duration + 0.2)
                    .filter("scale", REEL_WIDTH, REEL_HEIGHT)
                    .filter("setsar", "1")
                    .filter("fps", 30)
                    .filter("trim", duration=scene.duration)
                    .filter("setpts", "PTS-STARTPTS")
                )
        else:
            # Photo scene — render at photo dimensions with Ken Burns,
            # then pad to full frame size so xfade dimensions match card scenes
            z_expr, x_expr, y_expr, frame_count = _ken_burns_expr(index, scene)
            stream = (
                ffmpeg
                .input(str(frame_path), loop=1, t=scene.duration + 0.2)
                .filter("zoompan", z=z_expr, x=x_expr, y=y_expr,
                        d=frame_count, s=f"{REEL_PHOTO_WIDTH}x{REEL_PHOTO_HEIGHT}", fps=30)
                .filter("setsar", "1")
                .filter("fps", 30)
                .filter("trim", duration=scene.duration)
                .filter("setpts", "PTS-STARTPTS")
                .filter("pad", REEL_WIDTH, REEL_HEIGHT, REEL_MARGIN_X, REEL_PHOTO_TOP, color="0x12141C")
            )

        streams.append(stream)
        durations.append(scene.duration)

    # Compose streams with xfade transitions
    if len(streams) == 1:
        video = streams[0]
        total = durations[0]
    else:
        video = streams[0]
        elapsed = durations[0]
        previous_transition = "fade"
        for i in range(1, len(streams)):
            offset = elapsed - transition_duration
            tr = content_scenes[i].transition
            if tr is None:
                tr_rng = _rng_for_scene(i, content_scenes[i])
                tr = tr_rng.choice(transition_candidates)
                if tr == previous_transition:
                    tr = transition_candidates[(transition_candidates.index(tr) + 1) % len(transition_candidates)]

            video = ffmpeg.filter(
                [video, streams[i]],
                "xfade",
                transition=tr,
                duration=transition_duration,
                offset=offset,
            )
            # Force constant frame rate after each xfade — chaining many
            # xfade filters causes FFmpeg to lose timebase metadata, which
            # surfaces as "current rate of 1/0 is invalid" on later filters.
            video = video.filter("fps", 30)
            previous_transition = tr
            elapsed += durations[i] - transition_duration
        total = sum(durations) - transition_duration * (len(streams) - 1)

    # For scenes that DON'T have their own overlay, we composite the global overlay
    # (padding is now applied per-stream above so xfade dimensions match)
    has_photo_scenes = any(not s.has_own_overlay for s in content_scenes)

    if has_photo_scenes:
        if overlay_frame is not None:
            overlay_stream = (
                ffmpeg
                .input(str(overlay_frame), loop=1, t=max(0.1, total))
                .filter("scale", REEL_WIDTH, REEL_HEIGHT)
                .filter("fps", 30)
                .filter("format", "rgba")
                .filter("trim", duration=total)
                .filter("setpts", "PTS-STARTPTS")
            )
            video = ffmpeg.overlay(video, overlay_stream, x=0, y=0, shortest=1, eof_action="pass")

    # Concat outro if present
    if outro_scene and outro_scene.frame_path:
        outro_stream = (
            ffmpeg
            .input(str(outro_scene.frame_path), loop=1, t=outro_scene.duration)
            .filter("scale", REEL_WIDTH, REEL_HEIGHT)
            .filter("setsar", "1")
            .filter("fps", 30)
            .filter("trim", duration=outro_scene.duration)
            .filter("setpts", "PTS-STARTPTS")
        )
        video = ffmpeg.concat(
            video.filter("format", "yuv420p"),
            outro_stream.filter("format", "yuv420p"),
            v=1, a=0,
        )
        total += outro_scene.duration

    # Encode output
    music_enabled = ENABLE_BACKGROUND_AUDIO and include_music and MUSIC_PATH.exists()
    video_only_path = out_path
    if music_enabled:
        video_only_path = out_path.with_name(f"{out_path.stem}_video_only.mp4")

    try:
        (
            ffmpeg
            .output(
                video,
                str(video_only_path),
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=30,
                crf=30,
                preset="veryfast",
                movflags="+faststart",
                an=None,
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )

        if music_enabled:
            audio = (
                ffmpeg
                .input(str(MUSIC_PATH), stream_loop=-1, t=total)
                .filter("volume", 2.8)
            )
            (
                ffmpeg
                .output(
                    ffmpeg.input(str(video_only_path)).video,
                    audio,
                    str(out_path),
                    vcodec="copy",
                    acodec="aac",
                    movflags="+faststart",
                    shortest=None,
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            if video_only_path.exists():
                video_only_path.unlink()
    except FileNotFoundError as error:
        raise RuntimeError("ffmpeg binary not found") from error
    except ffmpeg.Error as error:
        stderr_text = ""
        if getattr(error, "stderr", None):
            stderr_text = error.stderr.decode("utf-8", errors="ignore").strip()
        if stderr_text:
            raise RuntimeError(f"ffmpeg failed: {stderr_text[-1200:]}") from error
        raise RuntimeError("ffmpeg failed with unknown error") from error
    finally:
        if music_enabled and video_only_path.exists():
            video_only_path.unlink()


def process_video_task(
    job_id: str,
    url: str,
    include_music: bool = True,
    template: str = "new_listing",
) -> None:
    """Scene-based video generation pipeline.

    This is the primary pipeline for property-video-generator.
    Falls back gracefully to the baseline photo+overlay flow when
    enrichment data is not available.
    """
    lock_acquired = GENERATION_SEMAPHORE.acquire(blocking=False)
    if not lock_acquired:
        update_job(
            job_id, "failed", None,
            f"queue_overload: backend is busy (max concurrent jobs={MAX_CONCURRENT_GENERATIONS}); retry shortly",
        )
        return

    temp_dir = Path(tempfile.mkdtemp(prefix=f"propvideo_{job_id}_"))
    started_at = time.time()
    current_step = "initializing"

    def _set_step(step: str) -> None:
        nonlocal current_step
        current_step = step
        logger.info("Job %s step: %s", job_id, step)

    def _ensure_within_runtime_limit() -> None:
        elapsed = time.time() - started_at
        if elapsed > MAX_JOB_SECONDS:
            raise TimeoutError(f"Generation exceeded time limit ({MAX_JOB_SECONDS}s)")

    try:
        _set_job_progress(job_id, 8)
        update_job(job_id, "processing", None, None)

        # --- Scrape listing ---
        _set_step("scrape_listing")
        _set_job_progress(job_id, 12)
        # Fetch HTML once — used by both scrape_listing and enrichment
        html_response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        html_response.raise_for_status()
        raw_html = html_response.text

        address, price, image_urls, branding = scrape_listing(url)
        image_urls = image_urls[:MAX_SOURCE_IMAGES]
        update_job(job_id, "processing", None, None, branding=branding)

        # --- Enrich listing data ---
        _set_step("enrich_listing")
        _set_job_progress(job_id, 18)
        enrichment = enrich_listing_data(
            raw_html,
            url,
            greatschools_api_key=GREATSCHOOLS_API_KEY or None,
            mapbox_token=MAPBOX_TOKEN or None,
            fetch_map=True,
            fetch_schools=True,
        )
        logger.info(
            "Job %s enrichment: stats=%s, desc=%d chars, features=%d, schools=%d, map=%s",
            job_id,
            list(enrichment["stats"].keys()),
            len(enrichment["description"]),
            len(enrichment["features"]),
            len(enrichment["schools"]),
            enrichment["map_image"] is not None,
        )

        # --- Branding assets ---
        _set_step("prepare_branding_assets")
        _set_job_progress(job_id, 22)
        branding_assets = _prepare_branding_assets(branding)

        # --- Download + crop photos ---
        _set_step("download_images")
        _set_job_progress(job_id, 28)
        photos: List[Image.Image] = []
        for i, image_url in enumerate(image_urls, start=1):
            _ensure_within_runtime_limit()
            _set_job_progress(job_id, 28 + int((i - 1) * 12 / max(1, len(image_urls))))
            raw = temp_dir / f"raw_{i}.jpg"
            try:
                download_image(image_url, raw)
                img = Image.open(raw).convert("RGB")
                img = crop_9_16(img)
                photos.append(img)
            except Exception:
                continue
            finally:
                # Remove raw download from disk immediately
                try:
                    raw.unlink(missing_ok=True)
                except Exception:
                    pass

        # Free the raw HTML now that scraping + enrichment are done
        del raw_html
        gc.collect()

        if not photos:
            raise ValueError("Image download failed")

        # --- Build scene list with enrichment data ---
        _set_step("build_scene_list")
        _set_job_progress(job_id, 42)
        scenes = build_scene_list(
            address=address,
            price=price,
            photos=photos,
            template=template,
            branding=branding,
            branding_assets=branding_assets,
            stats=enrichment["stats"] or None,
            description=enrichment["description"] or None,
            features=enrichment["features"] or None,
            schools=enrichment["schools"] or None,
            map_image=enrichment["map_image"],
        )

        # --- FREE photos & enrichment to reclaim memory ---
        # NOTE: Do NOT close enrichment["map_image"] here — scenes hold
        # a reference to the same PIL Image and need it during rendering.
        # The per-scene cleanup loop (below) closes scene.data images after use.
        del photos
        del enrichment
        gc.collect()

        # --- Render scene frames ---
        _set_step("render_scene_frames")
        _set_job_progress(job_id, 50)
        for i, scene in enumerate(scenes):
            _ensure_within_runtime_limit()
            _set_job_progress(job_id, 50 + int(i * 20 / max(1, len(scenes))))

            frame = render_scene_frame(scene)
            ext = "png" if scene.has_own_overlay else "jpg"
            frame_path = temp_dir / f"scene_{i}_{scene.scene_type.value}.{ext}"

            if ext == "png":
                frame.save(frame_path)
            else:
                frame.save(frame_path, quality=95)
            scene.frame_path = frame_path

            # --- FREE rendered frame to reclaim memory ---
            if frame is not scene.rendered_frame:
                frame.close()
            if scene.rendered_frame is not None:
                scene.rendered_frame.close()
                scene.rendered_frame = None
            # NOTE: Do NOT close scene.data images here — multiple scenes
            # share the same PIL Image references (e.g. bg_image = photos[0]).
            # Closing one scene's data would break later scenes that use it.
        gc.collect()

        # --- Render global overlay (for photo scenes) ---
        _set_step("render_overlay")
        _set_job_progress(job_id, 72)
        overlay_path = None
        has_photo_scenes = any(not s.has_own_overlay for s in scenes)
        if has_photo_scenes:
            overlay_path = temp_dir / "overlay.png"
            overlay_image = draw_overlay_layer(
                1080, 1920, address, price,
                template=template,
                branding=branding,
                branding_assets=branding_assets,
            )
            overlay_image.save(overlay_path)
            overlay_image.close()
            del overlay_image
            gc.collect()

        # --- Build video ---
        _set_step("build_video")
        _set_job_progress(job_id, 80)
        video_path = temp_dir / f"{job_id}.mp4"
        _ensure_within_runtime_limit()
        build_video(
            scenes,
            video_path,
            overlay_frame=overlay_path,
            include_music=include_music,
            motion_seed=job_id,
        )

        # --- Upload ---
        _set_step("upload_video")
        _set_job_progress(job_id, 95)
        storage_path = f"renders/{job_id}.mp4"
        _ensure_within_runtime_limit()
        video_bytes = video_path.read_bytes()
        upload_video_to_supabase(storage_path, video_bytes)
        del video_bytes
        gc.collect()

        _set_step("complete")
        _set_job_progress(job_id, 100)
        public_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{storage_path}"
        update_job(job_id, "completed", public_url, None, branding=branding)

    except Exception as error:
        logger.exception("Video generation failed for job %s", job_id)
        _set_job_progress(job_id, max(0, _get_job_progress(job_id, "failed")))
        try:
            update_job(job_id, "failed", None, f"{current_step}: {error}")
        except Exception as update_error:
            logger.error("Failed to persist failure status for job %s: %s", job_id, update_error)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        GENERATION_SEMAPHORE.release()


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        try:
            result = (
                supabase
                .table("videos")
                .select(
                    "id,status,download_url,error_message,updated_at,"
                    "agent_name,agent_phone,agent_email,agent_photo_url,"
                    "broker_name,broker_phone,broker_logo_url,office_address"
                )
                .eq("id", job_id)
                .single()
                .execute()
            )
        except Exception:
            result = (
                supabase
                .table("videos")
                .select("id,status,download_url,updated_at")
                .eq("id", job_id)
                .single()
                .execute()
            )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to fetch job: {error}")

    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    result.data = _mark_job_stale_if_needed(job_id, result.data)

    office_city, office_state = _extract_office_city_state(result.data.get("office_address") or "")
    status_value = result.data.get("status", "unknown")

    return {
        "id": result.data.get("id"),
        "status": status_value,
        "progress": _get_job_progress(job_id, str(status_value)),
        "videoUrl": result.data.get("download_url"),
        "errorMessage": result.data.get("error_message"),
        "branding": {
            "agentName": result.data.get("agent_name"),
            "agentPhone": result.data.get("agent_phone"),
            "agentEmail": result.data.get("agent_email"),
            "agentPhotoUrl": result.data.get("agent_photo_url"),
            "brokerName": result.data.get("broker_name"),
            "brokerPhone": result.data.get("broker_phone"),
            "brokerLogoUrl": result.data.get("broker_logo_url"),
            "officeAddress": result.data.get("office_address"),
            "officeCity": office_city,
            "officeState": office_state,
        },
    }


@app.get("/jobs/{job_id}/debug")
def get_job_debug(job_id: str) -> dict:
    try:
        result = (
            supabase
            .table("videos")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to fetch debug job: {error}")

    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"job": result.data}


@app.post("/generate")
def generate(payload: GenerateRequest, background_tasks: BackgroundTasks) -> dict:
    selected_template = _normalize_template(payload.template)
    try:
        result = supabase.table("videos").insert({"status": "processing"}).execute()
        job_id = str(result.data[0]["id"])
        _set_job_progress(job_id, 8)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {error}")

    background_tasks.add_task(process_video_task, job_id, str(payload.url), bool(payload.include_music), selected_template)
    return {"job_id": job_id, "status": "processing", "template": selected_template, "engine": "scene"}
