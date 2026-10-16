"""Place name -> coordinate, via Nominatim.

Nominatim's usage policy (https://operations.osmfoundation.org/policies/nominatim/)
requires an identifying User-Agent, allows at most one request per second,
and asks that results be cached. All three are handled in services.http;
this module only shapes the request and the result. A "lat,lon" string is
resolved locally without touching the service at all, which is both faster
and one fewer request against someone else's free server.
"""

from __future__ import annotations

import re
from typing import Optional

from django.conf import settings

from ..domain.models import Place
from .http import UpstreamError, get_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class PlaceNotFound(ValueError):
    """The geocoder answered, and the answer was "no such place".

    Distinct from :class:`UpstreamError` on purpose: a typo in a town name
    is the user's to fix (422), while Nominatim being down is ours (502).
    Collapsing the two would tell a driver to retry when retrying cannot
    help, and page an operator when nothing is broken.
    """


_LATLON = re.compile(
    r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)


def parse_latlon(query: str) -> Optional[Place]:
    """Accept a raw "lat,lon" so the app is usable without a geocoder."""
    match = _LATLON.match(query)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return Place(query=query, name=f"{lat:.4f}, {lon:.4f}", lon=lon, lat=lat)


def geocode(query: str) -> Place:
    """Resolve a free-text place to a :class:`Place`.

    Raises :class:`PlaceNotFound` when the geocoder has no match, and
    :class:`UpstreamError` when it could not be asked.
    """
    direct = parse_latlon(query)
    if direct is not None:
        return direct

    payload = get_json(
        "nominatim",
        NOMINATIM_URL,
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 0,
            "countrycodes": settings.GEOCODER_COUNTRY_CODES,
        },
        ttl=settings.CACHE_TTL_GEOCODE,
        min_interval=settings.NOMINATIM_MIN_INTERVAL_SECONDS,
    )

    if not payload:
        raise PlaceNotFound(
            f"No place matched {query!r}. Try adding a state, "
            'or enter coordinates as "lat,lon".'
        )

    top = payload[0]
    return Place(
        query=query,
        name=top.get("display_name", query),
        lon=float(top["lon"]),
        lat=float(top["lat"]),
    )
