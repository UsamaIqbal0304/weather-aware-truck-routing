"""Route generation, via the public OSRM demo server.

Two things this module exists to handle.

First, elapsed time. OSRM can annotate a route per vertex pair with
distance and duration (``annotations=true``). That is what makes an honest
ETA at checkpoint N possible: we read the engine's own time for the road
actually taken, instead of dividing miles by an assumed average speed. If
the annotation is missing we fall back to distributing the total duration
over the segments in proportion to length, and say so on the route.

Second, getting three options. OSRM's alternative search returns what it
finds, which on many pairs is two routes and sometimes one. Asking for
more than three makes the demo server return none at all. So when the
engine is short, we synthesise candidates by routing through a via-point
offset perpendicular to the straight line at the midpoint, and keep the
ones that are genuinely different roads rather than the same road again.

OSRM's demo server is run by the OSRM project as a courtesy
(https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server): it is for
light use, so every response is cached server-side and the per-host
interval in settings applies.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from django.conf import settings

from ..domain.geometry import (
    cumulative,
    frechet_like_similarity,
    haversine_miles,
    perpendicular_offset,
)
from ..domain.models import Coord, RawRoute
from ..domain.units import SECONDS_PER_HOUR, metres_to_miles
from .http import UpstreamError, get_json

logger = logging.getLogger(__name__)

# Offsets tried, in order, when the engine gives us fewer than we need.
# Signed: positive is left of the origin->destination bearing.
DETOUR_OFFSETS_FRACTION = (0.14, -0.14, 0.28, -0.28)

# Two candidates whose sampled mean separation is below this are the same
# road for our purposes and the later one is discarded.
DISTINCT_ROUTE_MIN_MILES = 12.0


class NoRouteFound(ValueError):
    """The engine answered, and there is no drivable road between the points.

    A ValueError rather than an UpstreamError for the same reason as
    :class:`~.geocoding.PlaceNotFound`: the caller should change the
    request, not retry it.
    """


def _coords_param(points: Sequence[Coord]) -> str:
    return ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)


def _parse_route(raw: dict, source: str) -> Optional[RawRoute]:
    """Convert one OSRM route object into a :class:`RawRoute`."""
    geometry = [tuple(c) for c in raw.get("geometry", {}).get("coordinates", [])]
    if len(geometry) < 2:
        return None

    distance_miles = metres_to_miles(float(raw.get("distance", 0.0)))
    duration_hours = float(raw.get("duration", 0.0)) / SECONDS_PER_HOUR

    seg_miles: List[float] = []
    seg_hours: List[float] = []
    for leg in raw.get("legs", []):
        annotation = leg.get("annotation") or {}
        distances = annotation.get("distance")
        durations = annotation.get("duration")
        if distances and durations and len(distances) == len(durations):
            seg_miles.extend(metres_to_miles(float(d)) for d in distances)
            seg_hours.extend(float(s) / SECONDS_PER_HOUR for s in durations)

    expected = len(geometry) - 1
    if len(seg_miles) != expected or not seg_miles:
        # Fall back to geometric lengths, with time spread by distance.
        source = f"{source}+estimated-time"
        seg_miles = [
            haversine_miles(geometry[i], geometry[i + 1]) for i in range(expected)
        ]
        total = sum(seg_miles) or 1.0
        seg_hours = [duration_hours * m / total for m in seg_miles]

    # Trust the annotation for the shape of the journey but keep the
    # engine's own totals authoritative, so the summary matches what OSRM
    # reports for the route as a whole.
    annotated_miles = sum(seg_miles)
    annotated_hours = sum(seg_hours)
    if annotated_miles > 0 and distance_miles > 0:
        scale = distance_miles / annotated_miles
        seg_miles = [m * scale for m in seg_miles]
    if annotated_hours > 0 and duration_hours > 0:
        scale = duration_hours / annotated_hours
        seg_hours = [h * scale for h in seg_hours]

    return RawRoute(
        geometry=geometry,
        distance_miles=distance_miles,
        duration_hours=duration_hours,
        segment_miles=seg_miles,
        segment_hours=seg_hours,
        source=source,
    )


def _osrm(points: Sequence[Coord], alternatives: int, source: str) -> List[RawRoute]:
    url = (
        f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/"
        f"{settings.OSRM_PROFILE}/{_coords_param(points)}"
    )
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "true",
        "steps": "false",
    }
    if alternatives > 0:
        params["alternatives"] = alternatives

    payload = get_json(
        "osrm",
        url,
        params,
        ttl=settings.CACHE_TTL_ROUTE,
        min_interval=settings.OSRM_MIN_INTERVAL_SECONDS,
        timeout=settings.OSRM_TIMEOUT_SECONDS,
    )

    if payload.get("code") != "Ok":
        raise UpstreamError("osrm", payload.get("message", payload.get("code", "error")))

    routes = []
    for raw in payload.get("routes", []):
        parsed = _parse_route(raw, source)
        if parsed is not None:
            routes.append(parsed)
    return routes


def _is_distinct(candidate: RawRoute, chosen: Sequence[RawRoute]) -> bool:
    return all(
        frechet_like_similarity(candidate.geometry, other.geometry)
        >= DISTINCT_ROUTE_MIN_MILES
        for other in chosen
    )


def generate_routes(
    origin: Coord, destination: Coord, wanted: int = 3
) -> Tuple[List[RawRoute], List[str]]:
    """Up to ``wanted`` distinct routes. Returns (routes, notes).

    ``notes`` carries anything the user should know about how the set was
    produced — a synthesised detour, or fewer routes than asked for — so
    the UI can say it rather than quietly presenting three equals.
    """
    notes: List[str] = []
    chosen: List[RawRoute] = []

    for route in _osrm([origin, destination], alternatives=wanted, source="osrm:alternative"):
        if _is_distinct(route, chosen):
            chosen.append(route)
        if len(chosen) >= wanted:
            return chosen, notes

    if not chosen:
        raise NoRouteFound(
            "No drivable route connects those points. Check that both ends are "
            "on the road network and on the same landmass."
        )

    direct_miles = haversine_miles(origin, destination)
    midpoint = ((origin[0] + destination[0]) / 2.0, (origin[1] + destination[1]) / 2.0)

    for fraction in DETOUR_OFFSETS_FRACTION:
        if len(chosen) >= wanted:
            break
        via = perpendicular_offset(origin, destination, midpoint, direct_miles * fraction)
        try:
            detours = _osrm([origin, via, destination], alternatives=0, source="osrm:via-detour")
        except UpstreamError as exc:
            logger.info("detour via %s failed: %s", via, exc)
            continue
        for route in detours:
            if _is_distinct(route, chosen):
                chosen.append(route)
                notes.append(
                    "The routing engine offered fewer than three alternatives for this "
                    "pair, so one option was generated by routing through a waypoint "
                    "off the direct line."
                )
                break

    if len(chosen) < wanted:
        notes.append(
            f"Only {len(chosen)} genuinely distinct route(s) exist between these points; "
            "near-identical candidates were merged."
        )
    return chosen[:wanted], notes


def route_totals(route: RawRoute) -> Tuple[float, float]:
    """(miles, hours) from the per-segment arrays. Used in tests."""
    return cumulative(route.segment_miles)[-1], cumulative(route.segment_hours)[-1]
