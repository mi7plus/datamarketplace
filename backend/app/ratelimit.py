# app/ratelimit.py
#
# Lightweight in-memory sliding-window rate limiter (S6). Used to throttle
# brute-force-prone auth endpoints per client IP. Process-local — fine for a
# single API process; behind multiple workers put a shared limiter at the proxy.
#
# Gated by RATELIMIT_ENABLED (default true); the test suite disables it via
# conftest so shared-IP test traffic isn't throttled.

import os
import time
import threading
from collections import defaultdict, deque

from fastapi import Request, HTTPException

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def _enabled() -> bool:
    return os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int, window_seconds: int):
    """
    FastAPI dependency: allow `limit` requests per `window_seconds` per client IP
    for the named bucket; raise 429 when exceeded.
    """
    def dep(request: Request):
        if not _enabled():
            return
        key = f"{bucket}:{_client_ip(request)}"
        now = time.monotonic()
        cutoff = now - window_seconds
        with _lock:
            dq = _hits[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests — slow down and try again shortly.",
                )
            dq.append(now)

    return dep


def reset() -> None:
    """Test helper — clear all counters."""
    with _lock:
        _hits.clear()
