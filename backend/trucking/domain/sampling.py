"""Turn a route into checkpoints carrying an estimated time of arrival.

This is the part of the brief most worth getting right: the weather that
matters at a checkpoint 600 miles out is the weather *when the truck gets
there*, not the weather at departure. OSRM returns a per-vertex duration
annotation, so the elapsed driving time at any point on the polyline is
known exactly rather than inferred from an average speed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Sequence

from .geometry import cumulative, interpolate, locate
from .models import Checkpoint, Coord, RawRoute

# Spacings the brief asks for.
ALLOWED_SPACINGS_MILES = (10, 25, 50)


def checkpoint_distances(total_miles: float, spacing_miles: float) -> List[float]:
    """Distances at which to sample, including both endpoints.

    Origin is always sampled (the driver is standing in that weather) and
    so is the destination, even when it does not land on a spacing
    multiple. A final checkpoint closer than a tenth of the spacing to the
    previous one is dropped rather than crowding the table.
    """
    if spacing_miles <= 0:
        raise ValueError("spacing_miles must be positive")
    marks: List[float] = []
    d = 0.0
    while d < total_miles:
        marks.append(d)
        d += spacing_miles
    if not marks:
        marks.append(0.0)
    if total_miles > 0:
        if total_miles - marks[-1] < spacing_miles * 0.1 and len(marks) > 1:
            marks[-1] = total_miles
        else:
            marks.append(total_miles)
    return marks


def covered_miles(marks: Sequence[float], total_miles: float) -> List[float]:
    """Route miles attributed to each checkpoint.

    Each checkpoint owns the stretch of road that is nearer to it than to
    any other checkpoint — the one-dimensional Voronoi cell, clipped to the
    route. The cells partition the route exactly, which is what lets
    "severe miles" and "average risk" be sums and weighted means over
    checkpoints without double counting.
    """
    n = len(marks)
    if n == 0:
        return []
    if n == 1:
        return [total_miles]
    out: List[float] = []
    for i, m in enumerate(marks):
        lower = 0.0 if i == 0 else (marks[i - 1] + m) / 2.0
        upper = total_miles if i == n - 1 else (m + marks[i + 1]) / 2.0
        out.append(max(0.0, upper - lower))
    return out


def sample_route(
    route: RawRoute,
    departure: datetime,
    spacing_miles: float,
) -> List[Checkpoint]:
    """Place checkpoints along ``route`` and date-stamp each with its ETA.

    ``route.segment_miles`` and ``route.segment_hours`` are per-vertex-pair
    arrays from the routing engine, so elapsed time is read off the route
    itself. Where the engine gives no annotation the caller is expected to
    have filled those arrays by distributing the total duration over the
    segments in proportion to their length; see ``services.routing``.
    """
    coords: Sequence[Coord] = route.geometry
    if len(coords) < 2:
        raise ValueError("a route needs at least two coordinates")

    cum_miles = cumulative(route.segment_miles)
    cum_hours = cumulative(route.segment_hours)
    total_miles = cum_miles[-1]

    marks = checkpoint_distances(total_miles, spacing_miles)
    spans = covered_miles(marks, total_miles)

    checkpoints: List[Checkpoint] = []
    for i, (mark, span) in enumerate(zip(marks, spans)):
        seg, fraction = locate(cum_miles, mark)
        lon, lat = interpolate(coords[seg], coords[seg + 1], fraction)
        seg_hours = cum_hours[seg + 1] - cum_hours[seg]
        elapsed = cum_hours[seg] + seg_hours * fraction
        checkpoints.append(
            Checkpoint(
                index=i,
                lon=lon,
                lat=lat,
                distance_miles=mark,
                eta=departure + timedelta(hours=elapsed),
                elapsed_hours=elapsed,
                covered_miles=span,
            )
        )
    return checkpoints


def corridor_points(route: RawRoute, max_points: int = 48) -> List[Coord]:
    """Evenly spaced points along the route, for the heatmap corridor.

    Spaced by distance rather than by vertex index so that the heatmap is
    not dense in cities and sparse on the interstate.
    """
    if max_points < 2 or len(route.geometry) < 2:
        return list(route.geometry[:max_points])
    cum_miles = cumulative(route.segment_miles)
    total = cum_miles[-1]
    out: List[Coord] = []
    for k in range(max_points):
        target = total * k / (max_points - 1)
        seg, fraction = locate(cum_miles, target)
        out.append(interpolate(route.geometry[seg], route.geometry[seg + 1], fraction))
    return out
