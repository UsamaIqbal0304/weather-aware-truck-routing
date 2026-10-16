"""Pure geometry helpers for polylines expressed as (lon, lat) pairs.

GeoJSON order (lon, lat) is used everywhere so that the same arrays can be
handed to the map client without a flip.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Iterable, List, Sequence, Tuple

Coord = Tuple[float, float]  # (lon, lat)

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a: Coord, b: Coord) -> float:
    """Great-circle distance between two (lon, lat) points, in miles."""
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def cumulative(values: Iterable[float]) -> List[float]:
    """Running total with a leading zero: ``[0, v0, v0+v1, ...]``."""
    out = [0.0]
    total = 0.0
    for v in values:
        total += v
        out.append(total)
    return out


def interpolate(a: Coord, b: Coord, fraction: float) -> Coord:
    """Linear interpolation between two coordinates.

    Over the sub-mile spans between consecutive OSRM vertices the error
    against a great-circle interpolation is far below the resolution of any
    weather model, so linear is the right trade.
    """
    f = min(1.0, max(0.0, fraction))
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def locate(cumulative_distances: Sequence[float], target: float) -> Tuple[int, float]:
    """Locate ``target`` on a polyline described by cumulative distances.

    Returns ``(segment_index, fraction_within_segment)``. The index is the
    index of the segment's first vertex. Targets outside the range are
    clamped to the first/last segment.
    """
    if len(cumulative_distances) < 2:
        return 0, 0.0
    total = cumulative_distances[-1]
    if target <= 0:
        return 0, 0.0
    if target >= total:
        last = len(cumulative_distances) - 2
        return last, 1.0
    i = bisect_right(cumulative_distances, target) - 1
    i = min(max(i, 0), len(cumulative_distances) - 2)
    span = cumulative_distances[i + 1] - cumulative_distances[i]
    fraction = 0.0 if span <= 0 else (target - cumulative_distances[i]) / span
    return i, fraction


def perpendicular_offset(a: Coord, b: Coord, point: Coord, miles: float) -> Coord:
    """A point ``miles`` to the left of the a->b bearing, measured at ``point``.

    Used to synthesise via-points when the routing engine returns fewer
    alternatives than we need.
    """
    lat_rad = math.radians(point[1])
    dx = (b[0] - a[0]) * math.cos(lat_rad)
    dy = b[1] - a[1]
    norm = math.hypot(dx, dy)
    if norm == 0:
        return point
    # Rotate the unit direction vector 90 degrees counter-clockwise.
    nx, ny = -dy / norm, dx / norm
    degrees_per_mile_lat = 1.0 / 69.0
    dlat = ny * miles * degrees_per_mile_lat
    cos_lat = max(math.cos(lat_rad), 1e-6)
    dlon = nx * miles * degrees_per_mile_lat / cos_lat
    return (point[0] + dlon, point[1] + dlat)


def simplify(coords: Sequence[Coord], max_points: int) -> List[Coord]:
    """Reduce a polyline to at most ``max_points`` vertices.

    Uniform decimation keeping both endpoints. We only use this on the copy
    of the geometry that is sent to the browser; all sampling maths runs on
    the full-resolution polyline server-side.
    """
    n = len(coords)
    if max_points < 2 or n <= max_points:
        return list(coords)
    step = (n - 1) / (max_points - 1)
    out = [coords[int(round(i * step))] for i in range(max_points)]
    out[-1] = coords[-1]
    return out


def frechet_like_similarity(a: Sequence[Coord], b: Sequence[Coord], samples: int = 24) -> float:
    """Mean distance in miles between two polylines sampled at equal fractions.

    A cheap stand-in for a discrete Frechet distance; good enough to decide
    whether two candidate routes are the "same road".
    """
    if not a or not b:
        return float("inf")

    def at(seq: Sequence[Coord], f: float) -> Coord:
        idx = f * (len(seq) - 1)
        i = int(idx)
        if i >= len(seq) - 1:
            return seq[-1]
        return interpolate(seq[i], seq[i + 1], idx - i)

    total = 0.0
    for k in range(samples):
        f = k / (samples - 1) if samples > 1 else 0.0
        total += haversine_miles(at(a, f), at(b, f))
    return total / samples
