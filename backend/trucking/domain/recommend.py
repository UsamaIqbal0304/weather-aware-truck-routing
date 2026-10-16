"""Route summaries and the recommendation comparator.

The brief fixes the preference order:

    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk
    4. Shortest travel time

That is a lexicographic order, so it is implemented as a sort key tuple
rather than as a chain of comparisons: a tuple key is a total order by
construction, which is exactly the property the tests assert (including
that a tie on one criterion falls through to the next).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .models import Checkpoint, RiskLevel, RouteOption, RouteSummary


def summarise(
    checkpoints: Sequence[Checkpoint],
    distance_miles: float,
    duration_hours: float,
) -> RouteSummary:
    """Fold checkpoints into the aggregates the comparator needs.

    Miles per band are summed over each checkpoint's Voronoi span, and the
    average risk is the distance-weighted mean of the band ordinals. It is
    distance-weighted and not a plain mean because the first and last
    checkpoints own half-width spans, and because the destination
    checkpoint lands wherever the route ends: an unweighted mean would let
    a 3-mile tail count as much as a 50-mile stretch of interstate.

    Checkpoints with no forecast (an ETA beyond the model horizon) are
    excluded from the weighting and reported as ``unassessed_miles``.
    """
    buckets = {level: 0.0 for level in RiskLevel}
    weighted = 0.0
    assessed = 0.0
    unassessed = 0.0
    worst = RiskLevel.LOW

    for cp in checkpoints:
        if cp.risk is None:
            unassessed += cp.covered_miles
            continue
        buckets[cp.risk.level] += cp.covered_miles
        weighted += float(cp.risk.level) * cp.covered_miles
        assessed += cp.covered_miles
        worst = max(worst, cp.risk.level)

    average = weighted / assessed if assessed > 0 else 0.0

    return RouteSummary(
        distance_miles=distance_miles,
        duration_hours=duration_hours,
        severe_miles=buckets[RiskLevel.SEVERE],
        high_miles=buckets[RiskLevel.HIGH],
        moderate_miles=buckets[RiskLevel.MODERATE],
        low_miles=buckets[RiskLevel.LOW],
        no_travel_miles=buckets[RiskLevel.NO_TRAVEL],
        average_risk=average,
        max_risk=worst,
        assessed_miles=assessed,
        unassessed_miles=unassessed,
    )


def preference_key(route: RouteOption) -> Tuple[float, float, float, float]:
    """The brief's ordering, as a lexicographic sort key. Lower is better.

    A route with no summary sorts last on every criterion rather than
    raising, so a partial failure on one candidate cannot take down the
    whole comparison.
    """
    s = route.summary
    if s is None:
        return (float("inf"),) * 4
    return (s.severe_miles, s.high_miles, s.average_risk, s.duration_hours)


def rank(routes: Sequence[RouteOption]) -> List[RouteOption]:
    """Routes best-first under the brief's order.

    Python's sort is stable, so candidates that tie on all four criteria
    keep the order the routing engine returned them in — which makes the
    output reproducible instead of arbitrary.
    """
    return sorted(routes, key=preference_key)


def recommend(
    routes: Sequence[RouteOption], skip_blocked: bool = True
) -> Tuple[Optional[RouteOption], List[RouteOption], Optional[str]]:
    """Pick the recommended route. Returns (choice, ranked, warning).

    The brief's four criteria do not mention No Travel, because a route
    carrying a No Travel checkpoint is not a travel option at all. So by
    default a blocked route is held back from the recommendation while
    still being ranked, shown and explained. Set ``skip_blocked=False`` to
    get the brief's four criteria applied literally across every candidate;
    both behaviours are covered by tests.

    If every candidate is blocked there is no safe choice to make, and the
    caller gets the best-ranked route together with a warning saying so.
    """
    ranked = rank(routes)
    if not ranked:
        return None, [], None

    if not skip_blocked:
        return ranked[0], ranked, None

    open_routes = [r for r in ranked if not r.blocked]
    if open_routes:
        warning = None
        if len(open_routes) < len(ranked):
            blocked_count = len(ranked) - len(open_routes)
            warning = (
                f"{blocked_count} of {len(ranked)} routes cross a No Travel checkpoint "
                "and were excluded from the recommendation."
            )
        return open_routes[0], ranked, warning

    return (
        ranked[0],
        ranked,
        "Every route crosses a No Travel checkpoint for this load and departure time. "
        "No departure is recommended; delay or re-plan.",
    )
