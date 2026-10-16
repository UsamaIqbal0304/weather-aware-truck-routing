"""Hourly forecasts, via Open-Meteo.

Open-Meteo is the right fit for this problem for three reasons: it needs
no API key at all, it answers for many coordinates in a single request,
and it returns an hourly series rather than a "current conditions" blob —
which is what lets a checkpoint be scored at its estimated arrival time
instead of at departure.

Two choices worth naming:

* The API is asked for mph and inches directly (``wind_speed_unit=mph``,
  ``precipitation_unit=inch``), so the numbers the risk table compares are
  the numbers the service returned. No conversion sits between the
  forecast and the threshold.
* ``rain`` and ``snowfall`` are requested separately rather than the
  combined ``precipitation`` field, because the brief scores rain and snow
  on different scales. Using ``precipitation`` for the rain axis would
  score melted snow as rain.

Caching is per grid cell, not per request: coordinates are rounded to a
~1 km grid and each cell's whole hourly series is cached under its own
key. Three candidate routes over one corridor overlap heavily, so most
cells are already in cache by the time the second route is sampled.
Open-Meteo's free tier is for non-commercial use under 10,000 calls a day
(https://open-meteo.com/en/terms); batching plus per-cell caching keeps a
full three-route plan at a handful of calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from django.conf import settings
from django.core.cache import cache

from ..domain.models import Coord, WeatherSample
from .http import UpstreamError, cache_key, get_json

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Only the columns the risk table and the UI actually read. "precipitation"
# is deliberately absent: it lumps rain and melted snow into one number, and
# the brief scores those two on different scales, so asking for it would cost
# a sixth of every response for a field we must not use.
HOURLY_FIELDS = (
    "rain",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
    "temperature_2m",
)

# Open-Meteo publishes 16 days of forecast; one day of history is kept so a
# departure earlier today still resolves.
MAX_FORECAST_DAYS = 15
MAX_PAST_DAYS = 1


@dataclass(frozen=True)
class HourlySeries:
    """One grid cell's hourly forecast."""

    lon: float
    lat: float
    start: datetime
    wind_mph: Tuple[float, ...]
    gust_mph: Tuple[float, ...]
    rain_in: Tuple[float, ...]
    snow_in: Tuple[float, ...]
    temp_f: Tuple[float, ...]

    def __len__(self) -> int:
        return len(self.wind_mph)

    def index_for(self, when: datetime) -> Optional[int]:
        """Index of the forecast hour nearest ``when``, or None if outside.

        Nearest rather than floor: a truck arriving at 10:58 meets the 11:00
        forecast, not the 10:00 one.
        """
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        offset_hours = (when - self.start).total_seconds() / 3600.0
        idx = int(round(offset_hours))
        if idx < 0 or idx >= len(self):
            return None
        return idx

    def at(self, when: datetime) -> Optional[WeatherSample]:
        idx = self.index_for(when)
        if idx is None:
            return None
        return self.sample(idx)

    def sample(self, idx: int) -> Optional[WeatherSample]:
        if idx < 0 or idx >= len(self):
            return None
        return WeatherSample(
            valid_time=self.start + timedelta(hours=idx),
            wind_mph=self.wind_mph[idx],
            wind_gust_mph=self.gust_mph[idx],
            rain_in_hr=self.rain_in[idx],
            snow_in_hr=self.snow_in[idx],
            temperature_f=self.temp_f[idx] if idx < len(self.temp_f) else None,
        )


def grid_round(coord: Coord, decimals: Optional[int] = None) -> Coord:
    """Snap a coordinate to the caching grid.

    Two decimal places is about 1.1 km of latitude — far finer than the
    ~2-11 km native resolution of the models Open-Meteo blends, so the snap
    costs no accuracy while collapsing the many near-identical points that
    three overlapping routes produce onto shared cache keys.
    """
    places = settings.WEATHER_GRID_DECIMALS if decimals is None else decimals
    return (round(coord[0], places), round(coord[1], places))


def _window(start: datetime, end: datetime) -> Tuple[date, date]:
    """Clamp a requested time window to the dates Open-Meteo will serve."""
    today = datetime.now(timezone.utc).date()
    first = max(start.astimezone(timezone.utc).date(), today - timedelta(days=MAX_PAST_DAYS))
    last = min(end.astimezone(timezone.utc).date(), today + timedelta(days=MAX_FORECAST_DAYS))
    if last < first:
        last = first
    return first, last


def _series_cache_key(coord: Coord, first: date, last: date) -> str:
    return cache_key(
        "openmeteo",
        OPEN_METEO_URL,
        {"lon": coord[0], "lat": coord[1], "from": first.isoformat(), "to": last.isoformat()},
    )


def _parse_series(entry: dict, coord: Coord) -> Optional[HourlySeries]:
    hourly = entry.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    def column(name: str) -> Tuple[float, ...]:
        values = hourly.get(name) or []
        return tuple(0.0 if v is None else float(v) for v in values)

    start = datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc)
    return HourlySeries(
        lon=coord[0],
        lat=coord[1],
        start=start,
        wind_mph=column("wind_speed_10m"),
        gust_mph=column("wind_gusts_10m"),
        rain_in=column("rain"),
        snow_in=column("snowfall"),
        temp_f=column("temperature_2m"),
    )


def _chunks(items: Sequence[Coord], size: int) -> Iterable[Sequence[Coord]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_series(
    coords: Sequence[Coord], start: datetime, end: datetime
) -> Dict[Coord, HourlySeries]:
    """Hourly forecasts for every coordinate, keyed by its grid cell.

    Cache is consulted per cell first; only the misses are requested, in
    batches. The returned mapping is keyed by the *rounded* coordinate, so
    callers must round before looking up — use :func:`grid_round`.
    """
    if not coords:
        return {}

    first, last = _window(start, end)
    unique: List[Coord] = []
    seen = set()
    for coord in coords:
        cell = grid_round(coord)
        if cell not in seen:
            seen.add(cell)
            unique.append(cell)

    found: Dict[Coord, HourlySeries] = {}
    misses: List[Coord] = []
    for cell in unique:
        hit = cache.get(_series_cache_key(cell, first, last))
        if hit is not None:
            found[cell] = hit
        else:
            misses.append(cell)

    logger.info(
        "weather: %d cells, %d cached, %d to fetch", len(unique), len(found), len(misses)
    )

    for batch in _chunks(misses, settings.WEATHER_BATCH_SIZE):
        params = {
            "latitude": ",".join(f"{lat:.4f}" for _, lat in batch),
            "longitude": ",".join(f"{lon:.4f}" for lon, _ in batch),
            "hourly": ",".join(HOURLY_FIELDS),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "temperature_unit": "fahrenheit",
            "timezone": "UTC",
            "start_date": first.isoformat(),
            "end_date": last.isoformat(),
        }
        # The batch itself is not cached: each cell is cached separately
        # below, so a different mix of the same cells still hits.
        payload = get_json(
            "openmeteo-batch",
            OPEN_METEO_URL,
            params,
            ttl=0,
            min_interval=settings.OPEN_METEO_MIN_INTERVAL_SECONDS,
        )
        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) != len(batch):
            raise UpstreamError(
                "openmeteo",
                f"asked for {len(batch)} locations, got {len(entries)}",
            )
        for cell, entry in zip(batch, entries):
            series = _parse_series(entry, cell)
            if series is None:
                continue
            found[cell] = series
            cache.set(
                _series_cache_key(cell, first, last),
                series,
                settings.CACHE_TTL_WEATHER,
            )

    return found


def lookup(series: Dict[Coord, HourlySeries], coord: Coord) -> Optional[HourlySeries]:
    """Fetch a cell's series for an unrounded coordinate."""
    return series.get(grid_round(coord))
