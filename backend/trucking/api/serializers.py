"""Domain objects -> the JSON the browser receives.

Two rules are kept throughout:

* coordinates are always ``[lon, lat]``, GeoJSON order, so the arrays go
  straight into a map source with no flip anywhere in the client;
* every number is rounded here, once, at the boundary. A float with
  fifteen digits of noise is the single biggest avoidable chunk of a plan
  response, and rounding at the edge keeps full precision in the maths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ..domain.models import Checkpoint, Place, RiskAssessment, RouteOption, RouteSummary, WeatherSample
from .planner import HeatmapFrames, Plan

# Six decimal places is ~0.1 m. Beyond that a polyline vertex is noise.
COORD_PLACES = 5


def _iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _coord(coord: Sequence[float]) -> List[float]:
    return [round(coord[0], COORD_PLACES), round(coord[1], COORD_PLACES)]


def place(value: Place) -> Dict[str, Any]:
    return {
        "query": value.query,
        "name": value.name,
        "lon": round(value.lon, 6),
        "lat": round(value.lat, 6),
    }


def weather(value: Optional[WeatherSample]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {
        "valid_time": _iso(value.valid_time),
        "wind_mph": round(value.wind_mph, 1),
        "wind_gust_mph": round(value.wind_gust_mph, 1),
        "rain_in_hr": round(value.rain_in_hr, 3),
        "snow_in_hr": round(value.snow_in_hr, 2),
        "temperature_f": None if value.temperature_f is None else round(value.temperature_f, 1),
    }


def risk(value: Optional[RiskAssessment]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {
        "level": int(value.level),
        "label": value.level.label,
        "wind_level": int(value.wind_level),
        "rain_level": int(value.rain_level),
        "snow_level": int(value.snow_level),
        "driver": value.driver,
        "load_rule": value.load_rule,
    }


def checkpoint(value: Checkpoint) -> Dict[str, Any]:
    return {
        "index": value.index,
        "lon": round(value.lon, COORD_PLACES),
        "lat": round(value.lat, COORD_PLACES),
        "distance_miles": round(value.distance_miles, 1),
        "covered_miles": round(value.covered_miles, 2),
        "elapsed_hours": round(value.elapsed_hours, 3),
        "eta": _iso(value.eta),
        "weather": weather(value.weather),
        "risk": risk(value.risk),
    }


def summary(value: Optional[RouteSummary]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {
        "distance_miles": round(value.distance_miles, 1),
        "duration_hours": round(value.duration_hours, 2),
        "severe_miles": round(value.severe_miles, 1),
        "high_miles": round(value.high_miles, 1),
        "moderate_miles": round(value.moderate_miles, 1),
        "low_miles": round(value.low_miles, 1),
        "no_travel_miles": round(value.no_travel_miles, 1),
        "average_risk": round(value.average_risk, 3),
        "max_risk": int(value.max_risk),
        "max_risk_label": value.max_risk.label,
        "assessed_miles": round(value.assessed_miles, 1),
        "unassessed_miles": round(value.unassessed_miles, 1),
    }


def heatmap(value: HeatmapFrames) -> Dict[str, Any]:
    return {
        "points": [_coord(p) for p in value.points],
        "levels": value.levels,
        "wind_mph": value.wind_mph,
        "rain_in_hr": value.rain_in_hr,
        "snow_in_hr": value.snow_in_hr,
    }


def route(value: RouteOption, rank: int, recommended: bool) -> Dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "source": value.source,
        "rank": rank,
        "recommended": recommended,
        "blocked": value.blocked,
        "distance_miles": round(value.distance_miles, 1),
        "duration_hours": round(value.duration_hours, 2),
        "arrival": _iso(value.arrival),
        "geometry": [_coord(c) for c in value.geometry],
        "summary": summary(value.summary),
        "checkpoints": [checkpoint(cp) for cp in value.checkpoints],
    }


def _why(plan: Plan) -> Optional[str]:
    """One sentence naming the criterion that actually decided the pick.

    The brief's preference order is lexicographic, so exactly one criterion
    separates the winner from the runner-up. Saying which one turns an
    opaque ranking into something a dispatcher can argue with.
    """
    chosen = next((r for r in plan.routes if r.id == plan.recommended_id), None)
    if chosen is None or chosen.summary is None:
        return None
    rivals = [r for r in plan.routes if r.id != chosen.id and r.summary is not None]
    if not rivals:
        return f"{chosen.name} is the only candidate route."
    best_rival = rivals[0]
    a, b = chosen.summary, best_rival.summary
    if a.severe_miles < b.severe_miles - 0.05:
        return (
            f"{chosen.name} has {a.severe_miles:.0f} severe miles against "
            f"{b.severe_miles:.0f} on {best_rival.name}."
        )
    if a.high_miles < b.high_miles - 0.05:
        return (
            f"Severe exposure is level, so high-risk miles decide it: "
            f"{a.high_miles:.0f} against {b.high_miles:.0f} on {best_rival.name}."
        )
    if a.average_risk < b.average_risk - 0.005:
        return (
            f"Severe and high miles are level, so average risk decides it: "
            f"{a.average_risk:.2f} against {b.average_risk:.2f} on {best_rival.name}."
        )
    if a.duration_hours < b.duration_hours - 0.01:
        return (
            f"Weather risk is level across the candidates, so travel time decides it: "
            f"{a.duration_hours:.1f} h against {b.duration_hours:.1f} h."
        )
    return f"{chosen.name} ties on every criterion and is first in the engine's order."


def plan_response(plan: Plan) -> Dict[str, Any]:
    return {
        "request": {
            "origin": place(plan.origin),
            "destination": place(plan.destination),
            "departure": _iso(plan.departure),
            "load_lb": plan.load_lb,
            "spacing_miles": plan.spacing_miles,
        },
        "recommendation": {
            "route_id": plan.recommended_id,
            "reason": _why(plan),
            "warning": plan.warning,
        },
        "routes": [
            route(r, rank=i + 1, recommended=(r.id == plan.recommended_id))
            for i, r in enumerate(plan.routes)
        ],
        "heatmap": {
            "hour_offsets": plan.hour_offsets,
            "by_route": {rid: heatmap(frames) for rid, frames in plan.heatmaps.items()},
        },
        "notes": plan.notes,
        "meta": {
            "weather_cells": plan.weather_cells,
            "elapsed_ms": plan.elapsed_ms,
            "checkpoints": sum(len(r.checkpoints) for r in plan.routes),
            "attribution": {
                "routing": "OSRM (Project-OSRM demo server), OpenStreetMap data",
                "geocoding": "Nominatim, OpenStreetMap data",
                "weather": "Open-Meteo",
            },
        },
    }
