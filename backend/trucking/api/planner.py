"""Orchestration: a validated request in, a scored plan out.

The order matters and is worth stating, because it is what makes the ETAs
mean anything:

1. resolve both endpoints to coordinates;
2. ask the routing engine for up to three distinct candidates;
3. place checkpoints along each at the requested spacing, carrying the
   engine's own elapsed time, so every checkpoint has an arrival instant;
4. fetch one hourly forecast series per ~1 km grid cell touched by any
   checkpoint or any heatmap corridor point, in a handful of batched calls;
5. score each checkpoint against the forecast hour nearest *its* ETA;
6. fold the checkpoints into per-route aggregates and rank.

Step 4 is deliberately a single fetch across all three routes rather than
three fetches: the candidates overlap heavily, so one combined call reuses
the shared cells instead of paying for them once per route.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from django.conf import settings

from ..domain.geometry import simplify
from ..domain.models import Checkpoint, Coord, Place, RawRoute, RouteOption
from ..domain.recommend import recommend, summarise
from ..domain.risk import assess
from ..domain.sampling import corridor_points, sample_route
from ..services import weather as weather_service
from ..services.geocoding import geocode
from ..services.routing import generate_routes
from .validation import PlanRequest, PlaceInput, check_route_size

logger = logging.getLogger(__name__)

ROUTE_LABELS = ("Route A", "Route B", "Route C", "Route D")


@dataclass
class HeatmapFrames:
    """Risk along one route's corridor, hour by hour, from departure.

    ``levels[h][i]`` is the risk ordinal at corridor point ``i`` during
    forecast hour ``h``. Stored transposed this way because the slider
    changes ``h`` and redraws every point, so one frame is one contiguous
    array the client hands straight to the map source.
    """

    points: List[Coord]
    levels: List[List[int]]
    wind_mph: List[List[float]]
    rain_in_hr: List[List[float]]
    snow_in_hr: List[List[float]]


@dataclass
class Plan:
    origin: Place
    destination: Place
    departure: datetime
    load_lb: float
    spacing_miles: int
    routes: List[RouteOption]
    recommended_id: Optional[str]
    warning: Optional[str]
    notes: List[str]
    heatmaps: Dict[str, HeatmapFrames]
    hour_offsets: List[int]
    weather_cells: int
    elapsed_ms: int


def _resolve(place: PlaceInput) -> Place:
    """Turn user input into a coordinate, geocoding only when needed."""
    if place.resolved:
        return Place(query=place.text, name=place.text, lon=place.lon, lat=place.lat)
    return geocode(place.text)


def _weather_window(
    departure: datetime, routes: Sequence[RawRoute], hours: int
) -> Tuple[datetime, datetime]:
    """Span the forecast has to cover: the whole drive, and the slider.

    The slider always runs ``hours`` past departure even on a short trip,
    because the heatmap is a forecast of the corridor and not of the drive.
    """
    latest_arrival = departure
    for route in routes:
        latest_arrival = max(latest_arrival, departure + timedelta(hours=route.duration_hours))
    return departure, max(latest_arrival, departure + timedelta(hours=hours))


def _score_checkpoints(
    checkpoints: Sequence[Checkpoint],
    series: Dict[Coord, weather_service.HourlySeries],
    load_lb: float,
) -> None:
    """Attach the forecast at each checkpoint's own ETA, and its risk.

    A checkpoint whose ETA falls outside the model horizon keeps a null
    weather and risk rather than borrowing the nearest hour it does have;
    ``summarise`` then reports those miles as unassessed instead of
    quietly scoring them Low.
    """
    for cp in checkpoints:
        cell = weather_service.lookup(series, cp.coord)
        if cell is None or cp.eta is None:
            continue
        sample = cell.at(cp.eta)
        if sample is None:
            continue
        cp.weather = sample
        cp.risk = assess(sample, load_lb)


def _build_heatmap(
    points: Sequence[Coord],
    series: Dict[Coord, weather_service.HourlySeries],
    departure: datetime,
    hours: int,
    load_lb: float,
) -> HeatmapFrames:
    """Risk at every corridor point for hours 0..N after departure."""
    levels: List[List[int]] = []
    winds: List[List[float]] = []
    rains: List[List[float]] = []
    snows: List[List[float]] = []

    cells = [weather_service.lookup(series, p) for p in points]
    for hour in range(hours + 1):
        when = departure + timedelta(hours=hour)
        row_level: List[int] = []
        row_wind: List[float] = []
        row_rain: List[float] = []
        row_snow: List[float] = []
        for cell in cells:
            sample = cell.at(when) if cell is not None else None
            if sample is None:
                # 0 is outside the RiskLevel range, so the client can draw
                # "no data" distinctly rather than as a calm Low.
                row_level.append(0)
                row_wind.append(0.0)
                row_rain.append(0.0)
                row_snow.append(0.0)
                continue
            row_level.append(int(assess(sample, load_lb).level))
            row_wind.append(round(sample.wind_mph, 1))
            row_rain.append(round(sample.rain_in_hr, 3))
            row_snow.append(round(sample.snow_in_hr, 2))
        levels.append(row_level)
        winds.append(row_wind)
        rains.append(row_rain)
        snows.append(row_snow)

    return HeatmapFrames(
        points=list(points),
        levels=levels,
        wind_mph=winds,
        rain_in_hr=rains,
        snow_in_hr=snows,
    )


def build_plan(request: PlanRequest) -> Plan:
    """Run the whole pipeline. Upstream failures propagate as UpstreamError."""
    started = time.monotonic()

    origin = _resolve(request.origin)
    destination = _resolve(request.destination)

    raw_routes, notes = generate_routes(
        origin.coord, destination.coord, wanted=request.wanted_routes
    )

    usable: List[RawRoute] = []
    for raw in raw_routes:
        ok, why = check_route_size(raw.distance_miles, request.spacing_miles)
        if ok:
            usable.append(raw)
        else:
            notes.append(f"A candidate route was dropped: {why}.")
    if not usable:
        raise ValueError(
            "No candidate route is within the planning limits. "
            "Try a shorter trip or a wider sampling interval."
        )

    hours = settings.HEATMAP_HOURS
    window_start, window_end = _weather_window(request.departure, usable, hours)

    # One coordinate list for every cell any part of the plan will read, so
    # the forecast is fetched once rather than per route and per purpose.
    corridors = [
        corridor_points(raw, settings.HEATMAP_CORRIDOR_POINTS) for raw in usable
    ]
    sampled = [sample_route(raw, request.departure, request.spacing_miles) for raw in usable]

    wanted_coords: List[Coord] = []
    for checkpoints in sampled:
        wanted_coords.extend(cp.coord for cp in checkpoints)
    for corridor in corridors:
        wanted_coords.extend(corridor)

    series = weather_service.fetch_series(wanted_coords, window_start, window_end)

    routes: List[RouteOption] = []
    heatmaps: Dict[str, HeatmapFrames] = {}
    for i, (raw, checkpoints, corridor) in enumerate(zip(usable, sampled, corridors)):
        _score_checkpoints(checkpoints, series, request.load_lb)
        route_id = f"route-{i + 1}"
        option = RouteOption(
            id=route_id,
            name=ROUTE_LABELS[i] if i < len(ROUTE_LABELS) else f"Route {i + 1}",
            source=raw.source,
            distance_miles=raw.distance_miles,
            duration_hours=raw.duration_hours,
            geometry=simplify(raw.geometry, settings.MAX_GEOMETRY_POINTS),
            checkpoints=checkpoints,
            arrival=request.departure + timedelta(hours=raw.duration_hours),
        )
        option.summary = summarise(checkpoints, raw.distance_miles, raw.duration_hours)
        routes.append(option)
        heatmaps[route_id] = _build_heatmap(
            corridor, series, request.departure, hours, request.load_lb
        )

    choice, ranked, warning = recommend(routes)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "plan: %s -> %s, %d routes, %d weather cells, %d ms",
        origin.name,
        destination.name,
        len(ranked),
        len(series),
        elapsed_ms,
    )

    return Plan(
        origin=origin,
        destination=destination,
        departure=request.departure,
        load_lb=request.load_lb,
        spacing_miles=request.spacing_miles,
        routes=ranked,
        recommended_id=choice.id if choice is not None else None,
        warning=warning,
        notes=notes,
        heatmaps=heatmaps,
        hour_offsets=list(range(hours + 1)),
        weather_cells=len(series),
        elapsed_ms=elapsed_ms,
    )
