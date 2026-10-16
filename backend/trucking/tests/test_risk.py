"""The risk table, tested at every printed threshold and either side of it.

These are the numbers the brief hands over verbatim, so the tests are
table-driven against the brief's own rows rather than written as prose
assertions. If a band moves, exactly one tuple changes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.test import SimpleTestCase

from trucking.domain.models import RiskLevel, WeatherSample
from trucking.domain.risk import (
    apply_load_rules,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
)

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def sample(wind=0.0, rain=0.0, snow=0.0, gust=None) -> WeatherSample:
    return WeatherSample(
        valid_time=datetime(2026, 10, 18, 6, tzinfo=timezone.utc),
        wind_mph=wind,
        wind_gust_mph=wind if gust is None else gust,
        rain_in_hr=rain,
        snow_in_hr=snow,
        temperature_f=40.0,
    )


class WindBandTests(SimpleTestCase):
    """Brief: Low <25 | Moderate 25-34 | High 35-44 | Severe 45-54 | No Travel >=55."""

    CASES = (
        (0.0, L),
        (24.9, L),
        (24.999, L),
        (25.0, M),  # band start is inclusive
        (30.0, M),
        (34.0, M),
        (34.6, M),  # the gap between printed bands closes upwards
        (34.999, M),
        (35.0, H),
        (44.9, H),
        (45.0, S),
        (54.9, S),
        (55.0, N),  # No Travel is >=55, so 55.0 itself is No Travel
        (120.0, N),
    )

    def test_bands(self):
        for mph, expected in self.CASES:
            with self.subTest(mph=mph):
                self.assertIs(classify_wind(mph), expected)


class RainBandTests(SimpleTestCase):
    """Brief: Low <0.10 | Moderate 0.10-0.25 | High 0.25-0.50 | Severe 0.50-1.00 | No Travel >1.00.

    The rows share endpoints, so a value exactly on one takes the lower
    band. That is the reading on which 'No Travel >1.00' is strict.
    """

    CASES = (
        (0.0, L),
        (0.099, L),
        (0.10, M),
        (0.20, M),
        (0.25, M),  # shared endpoint -> lower band
        (0.2501, H),
        (0.40, H),
        (0.50, H),  # shared endpoint -> lower band
        (0.5001, S),
        (0.99, S),
        (1.00, S),  # shared endpoint -> lower band, so 1.00 is not No Travel
        (1.0001, N),
        (3.0, N),
    )

    def test_bands(self):
        for in_hr, expected in self.CASES:
            with self.subTest(rain=in_hr):
                self.assertIs(classify_rain(in_hr), expected)


class SnowBandTests(SimpleTestCase):
    """Brief: Low <0.5 | Moderate 0.5-1.0 | High 1.0-2.0 | Severe 2.0-3.0 | No Travel >3.0."""

    CASES = (
        (0.0, L),
        (0.49, L),
        (0.5, M),
        (1.0, M),  # shared endpoint -> lower band
        (1.01, H),
        (2.0, H),  # shared endpoint -> lower band
        (2.01, S),
        (3.0, S),  # shared endpoint -> lower band
        (3.01, N),
        (10.0, N),
    )

    def test_bands(self):
        for in_hr, expected in self.CASES:
            with self.subTest(snow=in_hr):
                self.assertIs(classify_snow(in_hr), expected)


class FloatNoiseTests(SimpleTestCase):
    """A threshold reached by arithmetic must land in the same band as the
    literal. 0.1 + 0.15 is 0.24999999999999997 in binary floating point, and
    without the epsilon that would classify one band low."""

    def test_rain_endpoint_reached_by_addition(self):
        self.assertIs(classify_rain(0.1 + 0.15), classify_rain(0.25))

    def test_wind_endpoint_reached_by_division(self):
        self.assertIs(classify_wind(110.0 / 2.0), classify_wind(55.0))


class LoadRuleTests(SimpleTestCase):
    """Brief's load rules:
    >=55 mph -> No Travel for any load
    45-54 mph + >30,000 lb -> No Travel
    35-44 mph + >40,000 lb -> Severe
    """

    def test_55_mph_blocks_any_load(self):
        for load in (0.0, 1_000.0, 80_000.0):
            with self.subTest(load=load):
                level, rule = apply_load_rules(55.0, classify_wind(55.0), load)
                self.assertIs(level, N)
                self.assertIsNotNone(rule)

    def test_45_to_54_blocks_over_30000(self):
        level, rule = apply_load_rules(48.0, classify_wind(48.0), 30_001.0)
        self.assertIs(level, N)
        self.assertIn("30,000", rule)

    def test_45_to_54_at_exactly_30000_stays_severe(self):
        """The rule says '>30,000 lb'. At the boundary the table stands."""
        level, rule = apply_load_rules(48.0, classify_wind(48.0), 30_000.0)
        self.assertIs(level, S)
        self.assertIsNone(rule)

    def test_35_to_44_over_40000_becomes_severe(self):
        level, rule = apply_load_rules(40.0, classify_wind(40.0), 40_001.0)
        self.assertIs(level, S)
        self.assertIn("40,000", rule)

    def test_35_to_44_at_exactly_40000_stays_high(self):
        level, rule = apply_load_rules(40.0, classify_wind(40.0), 40_000.0)
        self.assertIs(level, H)
        self.assertIsNone(rule)

    def test_light_load_never_raised_below_45(self):
        for mph in (0.0, 24.0, 30.0, 44.0):
            with self.subTest(mph=mph):
                level, rule = apply_load_rules(mph, classify_wind(mph), 5_000.0)
                self.assertIs(level, classify_wind(mph))
                self.assertIsNone(rule)

    def test_rules_do_not_lower_a_band(self):
        """A heavy load can only make a checkpoint worse, never better."""
        for mph in range(0, 70, 1):
            for load in (0.0, 35_000.0, 45_000.0, 80_000.0):
                with self.subTest(mph=mph, load=load):
                    base = classify_wind(float(mph))
                    level, _ = apply_load_rules(float(mph), base, load)
                    self.assertGreaterEqual(int(level), int(base))


class AssessTests(SimpleTestCase):
    def test_worst_condition_wins(self):
        result = assess(sample(wind=10.0, rain=0.6, snow=0.0), 20_000.0)
        self.assertIs(result.level, S)
        self.assertEqual(result.driver, "rain")

    def test_snow_can_drive_the_level(self):
        result = assess(sample(wind=10.0, rain=0.0, snow=2.5), 20_000.0)
        self.assertIs(result.level, S)
        self.assertEqual(result.driver, "snow")

    def test_calm_weather_is_low_and_clear(self):
        result = assess(sample(wind=5.0, rain=0.0, snow=0.0), 20_000.0)
        self.assertIs(result.level, L)
        self.assertEqual(result.driver, "clear")

    def test_load_rule_is_reported_on_the_assessment(self):
        result = assess(sample(wind=40.0), 45_000.0)
        self.assertIs(result.level, S)
        self.assertIsNotNone(result.load_rule)
        self.assertEqual(result.driver, "wind")

    def test_no_travel_wind_beats_a_worse_looking_rain(self):
        """No Travel is the top of the scale, so nothing outranks it."""
        result = assess(sample(wind=60.0, rain=2.0), 10_000.0)
        self.assertIs(result.level, N)

    def test_component_levels_are_reported_separately(self):
        result = assess(sample(wind=30.0, rain=0.3, snow=0.6), 10_000.0)
        self.assertIs(result.wind_level, M)
        self.assertIs(result.rain_level, H)
        self.assertIs(result.snow_level, M)
        self.assertIs(result.level, H)

    def test_assess_is_deterministic(self):
        s = sample(wind=37.3, rain=0.26, snow=0.51)
        first = assess(s, 41_000.0)
        for _ in range(5):
            again = assess(s, 41_000.0)
            self.assertEqual(first, again)
