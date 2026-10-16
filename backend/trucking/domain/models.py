"""Domain types. Plain dataclasses and enums, no Django, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import List, Optional, Sequence, Tuple

Coord = Tuple[float, float]  # (lon, lat)


class RiskLevel(IntEnum):
    """Ordered risk bands from the assessment brief.

    Integer-valued so that ``max()`` composes the per-condition levels into
    a checkpoint level and so that an average risk is well defined.
    """

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

    @property
    def label(self) -> str:
        return {
            RiskLevel.LOW: "Low",
            RiskLevel.MODERATE: "Moderate",
            RiskLevel.HIGH: "High",
            RiskLevel.SEVERE: "Severe",
            RiskLevel.NO_TRAVEL: "No Travel",
        }[self]


@dataclass(frozen=True)
class Place:
    """A geocoded endpoint."""

    query: str
    name: str
    lon: float
    lat: float

    @property
    def coord(self) -> Coord:
        return (self.lon, self.lat)


@dataclass(frozen=True)
class WeatherSample:
    """Forecast values at one point in space and time.

    Units are exactly those of the risk table: mph and inches per hour.
    ``valid_time`` is the top of the forecast hour actually used, which is
    the hour nearest the checkpoint's estimated time of arrival.
    """

    valid_time: datetime
    wind_mph: float
    wind_gust_mph: float
    rain_in_hr: float
    snow_in_hr: float
    temperature_f: Optional[float] = None


@dataclass(frozen=True)
class RiskAssessment:
    """The outcome of applying the risk table and the load rules."""

    level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    driver: str
    load_rule: Optional[str] = None


@dataclass
class Checkpoint:
    """One sampling point along a route."""

    index: int
    lon: float
    lat: float
    distance_miles: float
    eta: Optional[datetime]
    elapsed_hours: float
    covered_miles: float
    weather: Optional[WeatherSample] = None
    risk: Optional[RiskAssessment] = None

    @property
    def coord(self) -> Coord:
        return (self.lon, self.lat)


@dataclass
class RouteSummary:
    """Aggregates used by the recommendation comparator."""

    distance_miles: float
    duration_hours: float
    severe_miles: float
    high_miles: float
    moderate_miles: float
    low_miles: float
    no_travel_miles: float
    average_risk: float
    max_risk: RiskLevel
    assessed_miles: float
    unassessed_miles: float


@dataclass
class RouteOption:
    """A candidate route with its checkpoints and summary."""

    id: str
    name: str
    source: str
    distance_miles: float
    duration_hours: float
    geometry: List[Coord]
    checkpoints: List[Checkpoint] = field(default_factory=list)
    summary: Optional[RouteSummary] = None
    arrival: Optional[datetime] = None

    @property
    def blocked(self) -> bool:
        """True when any assessed checkpoint reaches No Travel."""
        return any(
            cp.risk is not None and cp.risk.level is RiskLevel.NO_TRAVEL
            for cp in self.checkpoints
        )


@dataclass
class RawRoute:
    """What a routing engine returns, before any weather is attached."""

    geometry: List[Coord]
    distance_miles: float
    duration_hours: float
    segment_miles: Sequence[float]
    segment_hours: Sequence[float]
    source: str = "osrm:alternative"
