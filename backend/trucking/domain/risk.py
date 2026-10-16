"""The risk table and the load rules, implemented exactly as briefed.

The brief states the bands as:

    Wind  Low <25 mph  | Moderate 25-34   | High 35-44   | Severe 45-54   | No Travel >=55 mph
    Rain  Low <0.10    | Moderate .10-.25 | High .25-.50 | Severe .50-1.00| No Travel >1.00 in/hr
    Snow  Low <0.5     | Moderate 0.5-1.0 | High 1.0-2.0 | Severe 2.0-3.0 | No Travel >3.0 in/hr

Two things in that table need a stated reading, because a table written for
a human has edges a program does not get to leave undefined. Both readings
below are the ones that keep every number printed in the brief in the band
the brief puts it in:

1. The wind row is written in whole mph and therefore leaves a gap between
   bands (34 and 35, 44 and 45, 54 and 55). A real anemometer reports 34.6.
   We close each gap upwards, so the bands are half-open:
   ``<25 | [25,35) | [35,45) | [45,55) | >=55``. 34.6 mph is Moderate, which
   is the only reading consistent with "Moderate 25-34" and "High 35-44"
   both being true of their printed endpoints.

2. The rain and snow rows share their endpoints between bands (0.25 ends
   Moderate and starts High). We resolve a shared endpoint to the *lower*
   band, which is the reading that makes the printed "No Travel >1.00"
   strict inequality consistent with the rest of the row. So rain is
   ``<0.10 | [0.10,0.25] | (0.25,0.50] | (0.50,1.00] | >1.00``.

Both decisions are covered by table-driven boundary tests.

The load rules are applied to the wind band only, after classification:

    >=55 mph                      -> No Travel for any load
    45-54 mph and >30,000 lb      -> No Travel
    35-44 mph and >40,000 lb      -> Severe

Note the third rule can only ever hold the level where it already is: the
35-44 band is already High, and the rule raises it to Severe. The first is
already implied by the table; it is implemented anyway so that the rule set
is complete on its own and testable in isolation.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from .models import RiskAssessment, RiskLevel, WeatherSample

# --- thresholds -------------------------------------------------------------
# Each table is (exclusive upper bound, level), scanned in order; a value
# below the bound takes that level, otherwise it falls through to the last.

WIND_BANDS_MPH: Sequence[Tuple[float, RiskLevel]] = (
    (25.0, RiskLevel.LOW),
    (35.0, RiskLevel.MODERATE),
    (45.0, RiskLevel.HIGH),
    (55.0, RiskLevel.SEVERE),
)

# Rain and snow share endpoints with the band below, so the comparison is
# "less than or equal" and the tables carry inclusive upper bounds.
RAIN_BANDS_IN_HR: Sequence[Tuple[float, RiskLevel]] = (
    (0.10, RiskLevel.LOW),      # strictly below 0.10
    (0.25, RiskLevel.MODERATE),  # 0.10 .. 0.25 inclusive
    (0.50, RiskLevel.HIGH),
    (1.00, RiskLevel.SEVERE),
)

SNOW_BANDS_IN_HR: Sequence[Tuple[float, RiskLevel]] = (
    (0.5, RiskLevel.LOW),
    (1.0, RiskLevel.MODERATE),
    (2.0, RiskLevel.HIGH),
    (3.0, RiskLevel.SEVERE),
)

NO_TRAVEL_WIND_MPH = 55.0
HEAVY_LOAD_LB = 30_000.0
VERY_HEAVY_LOAD_LB = 40_000.0
HEAVY_LOAD_WIND_MPH = 45.0
VERY_HEAVY_LOAD_WIND_MPH = 35.0

# Tolerance for float noise at a band edge. 0.001 in/hr and 0.001 mph are
# both far finer than any forecast product resolves, so a value that is
# "0.25 plus a float wobble" is still treated as 0.25.
EPSILON = 1e-6


def classify_wind(wind_mph: float) -> RiskLevel:
    """Wind band. Gaps between the printed whole-mph bands close upwards."""
    for upper, level in WIND_BANDS_MPH:
        if wind_mph < upper - EPSILON:
            return level
    return RiskLevel.NO_TRAVEL


def classify_rain(rain_in_hr: float) -> RiskLevel:
    """Rain band. A value exactly on a shared endpoint takes the lower band."""
    if rain_in_hr < RAIN_BANDS_IN_HR[0][0] - EPSILON:
        return RiskLevel.LOW
    for upper, level in RAIN_BANDS_IN_HR[1:]:
        if rain_in_hr <= upper + EPSILON:
            return level
    return RiskLevel.NO_TRAVEL


def classify_snow(snow_in_hr: float) -> RiskLevel:
    """Snow band. A value exactly on a shared endpoint takes the lower band."""
    if snow_in_hr < SNOW_BANDS_IN_HR[0][0] - EPSILON:
        return RiskLevel.LOW
    for upper, level in SNOW_BANDS_IN_HR[1:]:
        if snow_in_hr <= upper + EPSILON:
            return level
    return RiskLevel.NO_TRAVEL


def apply_load_rules(
    wind_mph: float, wind_level: RiskLevel, load_lb: float
) -> Tuple[RiskLevel, Optional[str]]:
    """Raise the wind band for load weight. Returns (level, rule applied)."""
    if wind_mph >= NO_TRAVEL_WIND_MPH - EPSILON:
        return RiskLevel.NO_TRAVEL, "Wind at or above 55 mph: No Travel for any load"
    if wind_mph >= HEAVY_LOAD_WIND_MPH - EPSILON and load_lb > HEAVY_LOAD_LB + EPSILON:
        return (
            RiskLevel.NO_TRAVEL,
            f"Wind 45-54 mph with load over 30,000 lb ({load_lb:,.0f} lb): No Travel",
        )
    if (
        wind_mph >= VERY_HEAVY_LOAD_WIND_MPH - EPSILON
        and load_lb > VERY_HEAVY_LOAD_LB + EPSILON
    ):
        return (
            RiskLevel.SEVERE,
            f"Wind 35-44 mph with load over 40,000 lb ({load_lb:,.0f} lb): Severe",
        )
    return wind_level, None


def assess(sample: WeatherSample, load_lb: float) -> RiskAssessment:
    """Classify one checkpoint: worst of the three conditions, load applied."""
    wind_level = classify_wind(sample.wind_mph)
    rain_level = classify_rain(sample.rain_in_hr)
    snow_level = classify_snow(sample.snow_in_hr)

    wind_after_load, load_rule = apply_load_rules(sample.wind_mph, wind_level, load_lb)

    # The checkpoint takes the worst of the three conditions. On a tie the
    # order below decides the reported driver, so the answer is stable:
    # wind, then rain, then snow.
    candidates = (
        (wind_after_load, "wind"),
        (rain_level, "rain"),
        (snow_level, "snow"),
    )
    level, driver = max(candidates, key=lambda pair: pair[0])
    if level is RiskLevel.LOW:
        driver = "clear"

    return RiskAssessment(
        level=level,
        wind_level=wind_after_load,
        rain_level=rain_level,
        snow_level=snow_level,
        driver=driver,
        load_rule=load_rule,
    )
