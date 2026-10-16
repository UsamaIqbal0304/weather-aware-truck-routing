"""Request parsing for the plan endpoint.

Hand-written rather than a serializer library: there is exactly one request
shape, it has six fields, and every one of them needs a message a driver
could act on ("load weight must be between 0 and 200000 lb"), not a generic
type error. That is less code here than configuring it elsewhere, and it
keeps the dependency list at Django plus requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Tuple

from django.conf import settings

from ..domain.sampling import ALLOWED_SPACINGS_MILES

# A road tractor plus trailer tops out near 80,000 lb gross in the US without
# a permit. The ceiling here is deliberately well above that so a permitted
# heavy haul still plans, while a typo of 4,000,000 is rejected.
MAX_LOAD_LB = 200_000.0
# Open-Meteo serves 16 days ahead; a departure past that would sample nothing.
MAX_DEPARTURE_DAYS_AHEAD = 14
MAX_DEPARTURE_DAYS_PAST = 1


class ValidationError(ValueError):
    """A request the user can fix. Carries the offending field name."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class PlaceInput:
    """Either free text to geocode, or text that already carries a fix."""

    text: str
    lon: Optional[float] = None
    lat: Optional[float] = None

    @property
    def resolved(self) -> bool:
        return self.lon is not None and self.lat is not None


@dataclass(frozen=True)
class PlanRequest:
    origin: PlaceInput
    destination: PlaceInput
    departure: datetime
    load_lb: float
    spacing_miles: int
    wanted_routes: int


def _place(raw: Any, field: str) -> PlaceInput:
    """Accept ``"Denver, CO"`` or ``{"name": ..., "lon": ..., "lat": ...}``.

    The object form lets the UI's preset city buttons skip the geocoder
    entirely: they already know the coordinate, so a preset plan costs one
    fewer round trip against someone else's free server.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValidationError(field, f"{field} is required")
        return PlaceInput(text=text)

    if isinstance(raw, Mapping):
        text = str(raw.get("name") or raw.get("text") or "").strip()
        lon, lat = raw.get("lon"), raw.get("lat")
        if lon is None or lat is None:
            if not text:
                raise ValidationError(field, f"{field} is required")
            return PlaceInput(text=text)
        try:
            lon_f, lat_f = float(lon), float(lat)
        except (TypeError, ValueError):
            raise ValidationError(field, f"{field} coordinates must be numbers") from None
        if not (-180.0 <= lon_f <= 180.0 and -90.0 <= lat_f <= 90.0):
            raise ValidationError(field, f"{field} coordinates are out of range")
        return PlaceInput(text=text or f"{lat_f:.4f}, {lon_f:.4f}", lon=lon_f, lat=lat_f)

    raise ValidationError(field, f"{field} must be a place name or a coordinate object")


def _departure(raw: Any) -> datetime:
    """Parse an ISO-8601 instant and bound it to the forecast horizon.

    A naive value is read as UTC. The UI always sends an offset, but a curl
    request without one should plan rather than crash.
    """
    if raw in (None, ""):
        return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if not isinstance(raw, str):
        raise ValidationError("departure", "departure must be an ISO-8601 timestamp")
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError(
            "departure", "departure must be an ISO-8601 timestamp, e.g. 2026-10-18T06:00:00Z"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    if parsed < now - timedelta(days=MAX_DEPARTURE_DAYS_PAST):
        raise ValidationError(
            "departure", "departure is too far in the past for a forecast to exist"
        )
    if parsed > now + timedelta(days=MAX_DEPARTURE_DAYS_AHEAD):
        raise ValidationError(
            "departure",
            f"departure must be within {MAX_DEPARTURE_DAYS_AHEAD} days "
            "— the forecast model does not reach further",
        )
    return parsed


def _load_lb(raw: Any) -> float:
    if raw in (None, ""):
        raise ValidationError("load_lb", "load weight is required")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValidationError("load_lb", "load weight must be a number of pounds") from None
    if value < 0:
        raise ValidationError("load_lb", "load weight cannot be negative")
    if value > MAX_LOAD_LB:
        raise ValidationError(
            "load_lb", f"load weight must be at most {MAX_LOAD_LB:,.0f} lb"
        )
    return value


def _spacing(raw: Any) -> int:
    if raw in (None, ""):
        return 25
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        raise ValidationError("spacing_miles", "sampling interval must be a number") from None
    if value not in ALLOWED_SPACINGS_MILES:
        allowed = " / ".join(str(s) for s in ALLOWED_SPACINGS_MILES)
        raise ValidationError(
            "spacing_miles", f"sampling interval must be one of {allowed} miles"
        )
    return value


def _wanted_routes(raw: Any) -> int:
    if raw in (None, ""):
        return 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("routes", "route count must be a number") from None
    if not 1 <= value <= 4:
        raise ValidationError("routes", "route count must be between 1 and 4")
    return value


def parse_plan_request(payload: Mapping[str, Any]) -> PlanRequest:
    """Validate the whole body. Raises :class:`ValidationError` on the first
    field that is wrong, which is the field the form should highlight."""
    if not isinstance(payload, Mapping):
        raise ValidationError("body", "request body must be a JSON object")
    return PlanRequest(
        origin=_place(payload.get("origin"), "origin"),
        destination=_place(payload.get("destination"), "destination"),
        departure=_departure(payload.get("departure")),
        load_lb=_load_lb(payload.get("load_lb")),
        spacing_miles=_spacing(payload.get("spacing_miles")),
        wanted_routes=_wanted_routes(payload.get("routes")),
    )


def check_route_size(distance_miles: float, spacing_miles: int) -> Tuple[bool, str]:
    """Guard against a request that would sample thousands of checkpoints.

    Returned rather than raised: a single over-long candidate among three
    should be dropped, not fail the whole plan.
    """
    if distance_miles > settings.MAX_ROUTE_MILES:
        return False, (
            f"route is {distance_miles:,.0f} miles, beyond the "
            f"{settings.MAX_ROUTE_MILES:,.0f}-mile planning limit"
        )
    expected = int(distance_miles / max(spacing_miles, 1)) + 2
    if expected > settings.MAX_CHECKPOINTS_PER_ROUTE:
        return False, (
            f"{expected} checkpoints at {spacing_miles}-mile spacing exceeds the "
            f"{settings.MAX_CHECKPOINTS_PER_ROUTE} limit — choose a wider interval"
        )
    return True, ""
