"""One HTTP front door for every third-party call.

Everything outbound goes through :func:`get_json`, which gives us four
things in one place: a descriptive User-Agent (Nominatim requires one and
will block a generic client), a server-side response cache, a per-host
minimum interval between requests, and bounded retries on the transient
statuses. None of the three upstreams we use charges money and all three
publish a usage policy; honouring those policies is a hard requirement of
this app, not a nicety, so the limiter is not optional and not in the view.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode, urlsplit

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class UpstreamError(RuntimeError):
    """A third-party service failed in a way the caller should surface."""

    def __init__(self, service: str, message: str, status: Optional[int] = None):
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status = status


class _HostRateLimiter:
    """Smallest thing that enforces "no more than one request per N seconds".

    Per host, process-wide, thread-safe. Nominatim's policy is an absolute
    maximum of one request per second from one application; OSRM's demo
    server asks for "reasonable" use; Open-Meteo allows generous
    non-commercial volume. The intervals live in settings so the policy is
    visible in one place and can be tightened without touching callers.
    """

    def __init__(self) -> None:
        self._next_allowed: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        if min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            earliest = self._next_allowed.get(host, 0.0)
            delay = max(0.0, earliest - now)
            self._next_allowed[host] = max(now, earliest) + min_interval
        if delay > 0:
            logger.debug("rate limit: sleeping %.2fs before %s", delay, host)
            time.sleep(delay)


_limiter = _HostRateLimiter()

_session = requests.Session()
_session.headers.update({"Accept": "application/json"})


def cache_key(prefix: str, url: str, params: Mapping[str, Any]) -> str:
    """Stable cache key. Params are sorted so argument order cannot miss."""
    blob = json.dumps(
        {"url": url, "params": {k: params[k] for k in sorted(params)}},
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return f"trk:{prefix}:{digest}"


def get_json(
    service: str,
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    *,
    ttl: int,
    min_interval: float = 0.0,
    timeout: Optional[float] = None,
    attempts: int = 3,
) -> Any:
    """GET a JSON document, cached and rate limited.

    A cache hit does not consume the rate limiter, which is the point of
    caching here: three candidate routes over the same corridor ask for
    overlapping weather cells, and only the first of them reaches the
    network.
    """
    params = dict(params or {})
    key = cache_key(service, url, params)
    cached = cache.get(key)
    if cached is not None:
        logger.debug("cache hit %s %s", service, key)
        return cached

    host = urlsplit(url).netloc
    timeout = timeout if timeout is not None else settings.UPSTREAM_TIMEOUT_SECONDS
    headers = {"User-Agent": settings.UPSTREAM_USER_AGENT}

    last_error: Optional[str] = None
    for attempt in range(1, attempts + 1):
        _limiter.wait(host, min_interval)
        try:
            response = _session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"request failed ({exc.__class__.__name__})"
            logger.warning("%s attempt %d/%d: %s", service, attempt, attempts, last_error)
        else:
            if response.status_code in RETRY_STATUSES:
                last_error = f"HTTP {response.status_code}"
                logger.warning(
                    "%s attempt %d/%d: %s", service, attempt, attempts, last_error
                )
                if attempt < attempts:
                    time.sleep(min(2.0 ** attempt * 0.25, 4.0))
                continue
            if not response.ok:
                raise UpstreamError(
                    service,
                    f"HTTP {response.status_code}: {response.text[:200]}",
                    response.status_code,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError(service, f"invalid JSON ({exc})") from exc
            cache.set(key, payload, ttl)
            return payload

        if attempt < attempts:
            time.sleep(min(2.0 ** attempt * 0.25, 4.0))

    raise UpstreamError(service, last_error or "exhausted retries")


def describe_query(url: str, params: Mapping[str, Any]) -> str:
    """Readable URL for logs and error messages. Never logs credentials."""
    return f"{url}?{urlencode({k: v for k, v in params.items() if 'key' not in k.lower()})}"
