"""Django settings for the weather-aware routing service.

The app stores nothing, so there is no database and no ORM app in
``INSTALLED_APPS``. Everything it serves is derived on the fly from three
public APIs and cached in memory. Dropping ``contenttypes``/``auth``/
``sessions`` keeps the cold start on a serverless host down to the Django
core plus ``requests``.

Every tunable that affects how hard we lean on someone else's free server
lives here rather than in the call sites, so the whole upstream policy is
readable in one screen.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- core -------------------------------------------------------------------

# No user data, no sessions, no admin: the key signs nothing. It still has to
# exist for Django to boot, and it is still read from the environment first so
# a deployment can set a real one.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-a-secret")
DEBUG = _env_bool("DJANGO_DEBUG", False)

# Vercel gives each deployment its own hostname, so an explicit list would be
# wrong a minute after it was written. The service exposes no host-sensitive
# behaviour (no cookies, no password reset links), so the wildcard costs
# nothing; an operator can still pin it with DJANGO_ALLOWED_HOSTS.
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = ["trucking"]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.middleware.gzip.GZipMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []
DATABASES = {}
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False

# --- cache ------------------------------------------------------------------

# In-process only. On a serverless host each instance warms its own copy,
# which is still worth having: one plan request samples three overlapping
# routes, and the second and third reuse most of the first one's weather
# cells. A shared Redis would help across requests but adds a service to
# operate for an app whose data is free to re-fetch.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "trucking",
        "OPTIONS": {"MAX_ENTRIES": 5000, "CULL_FREQUENCY": 4},
    }
}

CACHE_TTL_GEOCODE = _env_int("CACHE_TTL_GEOCODE", 7 * 24 * 3600)
CACHE_TTL_ROUTE = _env_int("CACHE_TTL_ROUTE", 6 * 3600)
# Open-Meteo refreshes hourly; holding a series longer than that would serve
# a forecast the upstream has already revised.
CACHE_TTL_WEATHER = _env_int("CACHE_TTL_WEATHER", 15 * 60)

# --- upstream services ------------------------------------------------------

UPSTREAM_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT",
    "spotter-weather-routing/1.0 (+https://github.com/UsamaIqbal0304/spotter-assessment)",
)
UPSTREAM_TIMEOUT_SECONDS = _env_float("UPSTREAM_TIMEOUT_SECONDS", 12.0)

# Nominatim's usage policy allows at most one request per second per
# application and requires the identifying User-Agent set above.
NOMINATIM_MIN_INTERVAL_SECONDS = _env_float("NOMINATIM_MIN_INTERVAL_SECONDS", 1.0)
# Bias free-text geocoding to the US; the brief is about US trucking and the
# bias stops "Springfield" resolving to a village in another hemisphere.
GEOCODER_COUNTRY_CODES = os.environ.get("GEOCODER_COUNTRY_CODES", "us,ca,mx")

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
OSRM_PROFILE = os.environ.get("OSRM_PROFILE", "driving")
OSRM_MIN_INTERVAL_SECONDS = _env_float("OSRM_MIN_INTERVAL_SECONDS", 0.2)
# Continental routes with full geometry and per-vertex annotations are a big
# response; the demo server needs longer than the default.
OSRM_TIMEOUT_SECONDS = _env_float("OSRM_TIMEOUT_SECONDS", 25.0)

OPEN_METEO_MIN_INTERVAL_SECONDS = _env_float("OPEN_METEO_MIN_INTERVAL_SECONDS", 0.0)
# Open-Meteo accepts many coordinates in one call. 100 keeps the URL well
# inside limits while making a 50-mile sampling of three routes a few calls.
WEATHER_BATCH_SIZE = _env_int("WEATHER_BATCH_SIZE", 100)
# ~1.1 km of latitude. Finer than any model Open-Meteo blends, so rounding to
# it loses no accuracy and collapses the near-identical points that three
# overlapping routes produce onto shared cache keys.
WEATHER_GRID_DECIMALS = _env_int("WEATHER_GRID_DECIMALS", 2)

# --- planning limits --------------------------------------------------------

# Guard rails on user input, so one request cannot ask for 40,000 checkpoints.
MAX_ROUTE_MILES = _env_float("MAX_ROUTE_MILES", 3200.0)
MAX_CHECKPOINTS_PER_ROUTE = _env_int("MAX_CHECKPOINTS_PER_ROUTE", 420)
# The brief's heatmap slider spans 0-48 hours.
HEATMAP_HOURS = _env_int("HEATMAP_HOURS", 48)
HEATMAP_CORRIDOR_POINTS = _env_int("HEATMAP_CORRIDOR_POINTS", 60)
# Vertices in the polyline handed to the browser. The full OSRM geometry for a
# 1,000-mile route is ~20k points; drawing that for three routes costs more
# than it shows. All sampling maths still runs on the full-resolution line.
MAX_GEOMETRY_POINTS = _env_int("MAX_GEOMETRY_POINTS", 900)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
