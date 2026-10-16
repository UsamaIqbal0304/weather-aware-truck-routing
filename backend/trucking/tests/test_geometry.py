"""Polyline helpers. Checked against distances that can be verified by hand."""

from __future__ import annotations

from django.test import SimpleTestCase

from trucking.domain.geometry import (
    cumulative,
    frechet_like_similarity,
    haversine_miles,
    interpolate,
    locate,
    perpendicular_offset,
    simplify,
)

CHICAGO = (-87.6298, 41.8781)
DENVER = (-104.9903, 39.7392)


class HaversineTests(SimpleTestCase):
    def test_known_city_pair(self):
        """Chicago to Denver great-circle is ~920 statute miles."""
        self.assertAlmostEqual(haversine_miles(CHICAGO, DENVER), 920.0, delta=5.0)

    def test_one_degree_of_latitude_is_about_69_miles(self):
        self.assertAlmostEqual(haversine_miles((0.0, 0.0), (0.0, 1.0)), 69.09, delta=0.05)

    def test_identical_points_are_zero(self):
        self.assertEqual(haversine_miles(CHICAGO, CHICAGO), 0.0)

    def test_symmetric(self):
        self.assertAlmostEqual(
            haversine_miles(CHICAGO, DENVER), haversine_miles(DENVER, CHICAGO), places=9
        )


class CumulativeTests(SimpleTestCase):
    def test_leading_zero_and_running_total(self):
        self.assertEqual(cumulative([2.0, 3.0, 5.0]), [0.0, 2.0, 5.0, 10.0])

    def test_empty_input_is_a_single_zero(self):
        self.assertEqual(cumulative([]), [0.0])


class InterpolateTests(SimpleTestCase):
    def test_midpoint(self):
        self.assertEqual(interpolate((0.0, 0.0), (10.0, 20.0), 0.5), (5.0, 10.0))

    def test_endpoints(self):
        self.assertEqual(interpolate((1.0, 2.0), (3.0, 4.0), 0.0), (1.0, 2.0))
        self.assertEqual(interpolate((1.0, 2.0), (3.0, 4.0), 1.0), (3.0, 4.0))

    def test_fraction_is_clamped(self):
        self.assertEqual(interpolate((0.0, 0.0), (10.0, 0.0), 5.0), (10.0, 0.0))
        self.assertEqual(interpolate((0.0, 0.0), (10.0, 0.0), -3.0), (0.0, 0.0))


class LocateTests(SimpleTestCase):
    CUM = [0.0, 10.0, 20.0, 30.0]

    def test_inside_a_segment(self):
        self.assertEqual(locate(self.CUM, 15.0), (1, 0.5))

    def test_on_a_vertex_takes_the_following_segment(self):
        self.assertEqual(locate(self.CUM, 10.0), (1, 0.0))

    def test_before_the_start_clamps(self):
        self.assertEqual(locate(self.CUM, -5.0), (0, 0.0))

    def test_past_the_end_clamps_to_the_last_segment(self):
        self.assertEqual(locate(self.CUM, 99.0), (2, 1.0))

    def test_degenerate_input(self):
        self.assertEqual(locate([0.0], 5.0), (0, 0.0))

    def test_a_duplicate_vertex_is_skipped_not_divided_by(self):
        """Routing engines emit repeated vertices. bisect_right lands past
        the duplicate, so the zero-length segment is never the one chosen
        and the fraction is never 0/0."""
        self.assertEqual(locate([0.0, 10.0, 10.0, 20.0], 10.0), (2, 0.0))


class SimplifyTests(SimpleTestCase):
    def test_endpoints_are_preserved(self):
        coords = [(float(i), 0.0) for i in range(1000)]
        out = simplify(coords, 50)
        self.assertEqual(len(out), 50)
        self.assertEqual(out[0], coords[0])
        self.assertEqual(out[-1], coords[-1])

    def test_short_input_is_returned_unchanged(self):
        coords = [(0.0, 0.0), (1.0, 1.0)]
        self.assertEqual(simplify(coords, 50), coords)

    def test_order_is_kept(self):
        coords = [(float(i), 0.0) for i in range(500)]
        lons = [p[0] for p in simplify(coords, 30)]
        self.assertEqual(lons, sorted(lons))


class SimilarityTests(SimpleTestCase):
    def test_a_line_is_identical_to_itself(self):
        line = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
        self.assertAlmostEqual(frechet_like_similarity(line, line), 0.0, places=6)

    def test_parallel_lines_separate_by_their_offset(self):
        a = [(0.0, 0.0), (2.0, 0.0)]
        b = [(0.0, 1.0), (2.0, 1.0)]
        # One degree of latitude is ~69 miles.
        self.assertAlmostEqual(frechet_like_similarity(a, b), 69.0, delta=1.0)

    def test_empty_input_is_infinitely_far(self):
        self.assertEqual(frechet_like_similarity([], [(0.0, 0.0)]), float("inf"))


class PerpendicularOffsetTests(SimpleTestCase):
    def test_offset_is_the_requested_distance_away(self):
        midpoint = (-96.0, 40.8)
        shifted = perpendicular_offset(CHICAGO, DENVER, midpoint, 60.0)
        self.assertAlmostEqual(haversine_miles(midpoint, shifted), 60.0, delta=2.0)

    def test_opposite_signs_land_on_opposite_sides(self):
        midpoint = (-96.0, 40.8)
        left = perpendicular_offset(CHICAGO, DENVER, midpoint, 60.0)
        right = perpendicular_offset(CHICAGO, DENVER, midpoint, -60.0)
        self.assertAlmostEqual(haversine_miles(left, right), 120.0, delta=4.0)

    def test_a_zero_length_bearing_returns_the_point(self):
        point = (-96.0, 40.8)
        self.assertEqual(perpendicular_offset(point, point, point, 50.0), point)
