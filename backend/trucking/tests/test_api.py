"""Validation and the HTTP contract.

Every upstream is replaced with a fixture, so the suite runs offline and
the same input always produces the same plan. Nothing here is seeded
randomness because nothing here is random: the stub forecast is a
deterministic function of longitude, which is what lets a test assert an
exact recommendation rather than 'something reasonable'.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase

from trucking.api.validation import ValidationError, parse_plan_request
from trucking.domain.models import RawRoute
from trucking.services.weather import HourlySeries, grid_round

DEPARTURE = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)
HORIZON_HOURS = 120


def _line(lon_from: float, lon_to: float, lat: float, vertices: int = 201):
    step = (lon_to - lon_from) / (vertices - 1)
    return [(lon_from + step * i, lat) for i in range(vertices)]


def _route(lat: float, miles: float, hours: float, vertices: int = 201) -> RawRoute:
    geometry = _line(-90.0, -100.0, lat, vertices)
    return RawRoute(
        geometry=geometry,
        distance_miles=miles,
        duration_hours=hours,
        segment_miles=[miles / (vertices - 1)] * (vertices - 1),
        segment_hours=[hours / (vertices - 1)] * (vertices - 1),
        source="stub",
    )


def _series(coord, wind: float, rain: float = 0.0, snow: float = 0.0) -> HourlySeries:
    hours = HORIZON_HOURS
    return HourlySeries(
        lon=coord[0],
        lat=coord[1],
        start=DEPARTURE.replace(minute=0, second=0, microsecond=0),
        wind_mph=tuple([wind] * hours),
        gust_mph=tuple([wind * 1.3] * hours),
        rain_in=tuple([rain] * hours),
        snow_in=tuple([snow] * hours),
        temp_f=tuple([35.0] * hours),
    )


class FixedUpstreams:
    """Patches geocoding, routing and weather with deterministic fixtures.

    The stub weather is a function of latitude only: the northern
    candidate gets a blizzard, the middle one a gale, the southern one
    calm air. That makes the expected ranking something a reader can work
    out from the brief's table by hand.
    """

    LATS = {41.0: (3.0, 0.0, 0.0), 40.0: (38.0, 0.0, 0.0), 39.0: (0.0, 0.0, 2.5)}

    def __init__(self, routes=None):
        self.routes = routes or [
            _route(41.0, 600.0, 10.0),  # calm, slowest
            _route(40.0, 590.0, 9.5),  # gale -> High (or Severe with a heavy load)
            _route(39.0, 580.0, 9.0),  # heavy snow -> Severe
        ]

    def __enter__(self):
        from trucking.domain.models import Place

        self._patches = [
            mock.patch(
                "trucking.api.planner.geocode",
                side_effect=lambda q: Place(query=q, name=q, lon=-90.0, lat=41.0),
            ),
            mock.patch(
                "trucking.api.planner.generate_routes",
                return_value=(self.routes, []),
            ),
            mock.patch(
                "trucking.api.planner.weather_service.fetch_series",
                side_effect=self._fetch,
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False

    def _fetch(self, coords, start, end):
        out = {}
        for coord in coords:
            cell = grid_round(coord)
            wind, rain, snow = self.LATS.get(round(cell[1]), (0.0, 0.0, 0.0))
            out[cell] = _series(cell, wind, rain, snow)
        return out


class ValidationTests(SimpleTestCase):
    BASE = {
        "origin": "Chicago, IL",
        "destination": "Denver, CO",
        "departure": DEPARTURE.isoformat(),
        "load_lb": 42000,
        "spacing_miles": 25,
    }

    def _parse(self, **overrides):
        payload = dict(self.BASE)
        payload.update(overrides)
        return parse_plan_request(payload)

    def test_a_valid_request_parses(self):
        parsed = self._parse()
        self.assertEqual(parsed.origin.text, "Chicago, IL")
        self.assertEqual(parsed.load_lb, 42000.0)
        self.assertEqual(parsed.spacing_miles, 25)
        self.assertEqual(parsed.wanted_routes, 3)

    def test_coordinates_may_be_supplied_to_skip_the_geocoder(self):
        parsed = self._parse(origin={"name": "Chicago", "lon": -87.6, "lat": 41.9})
        self.assertTrue(parsed.origin.resolved)
        self.assertEqual(parsed.origin.lon, -87.6)

    def test_a_place_object_without_coordinates_falls_back_to_text(self):
        parsed = self._parse(origin={"name": "Chicago"})
        self.assertFalse(parsed.origin.resolved)

    def test_out_of_range_coordinates_are_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._parse(origin={"name": "nowhere", "lon": -400.0, "lat": 91.0})
        self.assertEqual(ctx.exception.field, "origin")

    def test_missing_origin_names_the_field(self):
        with self.assertRaises(ValidationError) as ctx:
            self._parse(origin="   ")
        self.assertEqual(ctx.exception.field, "origin")

    def test_spacing_must_be_one_of_the_briefs_three(self):
        for good in (10, 25, 50):
            with self.subTest(spacing=good):
                self.assertEqual(self._parse(spacing_miles=good).spacing_miles, good)
        for bad in (5, 20, 100):
            with self.subTest(spacing=bad):
                with self.assertRaises(ValidationError) as ctx:
                    self._parse(spacing_miles=bad)
                self.assertEqual(ctx.exception.field, "spacing_miles")

    def test_load_weight_is_required_and_bounded(self):
        with self.assertRaises(ValidationError):
            self._parse(load_lb=None)
        with self.assertRaises(ValidationError):
            self._parse(load_lb=-1)
        with self.assertRaises(ValidationError):
            self._parse(load_lb=4_000_000)
        self.assertEqual(self._parse(load_lb=0).load_lb, 0.0)

    def test_load_weight_accepts_a_numeric_string(self):
        self.assertEqual(self._parse(load_lb="42000").load_lb, 42000.0)

    def test_departure_accepts_z_and_offset_forms(self):
        for text in ("2026-10-18T06:00:00Z", "2026-10-18T01:00:00-05:00"):
            with self.subTest(text=text):
                parsed = self._parse(departure=text)
                self.assertEqual(parsed.departure.tzinfo, timezone.utc)

    def test_a_naive_departure_is_read_as_utc(self):
        parsed = self._parse(departure="2026-10-18T06:00:00")
        self.assertEqual(parsed.departure.tzinfo, timezone.utc)

    def test_a_departure_past_the_forecast_horizon_is_rejected(self):
        far = datetime.now(timezone.utc) + timedelta(days=60)
        with self.assertRaises(ValidationError) as ctx:
            self._parse(departure=far.isoformat())
        self.assertEqual(ctx.exception.field, "departure")

    def test_a_departure_long_past_is_rejected(self):
        old = datetime.now(timezone.utc) - timedelta(days=10)
        with self.assertRaises(ValidationError):
            self._parse(departure=old.isoformat())

    def test_unparseable_departure_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._parse(departure="next tuesday")

    def test_omitted_departure_defaults_to_the_current_hour(self):
        payload = dict(self.BASE)
        payload.pop("departure")
        parsed = parse_plan_request(payload)
        self.assertEqual(parsed.departure.minute, 0)


class PlanEndpointTests(SimpleTestCase):
    BODY = {
        "origin": {"name": "Origin", "lon": -90.0, "lat": 41.0},
        "destination": {"name": "Destination", "lon": -100.0, "lat": 41.0},
        "departure": DEPARTURE.isoformat(),
        "load_lb": 20000,
        "spacing_miles": 50,
    }

    def _post(self, **overrides):
        body = dict(self.BODY)
        body.update(overrides)
        return self.client.post(
            "/api/plan", data=json.dumps(body), content_type="application/json"
        )

    def test_health_reports_the_sampling_intervals(self):
        payload = self.client.get("/api/health").json()
        self.assertEqual(payload["sampling_intervals_miles"], [10, 25, 50])
        self.assertEqual(payload["heatmap_hours"], 48)

    def test_three_routes_are_returned_scored_and_ranked(self):
        with FixedUpstreams():
            response = self._post()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["routes"]), 3)
        self.assertEqual([r["rank"] for r in payload["routes"]], [1, 2, 3])
        for route in payload["routes"]:
            self.assertIsNotNone(route["summary"])
            self.assertTrue(route["checkpoints"])
            for cp in route["checkpoints"]:
                self.assertIsNotNone(cp["risk"])
                self.assertIsNotNone(cp["eta"])

    def test_the_calm_route_is_recommended_over_faster_rougher_ones(self):
        """The calm candidate is the slowest of the three, so this fails if
        travel time is being weighed before severe miles."""
        with FixedUpstreams():
            payload = self._post().json()
        recommended = next(r for r in payload["routes"] if r["recommended"])
        self.assertEqual(recommended["summary"]["severe_miles"], 0.0)
        self.assertEqual(recommended["summary"]["high_miles"], 0.0)
        self.assertEqual(payload["recommendation"]["route_id"], recommended["id"])
        self.assertIn("severe", (payload["recommendation"]["reason"] or "").lower())

    def test_load_weight_changes_the_outcome(self):
        """38 mph is High for a light load. Over 40,000 lb the brief's third
        load rule makes the same wind Severe, so the same trip must come
        back with more severe miles."""
        with FixedUpstreams():
            light = self._post(load_lb=10_000).json()
        with FixedUpstreams():
            heavy = self._post(load_lb=45_000).json()

        def severe_on_gale(payload):
            route = next(
                r for r in payload["routes"] if any(cp["lat"] == 40.0 for cp in r["checkpoints"])
            )
            return route["summary"]["severe_miles"]

        self.assertEqual(severe_on_gale(light), 0.0)
        self.assertGreater(severe_on_gale(heavy), 0.0)

    def test_etas_advance_along_the_route(self):
        with FixedUpstreams():
            payload = self._post().json()
        for route in payload["routes"]:
            etas = [cp["eta"] for cp in route["checkpoints"]]
            self.assertEqual(etas, sorted(etas))

    def test_sampling_interval_changes_the_checkpoint_count(self):
        counts = {}
        for spacing in (10, 25, 50):
            with FixedUpstreams():
                payload = self._post(spacing_miles=spacing).json()
            counts[spacing] = len(payload["routes"][0]["checkpoints"])
        self.assertGreater(counts[10], counts[25])
        self.assertGreater(counts[25], counts[50])

    def test_heatmap_covers_0_to_48_hours_for_every_route(self):
        with FixedUpstreams():
            payload = self._post().json()
        self.assertEqual(payload["heatmap"]["hour_offsets"], list(range(49)))
        self.assertEqual(set(payload["heatmap"]["by_route"]), {r["id"] for r in payload["routes"]})
        for frames in payload["heatmap"]["by_route"].values():
            self.assertEqual(len(frames["levels"]), 49)
            for row in frames["levels"]:
                self.assertEqual(len(row), len(frames["points"]))

    def test_a_blocked_route_is_shown_but_not_recommended(self):
        """A 60 mph crosswind is No Travel for any load."""
        blocked = _route(41.0, 400.0, 6.0)
        with FixedUpstreams(routes=[blocked, _route(39.0, 600.0, 11.0)]) as stub:
            stub.LATS = {41.0: (60.0, 0.0, 0.0), 39.0: (5.0, 0.0, 0.0)}
            payload = self._post().json()
        blocked_route = next(r for r in payload["routes"] if r["blocked"])
        self.assertFalse(blocked_route["recommended"])
        self.assertIsNotNone(payload["recommendation"]["warning"])

    def test_the_same_request_twice_gives_the_same_plan(self):
        def plan():
            with FixedUpstreams():
                payload = self._post().json()
            payload["meta"].pop("elapsed_ms")
            return payload

        self.assertEqual(plan(), plan())

    def test_malformed_json_is_a_400(self):
        response = self.client.post(
            "/api/plan", data="{not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_json")

    def test_a_bad_field_is_a_400_naming_the_field(self):
        response = self._post(spacing_miles=7)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["field"], "spacing_miles")

    def test_an_unroutable_request_is_a_422(self):
        from trucking.services.routing import NoRouteFound

        with mock.patch(
            "trucking.api.planner.generate_routes", side_effect=NoRouteFound("no road")
        ), mock.patch(
            "trucking.api.planner.geocode",
            side_effect=lambda q: __import__(
                "trucking.domain.models", fromlist=["Place"]
            ).Place(query=q, name=q, lon=-90.0, lat=41.0),
        ):
            response = self._post()
        self.assertEqual(response.status_code, 422)

    def test_an_unknown_place_names_the_field_that_failed(self):
        """So the form can mark the offending input, not just apologise."""
        from trucking.services.geocoding import PlaceNotFound

        with mock.patch(
            "trucking.api.planner.geocode", side_effect=PlaceNotFound("no match for that")
        ):
            response = self._post(origin="Nowhere City")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["field"], "origin")

    def test_an_upstream_failure_is_a_502(self):
        from trucking.services.http import UpstreamError

        with mock.patch(
            "trucking.api.planner.geocode", side_effect=UpstreamError("nominatim", "timeout")
        ):
            response = self._post(origin="Chicago, IL")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["service"], "nominatim")

    def test_get_is_not_allowed_on_plan(self):
        self.assertEqual(self.client.get("/api/plan").status_code, 405)

    def test_geocode_requires_a_query(self):
        response = self.client.get("/api/geocode")
        self.assertEqual(response.status_code, 400)

    def test_geocode_resolves_a_literal_coordinate_without_the_network(self):
        """'lat,lon' is handled locally, so this touches no upstream."""
        response = self.client.get("/api/geocode", {"q": "41.8781,-87.6298"})
        self.assertEqual(response.status_code, 200)
        place = response.json()["place"]
        self.assertAlmostEqual(place["lat"], 41.8781)
        self.assertAlmostEqual(place["lon"], -87.6298)

    def test_a_missing_place_is_a_422_not_a_502(self):
        from trucking.services.geocoding import PlaceNotFound

        with mock.patch(
            "trucking.api.views.geocode", side_effect=PlaceNotFound("no match")
        ):
            response = self.client.get("/api/geocode", {"q": "Narnia"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "not_found")
