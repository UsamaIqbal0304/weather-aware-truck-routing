# Weather-Aware Truck Routing

Pick an origin, a destination, a departure time and a load weight. The app
generates three candidate routes, samples the weather forecast at every
checkpoint *at the hour the truck actually arrives there*, scores each
checkpoint against the briefed risk and load rules, and recommends the route
a dispatcher should take — with the reasoning spelled out rather than
implied.

- **Live app:** <https://weather-aware-truck-routing-eta.vercel.app>
- **Stack:** Django 5.1 (API only, no database) · React 18 + TypeScript + Vite
  · MapLibre GL JS
- **No API keys.** Routing, geocoding, forecasts and basemap tiles all come
  from keyless public services, so a reviewer can clone this repository and
  run it without being issued a secret.

---

## Requirements checklist

Every line of the brief, and where it is implemented.

### Inputs

| Requirement | Status | Where |
| --- | --- | --- |
| Origin & destination | Met | `PlanForm.tsx`; free text geocoded via Nominatim, or `lat,lon` typed directly, or one of four preset corridors that carry their own coordinates |
| Departure date/time | Met | `PlanForm.tsx` (`datetime-local`, sent as an ISO-8601 instant); validated in `api/validation.py` to −1/+14 days |
| Load weight | Met | `PlanForm.tsx` slider, 0–80,000 lb; the two load-rule thresholds are marked on the scale |

### Behaviour

| Requirement | Status | Where |
| --- | --- | --- |
| Generate 3 route options using a routing API | Met | `services/routing.py` — OSRM `alternatives=N`; when the engine returns fewer than three (common), extra candidates are synthesised by routing through a perpendicular via-point and kept only if they are genuinely different roads (`frechet_like_similarity`). A synthesised route is labelled as such in the UI |
| Sample weather every 10 / 25 / 50 miles | Met | `domain/sampling.py`; the interval is a three-way choice in the form and validated server-side |
| …using the truck's estimated arrival time at each checkpoint | Met | `domain/sampling.py` + `services/routing.py`. OSRM is asked for per-vertex annotations, so elapsed drive time at any point on the polyline is read from the engine rather than inferred from an average speed. Each checkpoint's forecast is read from that checkpoint's own hour |
| Calculate weather risk using the provided risk/load rules | Met | `domain/risk.py` — the three threshold tables and the three load rules, with the two ambiguous edges in the printed table resolved explicitly and covered by boundary tests |
| Recommend the best route, balancing weather risk and travel time | Met | `domain/recommend.py` — the brief's four criteria as a lexicographic sort key: severe miles, high miles, average risk, duration |
| Show all routes on a map | Met | `MapView.tsx` — the selected route drawn in risk colours, the other two dashed and clickable |
| Show checkpoints, risk levels and ETAs | Met | Coloured circles on the map with a click-through popup (mile, ETA, wind, rain, snow, temperature), plus a checkpoint table in the panel that defaults to the rows above Low |
| Show route summaries | Met | `RouteList.tsx` — distance, duration, arrival, a mile-band bar, and severe / high / average-risk / worst figures per route |
| Weather heatmap along the trip corridor | Met | `MapView.tsx` heatmap layer, fed from `api/planner.py::_build_heatmap`; the corridor is sampled at up to 60 points per route |
| 0–48 hour forecast slider | Met | `TimeSlider.tsx`; 49 frames (hours 0–48 inclusive) are precomputed per route, so a slider step swaps one array into one map source and touches nothing else |

### Risk rules

Implemented in `domain/risk.py` exactly as briefed, with the table's two
under-specified edges stated rather than guessed:

- The **wind** row is written in whole mph and so leaves a gap between bands
  (34 → 35, 44 → 45, 54 → 55). Each gap closes upwards, making the bands
  half-open: `<25 | [25,35) | [35,45) | [45,55) | ≥55`. A real anemometer
  reading of 34.6 mph is therefore Moderate, which is the only reading under
  which both "Moderate 25–34" and "High 35–44" stay true of their printed
  endpoints.
- The **rain** and **snow** rows share endpoints between bands (0.25 both
  ends Moderate and starts High). A shared endpoint resolves to the *lower*
  band, which is the reading that keeps the printed strict "No Travel >1.00"
  consistent with the rest of the row.

Load rules are applied to the wind band after classification: `≥55 mph` is No
Travel for any load; `45–54 mph` with more than 30,000 lb is No Travel;
`35–44 mph` with more than 40,000 lb is Severe. When a load rule is what
raised a checkpoint's level, the UI says so on the pill and in the popup.

### Recommendation

`domain/recommend.py` builds the sort key `(severe_miles, high_miles,
average_risk, duration_hours)`, so ties fall through by construction rather
than by a chain of hand-written comparisons.

Miles per band are attributed by a one-dimensional Voronoi partition: each
checkpoint owns the span of road closer to it than to its neighbours, so the
spans tile the route exactly once and the average risk is a distance-weighted
mean. An unweighted mean would let a three-mile tail at the destination count
for as much as fifty miles of interstate.

A route whose worst checkpoint is **No Travel** is excluded from the
recommendation and flagged in the UI; if every candidate is blocked, the best
of a bad set is still named, with a warning.

The banner names the criterion that actually decided the pick — "Route A
crosses 0 severe miles against 48 on the next best", or, when risk is level
across the candidates, "travel time decides it".

### Deliverables

| Deliverable | Status |
| --- | --- |
| GitHub repository | Met — this repository |
| Hosted application | Met — <https://weather-aware-truck-routing-eta.vercel.app> |
| 5–10 min Loom walkthrough | Recorded separately |

---

## Running it locally

Two processes. Python 3.10+ and Node 18+.

```bash
# 1. API
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000

# 2. UI (second terminal)
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api to :8000
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000` by default; set
`VITE_API_TARGET` to point it somewhere else.

### Tests

```bash
.venv/bin/python backend/manage.py test trucking
```

118 tests, no network access: the upstream clients are patched with a
deterministic stub whose forecast is a function of latitude, so the expected
ranking can be derived by hand and asserted. They cover the risk table's band
edges, the load rules, Voronoi mile attribution, ETA interpolation, the
lexicographic comparator's tie-breaks, and every API status path.

### Deployment

The hosted copy runs on Vercel: the Vite build is served as static files and
each API endpoint is a Python serverless function. `api/health.py`,
`api/geocode.py` and `api/plan.py` are three-line shims that hand the request
to the same Django WSGI application the local server runs, via
`backend/config/serverless.py`. `vercel.json` pins the build commands and
disables framework auto-detection, which otherwise sees `backend/manage.py`
and tries to run the platform's Django preset.

---

## Layout

```
backend/
  config/            Django settings, URLs, WSGI, serverless entry points
  trucking/
    domain/          Pure functions — no Django, no I/O
      geometry.py      haversine, cumulative distance, interpolation, simplify
      risk.py          the risk table and the load rules
      sampling.py      checkpoints at 10/25/50 mi, ETA per checkpoint
      recommend.py     summaries and the preference comparator
    services/        Upstream clients — rate limiting, caching, retry
      routing.py       OSRM, with synthesised alternatives
      geocoding.py     Nominatim, plus literal "lat,lon"
      weather.py       Open-Meteo, batched and grid-cached
    api/             Request validation, orchestration, JSON serialisation
    tests/
frontend/
  src/
    api/             Typed client and response types
    components/      Map, form, route list, slider, legend, tables
    hooks/           usePlan — request lifecycle and cancellation
    lib/             Risk colours, formatting, geometry, presets
api/                 One file per endpoint, for serverless hosting
```

The domain layer imports nothing from Django and performs no I/O, which is
why most of the test suite runs in about a second.

---

## Design decisions worth a sentence

**ETA comes from the routing engine, not from an average speed.** OSRM is
asked for per-vertex annotations, so the elapsed drive time at mile 412 is
the engine's own figure for the road actually taken. If a response arrives
without annotations the route falls back to distributing the total duration
by length and says so, rather than quietly pretending to a precision it
does not have.

**One batched, grid-rounded weather fetch.** Checkpoint coordinates are
rounded to two decimal places (≈1.1 km) before lookup, so three routes
sharing an interstate share forecast cells; every cell for every route and
both purposes is then fetched in one batched pass. A typical 1,000-mile plan
with three routes resolves to under 300 cells.

**The heatmap is precomputed hour-major.** The API returns
`levels[hour][point]`, so a slider step is one contiguous array handed
straight to one map source. Dragging the slider does not touch the route
layers, the checkpoint layer or the camera — each lives in its own effect
with its own dependency list for exactly that reason.

**Errors are separated by who can fix them.** 400 for a malformed request
(and it names the field), 422 for a well-formed request that cannot be
planned — an unknown place name, no road between the points — and 502 for an
upstream that failed. The UI highlights the offending input for the first,
explains the second, and offers a retry only for the third.

---

## Third-party services

All keyless, all public, each credited in the map's attribution control:

| Service | Used for | Notes |
| --- | --- | --- |
| [OSRM demo server](https://project-osrm.org/) | Routing and alternatives | Run by the OSRM project as a courtesy; this app rate-limits itself and caches every response |
| [Nominatim](https://nominatim.org/) | Geocoding place names | One request per second maximum, per the usage policy |
| [Open-Meteo](https://open-meteo.com/) | Hourly forecasts | Free for non-commercial use, no key |
| [OpenFreeMap](https://openfreemap.org/) | Basemap tiles | OpenStreetMap vector tiles, no key, no sign-up |

Because nothing here needs a secret, there is nothing to leak and nothing to
configure before the app runs. Every upstream URL, timeout, rate limit and
cache TTL is an environment-overridable Django setting
(`backend/config/settings.py`) rather than a literal buried in a client.

## Known limits

- The OSRM demo server is a shared courtesy instance. If it is busy the API
  returns 502 with an explanation and the UI offers a retry; a production
  deployment would point `OSRM_BASE_URL` at a dedicated instance.
- Open-Meteo's hourly model runs about 16 days ahead, so departures are
  capped at 14 days out. Checkpoints past the forecast horizon are reported
  as unassessed miles rather than silently scored as calm.
- Routes are capped at 3,200 miles and 420 checkpoints per route, so a
  10-mile interval across a continent cannot melt the forecast quota. The API
  explains the cap instead of truncating the route.
- The map needs WebGL. Where a browser cannot provide it, the map area says
  so and the panel — ranking, checkpoints, forecasts — keeps working.
- The risk shown is the real forecast, so on a calm day every candidate
  scores Low and the recommendation falls through to travel time — which the
  banner says outright instead of implying a weather verdict it did not make.
  The four preset corridors are picked for the conditions each is likeliest
  to meet (crosswind, mountain snow, Gulf rain, desert heat), and the full
  risk table, including every band edge and all three load rules, is pinned
  by the test suite rather than by whatever the sky is doing today.
