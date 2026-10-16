"""Aggregation and the brief's preference order.

The order is:
  1. fewest Severe miles
  2. fewest High miles
  3. lowest average risk
  4. shortest travel time

Lexicographic, so each test isolates one criterion by making the earlier
ones tie exactly. That is the property worth testing: a tie must fall
through, not become arbitrary.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from trucking.domain.models import (
    Checkpoint,
    RiskAssessment,
    RiskLevel,
    RouteOption,
    WeatherSample,
)
from trucking.domain.recommend import preference_key, rank, recommend, summarise

DEPARTURE = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)


def checkpoint(index: int, level, covered: float, assessed: bool = True) -> Checkpoint:
    weather = WeatherSample(
        valid_time=DEPARTURE,
        wind_mph=0.0,
        wind_gust_mph=0.0,
        rain_in_hr=0.0,
        snow_in_hr=0.0,
    )
    risk = (
        RiskAssessment(
            level=level,
            wind_level=level,
            rain_level=RiskLevel.LOW,
            snow_level=RiskLevel.LOW,
            driver="wind",
        )
        if assessed
        else None
    )
    return Checkpoint(
        index=index,
        lon=float(index),
        lat=0.0,
        distance_miles=covered * index,
        eta=DEPARTURE + timedelta(hours=index),
        elapsed_hours=float(index),
        covered_miles=covered,
        weather=weather if assessed else None,
        risk=risk,
    )


def route(
    route_id: str,
    levels,
    covered: float = 25.0,
    duration: float = 10.0,
    distance: float = None,
) -> RouteOption:
    checkpoints = [checkpoint(i, lvl, covered) for i, lvl in enumerate(levels)]
    total = distance if distance is not None else covered * len(levels)
    option = RouteOption(
        id=route_id,
        name=route_id,
        source="test",
        distance_miles=total,
        duration_hours=duration,
        geometry=[(0.0, 0.0), (1.0, 0.0)],
        checkpoints=checkpoints,
    )
    option.summary = summarise(checkpoints, total, duration)
    return option


class SummariseTests(SimpleTestCase):
    def test_miles_land_in_the_right_bands(self):
        summary = summarise(
            [
                checkpoint(0, RiskLevel.LOW, 10.0),
                checkpoint(1, RiskLevel.HIGH, 10.0),
                checkpoint(2, RiskLevel.SEVERE, 10.0),
            ],
            distance_miles=30.0,
            duration_hours=1.0,
        )
        self.assertAlmostEqual(summary.low_miles, 10.0)
        self.assertAlmostEqual(summary.high_miles, 10.0)
        self.assertAlmostEqual(summary.severe_miles, 10.0)
        self.assertAlmostEqual(summary.moderate_miles, 0.0)

    def test_average_risk_is_distance_weighted_not_a_plain_mean(self):
        """One Severe checkpoint owning 3 miles must not weigh the same as a
        Low checkpoint owning 300."""
        summary = summarise(
            [
                checkpoint(0, RiskLevel.LOW, 300.0),
                checkpoint(1, RiskLevel.SEVERE, 3.0),
            ],
            distance_miles=303.0,
            duration_hours=5.0,
        )
        plain_mean = (1 + 4) / 2
        self.assertLess(summary.average_risk, plain_mean)
        self.assertAlmostEqual(summary.average_risk, (1 * 300.0 + 4 * 3.0) / 303.0)

    def test_unassessed_miles_are_excluded_from_the_average(self):
        """Miles with no forecast must not be scored Low by default."""
        summary = summarise(
            [
                checkpoint(0, RiskLevel.SEVERE, 10.0),
                checkpoint(1, None, 90.0, assessed=False),
            ],
            distance_miles=100.0,
            duration_hours=2.0,
        )
        self.assertAlmostEqual(summary.unassessed_miles, 90.0)
        self.assertAlmostEqual(summary.assessed_miles, 10.0)
        self.assertAlmostEqual(summary.average_risk, 4.0)
        self.assertAlmostEqual(summary.low_miles, 0.0)

    def test_max_risk_is_the_worst_checkpoint(self):
        summary = summarise(
            [
                checkpoint(0, RiskLevel.LOW, 10.0),
                checkpoint(1, RiskLevel.NO_TRAVEL, 10.0),
                checkpoint(2, RiskLevel.MODERATE, 10.0),
            ],
            distance_miles=30.0,
            duration_hours=1.0,
        )
        self.assertIs(summary.max_risk, RiskLevel.NO_TRAVEL)

    def test_a_route_with_no_assessed_checkpoint_has_zero_average(self):
        summary = summarise(
            [checkpoint(0, None, 10.0, assessed=False)],
            distance_miles=10.0,
            duration_hours=1.0,
        )
        self.assertEqual(summary.average_risk, 0.0)
        self.assertEqual(summary.assessed_miles, 0.0)


class PreferenceOrderTests(SimpleTestCase):
    def test_criterion_1_severe_miles_dominates_everything_else(self):
        """Fewer severe miles wins even when the route is far slower and
        carries more high miles."""
        safe = route("safe", [RiskLevel.HIGH] * 8, duration=30.0)
        fast = route("fast", [RiskLevel.SEVERE, RiskLevel.LOW], duration=4.0)
        self.assertEqual([r.id for r in rank([fast, safe])], ["safe", "fast"])

    def test_criterion_2_high_miles_decides_when_severe_ties(self):
        a = route("a", [RiskLevel.SEVERE, RiskLevel.LOW, RiskLevel.LOW], duration=20.0)
        b = route("b", [RiskLevel.SEVERE, RiskLevel.HIGH, RiskLevel.LOW], duration=5.0)
        self.assertEqual([r.id for r in rank([b, a])], ["a", "b"])

    def test_criterion_3_average_risk_decides_when_miles_tie(self):
        """Both have zero severe and zero high miles, and the same length;
        the one with moderate instead of low miles must lose."""
        calm = route("calm", [RiskLevel.LOW, RiskLevel.LOW], duration=9.0)
        breezy = route("breezy", [RiskLevel.LOW, RiskLevel.MODERATE], duration=8.0)
        self.assertEqual([r.id for r in rank([breezy, calm])], ["calm", "breezy"])

    def test_criterion_4_travel_time_decides_when_risk_ties(self):
        slow = route("slow", [RiskLevel.LOW, RiskLevel.LOW], duration=12.0)
        quick = route("quick", [RiskLevel.LOW, RiskLevel.LOW], duration=9.0)
        self.assertEqual([r.id for r in rank([slow, quick])], ["quick", "slow"])

    def test_a_full_tie_keeps_the_engines_order(self):
        """Stable sort, so the output is reproducible rather than arbitrary."""
        first = route("first", [RiskLevel.LOW, RiskLevel.LOW], duration=10.0)
        second = route("second", [RiskLevel.LOW, RiskLevel.LOW], duration=10.0)
        self.assertEqual([r.id for r in rank([first, second])], ["first", "second"])
        self.assertEqual([r.id for r in rank([second, first])], ["second", "first"])

    def test_key_is_the_four_criteria_in_order(self):
        key = preference_key(route("r", [RiskLevel.SEVERE, RiskLevel.HIGH], duration=7.5))
        self.assertEqual(len(key), 4)
        self.assertAlmostEqual(key[0], 25.0)  # severe miles
        self.assertAlmostEqual(key[1], 25.0)  # high miles
        self.assertAlmostEqual(key[3], 7.5)  # duration

    def test_a_route_without_a_summary_sorts_last(self):
        broken = RouteOption(
            id="broken",
            name="broken",
            source="test",
            distance_miles=10.0,
            duration_hours=1.0,
            geometry=[(0.0, 0.0), (1.0, 0.0)],
        )
        ok = route("ok", [RiskLevel.SEVERE] * 4, duration=40.0)
        self.assertEqual([r.id for r in rank([broken, ok])], ["ok", "broken"])

    def test_ranking_is_deterministic(self):
        routes = [
            route("a", [RiskLevel.LOW, RiskLevel.MODERATE], duration=10.0),
            route("b", [RiskLevel.LOW, RiskLevel.LOW], duration=11.0),
            route("c", [RiskLevel.HIGH, RiskLevel.LOW], duration=9.0),
        ]
        expected = [r.id for r in rank(routes)]
        for _ in range(5):
            self.assertEqual([r.id for r in rank(routes)], expected)


class RecommendTests(SimpleTestCase):
    def test_a_no_travel_route_is_ranked_but_not_recommended(self):
        blocked = route("blocked", [RiskLevel.NO_TRAVEL, RiskLevel.LOW], duration=5.0)
        open_route = route("open", [RiskLevel.HIGH, RiskLevel.HIGH], duration=20.0)
        choice, ranked, warning = recommend([blocked, open_route])
        self.assertEqual(choice.id, "open")
        self.assertIn("blocked", [r.id for r in ranked])
        self.assertIsNotNone(warning)

    def test_literal_reading_can_be_requested(self):
        """skip_blocked=False applies the brief's four criteria as printed,
        with no special case for No Travel."""
        blocked = route("blocked", [RiskLevel.NO_TRAVEL, RiskLevel.LOW], duration=5.0)
        open_route = route("open", [RiskLevel.SEVERE, RiskLevel.SEVERE], duration=20.0)
        choice, _, warning = recommend([blocked, open_route], skip_blocked=False)
        self.assertEqual(choice.id, "blocked")
        self.assertIsNone(warning)

    def test_every_route_blocked_still_returns_a_ranking_and_says_so(self):
        a = route("a", [RiskLevel.NO_TRAVEL], duration=5.0)
        b = route("b", [RiskLevel.NO_TRAVEL], duration=6.0)
        choice, ranked, warning = recommend([a, b])
        self.assertIsNotNone(choice)
        self.assertEqual(len(ranked), 2)
        self.assertIn("No departure", warning)

    def test_no_candidates_recommends_nothing(self):
        choice, ranked, warning = recommend([])
        self.assertIsNone(choice)
        self.assertEqual(ranked, [])
        self.assertIsNone(warning)

    def test_no_warning_when_nothing_was_excluded(self):
        a = route("a", [RiskLevel.LOW], duration=5.0)
        b = route("b", [RiskLevel.MODERATE], duration=4.0)
        _, _, warning = recommend([a, b])
        self.assertIsNone(warning)
