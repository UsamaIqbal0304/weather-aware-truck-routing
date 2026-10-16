"""Unit constants and conversions.

Every value that crosses the domain boundary is in US customary units,
because the risk table in the brief is written in mph, in/hr and lb.
External APIs are asked to deliver those units directly (Open-Meteo
supports ``wind_speed_unit=mph`` and ``precipitation_unit=inch``), so the
only conversion we perform ourselves is metres -> miles for OSRM.
"""

from __future__ import annotations

METRES_PER_MILE = 1609.344
SECONDS_PER_HOUR = 3600.0


def metres_to_miles(metres: float) -> float:
    return metres / METRES_PER_MILE


def miles_to_metres(miles: float) -> float:
    return miles * METRES_PER_MILE
