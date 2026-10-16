"""Checkpoint placement, mile attribution, and ETAs.

The invariant worth protecting is that the per-checkpoint spans partition
the route exactly. 'Severe miles' is a sum over those spans, so if they
overlapped or left gaps the headline number in the UI would be wrong in a
way no individual checkpoint looks wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from trucking.domain.models import RawRoute
from trucking.domain.sampling import (
    ALLOWED_SPACINGS_MILES,
    checkpoint_distances,
    corridor_points,
    covered_miles,
    sample_route,
)

DEPARTURE = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)


def straight_route(total_miles: float, hours: float, vertices: int = 101) -> RawRoute:
    """A due-east line at the equator, split into equal segments.

    Equal segments mean elapsed time is linear in distance, so an ETA can
    be checked against an exact expected value rather than a tolerance.
    """
    # 1 degree of longitude at the equator is ~69.09 miles.
    span_deg = total_miles / 69.0932
    coords = [(span_deg * i / (vertices - 1), 0.0) for i in range(vertices)]
    seg_miles = [total_miles / (vertices - 1)] * (vertices - 1)
    seg_hours = [hours / (vertices - 1)] * (vertices - 1)
    return RawRoute(
        geometry=coords,
        distance_miles=total_miles,
        duration_hours=hours,
        segment_miles=seg_miles,
        segment_hours=seg_hours,
        source="test",
    )


class CheckpointDistanceTests(SimpleTestCase):
    def test_brief_spacings_are_the_allowed_set(self):
        self.assertEqual(ALLOWED_SPACINGS_MILES, (10, 25, 50))

    def test_origin_is_always_sampled(self):
        for spacing in ALLOWED_SPACINGS_MILES:
            with self.subTest(spacing=spacing):
                self.assertEqual(checkpoint_distances(137.0, spacing)[0], 0.0)

    def test_destination_is_always_sampled(self):
        for spacing in ALLOWED_SPACINGS_MILES:
            with self.subTest(spacing=spacing):
                self.assertAlmostEqual(checkpoint_distances(137.0, spacing)[-1], 137.0)

    def test_exact_multiple_does_not_duplicate_the_end(self):
        marks = checkpoint_distances(100.0, 25.0)
        self.assertEqual(marks, [0.0, 25.0, 50.0, 75.0, 100.0])

    def test_a_crowded_tail_is_absorbed_rather_than_added(self):
        """100.5 miles at 25-mile spacing should not put a checkpoint half a
        mile after the one at 100."""
        marks = checkpoint_distances(100.5, 25.0)
        self.assertEqual(marks, [0.0, 25.0, 50.0, 75.0, 100.5])

    def test_trip_shorter_than_one_interval_still_has_both_ends(self):
        self.assertEqual(checkpoint_distances(4.0, 50.0), [0.0, 4.0])

    def test_zero_length_trip_yields_one_mark(self):
        self.assertEqual(checkpoint_distances(0.0, 10.0), [0.0])

    def test_non_positive_spacing_is_rejected(self):
        for bad in (0.0, -10.0):
            with self.subTest(spacing=bad):
                with self.assertRaises(ValueError):
                    checkpoint_distances(100.0, bad)

    def test_count_matches_spacing(self):
        """A 1,000-mile route gives roughly 100 / 40 / 20 checkpoints."""
        self.assertEqual(len(checkpoint_distances(1000.0, 10.0)), 101)
        self.assertEqual(len(checkpoint_distances(1000.0, 25.0)), 41)
        self.assertEqual(len(checkpoint_distances(1000.0, 50.0)), 21)


class CoveredMilesTests(SimpleTestCase):
    def test_spans_sum_to_the_route_length(self):
        for total in (4.0, 100.0, 100.5, 1005.1):
            for spacing in ALLOWED_SPACINGS_MILES:
                with self.subTest(total=total, spacing=spacing):
                    marks = checkpoint_distances(total, spacing)
                    self.assertAlmostEqual(sum(covered_miles(marks, total)), total, places=6)

    def test_interior_checkpoints_own_one_full_interval(self):
        marks = checkpoint_distances(100.0, 25.0)
        spans = covered_miles(marks, 100.0)
        self.assertAlmostEqual(spans[1], 25.0)
        self.assertAlmostEqual(spans[2], 25.0)

    def test_endpoints_own_a_half_interval(self):
        marks = checkpoint_distances(100.0, 25.0)
        spans = covered_miles(marks, 100.0)
        self.assertAlmostEqual(spans[0], 12.5)
        self.assertAlmostEqual(spans[-1], 12.5)

    def test_no_span_is_negative(self):
        marks = checkpoint_distances(1005.1, 50.0)
        self.assertTrue(all(s >= 0.0 for s in covered_miles(marks, 1005.1)))

    def test_single_checkpoint_owns_everything(self):
        self.assertEqual(covered_miles([0.0], 12.0), [12.0])


class SampleRouteTests(SimpleTestCase):
    def test_eta_uses_the_engines_own_durations(self):
        """A 600-mile, 10-hour route sampled every 50 miles puts the
        checkpoint at mile 300 exactly 5 hours after departure."""
        route = straight_route(600.0, 10.0, vertices=601)
        checkpoints = sample_route(route, DEPARTURE, 50.0)
        at_300 = next(cp for cp in checkpoints if abs(cp.distance_miles - 300.0) < 1e-6)
        self.assertAlmostEqual(at_300.elapsed_hours, 5.0, places=6)
        self.assertEqual(at_300.eta, DEPARTURE + timedelta(hours=5))

    def test_first_checkpoint_is_at_departure(self):
        checkpoints = sample_route(straight_route(600.0, 10.0), DEPARTURE, 25.0)
        self.assertEqual(checkpoints[0].eta, DEPARTURE)
        self.assertAlmostEqual(checkpoints[0].elapsed_hours, 0.0)

    def test_last_checkpoint_is_at_arrival(self):
        checkpoints = sample_route(straight_route(600.0, 10.0), DEPARTURE, 25.0)
        self.assertAlmostEqual(checkpoints[-1].elapsed_hours, 10.0, places=6)

    def test_etas_increase_monotonically(self):
        checkpoints = sample_route(straight_route(1005.0, 17.8), DEPARTURE, 10.0)
        elapsed = [cp.elapsed_hours for cp in checkpoints]
        self.assertEqual(elapsed, sorted(elapsed))

    def test_checkpoints_lie_on_the_route(self):
        """Interpolated points stay on the line they were interpolated along."""
        route = straight_route(600.0, 10.0)
        for cp in sample_route(route, DEPARTURE, 25.0):
            with self.subTest(mile=cp.distance_miles):
                self.assertAlmostEqual(cp.lat, 0.0, places=9)
                self.assertGreaterEqual(cp.lon, route.geometry[0][0] - 1e-9)
                self.assertLessEqual(cp.lon, route.geometry[-1][0] + 1e-9)

    def test_indices_are_sequential(self):
        checkpoints = sample_route(straight_route(300.0, 5.0), DEPARTURE, 50.0)
        self.assertEqual([cp.index for cp in checkpoints], list(range(len(checkpoints))))

    def test_spans_sum_to_the_route_length(self):
        route = straight_route(1005.1, 17.8)
        checkpoints = sample_route(route, DEPARTURE, 25.0)
        self.assertAlmostEqual(
            sum(cp.covered_miles for cp in checkpoints), 1005.1, places=4
        )

    def test_a_degenerate_route_is_rejected(self):
        route = RawRoute(
            geometry=[(0.0, 0.0)],
            distance_miles=0.0,
            duration_hours=0.0,
            segment_miles=[],
            segment_hours=[],
        )
        with self.assertRaises(ValueError):
            sample_route(route, DEPARTURE, 10.0)

    def test_sampling_is_deterministic(self):
        route = straight_route(777.0, 13.5)
        first = [(cp.lon, cp.lat, cp.elapsed_hours) for cp in sample_route(route, DEPARTURE, 25.0)]
        for _ in range(3):
            again = [
                (cp.lon, cp.lat, cp.elapsed_hours)
                for cp in sample_route(route, DEPARTURE, 25.0)
            ]
            self.assertEqual(first, again)


class CorridorTests(SimpleTestCase):
    def test_corridor_is_capped_and_spans_the_route(self):
        route = straight_route(1000.0, 17.0)
        points = corridor_points(route, 60)
        self.assertEqual(len(points), 60)
        self.assertAlmostEqual(points[0][0], route.geometry[0][0], places=6)
        self.assertAlmostEqual(points[-1][0], route.geometry[-1][0], places=6)

    def test_corridor_points_advance(self):
        points = corridor_points(straight_route(1000.0, 17.0), 25)
        lons = [p[0] for p in points]
        self.assertEqual(lons, sorted(lons))
