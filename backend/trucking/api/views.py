"""HTTP surface: three endpoints, all JSON, none of them stateful.

Error mapping is deliberate, because "the app is broken" and "that town
does not exist" are different problems for the driver and for whoever is
on call:

* 400 — the request is malformed or out of range (``ValidationError``);
* 422 — the request is well formed but cannot be planned: no such place,
  no road between the points, trip beyond the planning limits;
* 502 — a third party failed or timed out. Nothing we can fix from here,
  and the client should offer a retry rather than a correction.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ..services.geocoding import geocode
from ..services.http import UpstreamError
from . import serializers
from .planner import build_plan
from .validation import ValidationError, parse_plan_request

logger = logging.getLogger(__name__)


def _error(status: int, code: str, message: str, **extra) -> JsonResponse:
    body = {"error": {"code": code, "message": message, **extra}}
    return JsonResponse(body, status=status)


@require_http_methods(["GET"])
def health(request: HttpRequest) -> HttpResponse:
    """Liveness plus the knobs that change behaviour, for a quick sanity
    check against a deployed instance without reading its environment."""
    return JsonResponse(
        {
            "status": "ok",
            "debug": settings.DEBUG,
            "routing_engine": settings.OSRM_BASE_URL,
            "heatmap_hours": settings.HEATMAP_HOURS,
            "sampling_intervals_miles": [10, 25, 50],
        }
    )


@require_http_methods(["GET"])
def geocode_view(request: HttpRequest) -> HttpResponse:
    """Resolve one place name. Used by the form to confirm an endpoint
    before the user commits to a full plan."""
    query = (request.GET.get("q") or "").strip()
    if not query:
        return _error(400, "invalid_request", "q is required", field="q")
    try:
        resolved = geocode(query)
    except UpstreamError as exc:
        logger.warning("geocode failed for %r: %s", query, exc)
        return _error(502, "upstream_failed", str(exc), service=exc.service)
    except ValueError as exc:
        return _error(422, "not_found", str(exc), field="q")
    return JsonResponse({"place": serializers.place(resolved)})


@csrf_exempt
@require_http_methods(["POST"])
def plan_view(request: HttpRequest) -> HttpResponse:
    """Plan a trip. The only endpoint that matters.

    CSRF-exempt because the API is stateless and cookie-free: there is no
    session to ride, so a token would protect nothing. Authentication is
    out of scope for the brief; if it were added, this is the decorator
    that would come off.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error(400, "invalid_json", f"request body is not valid JSON ({exc})")

    try:
        parsed = parse_plan_request(payload)
    except ValidationError as exc:
        return _error(400, "invalid_request", exc.message, field=exc.field)

    try:
        plan = build_plan(parsed)
    except UpstreamError as exc:
        logger.warning("plan failed upstream: %s", exc)
        return _error(
            502,
            "upstream_failed",
            f"{exc.service} could not be reached. This app depends on free public "
            "services for routing, geocoding and weather; please retry in a moment.",
            service=exc.service,
        )
    except ValueError as exc:
        # A geocoding miss knows which of the two inputs it was.
        field = getattr(exc, "field", None)
        return _error(422, "unplannable", str(exc), **({"field": field} if field else {}))

    return JsonResponse(serializers.plan_response(plan))
