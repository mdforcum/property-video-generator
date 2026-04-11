"""Scene engine for composing multi-scene real estate videos.

Instead of treating a video as a flat list of photos with a single overlay,
the scene engine models each video as an ordered list of typed Scene objects.
Each scene carries its own data payload, duration, render function, and
motion profile, allowing rich mixed-content videos (hero photos, stats cards,
description slides, school infographics, map CTAs, branded outros).
"""

from .models import Scene, SceneType, MotionProfile  # noqa: F401
from .renderers import render_scene_frame  # noqa: F401
from .builder import build_scene_list  # noqa: F401
