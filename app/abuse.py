"""In-process rate limiting (spec sec. 4 NFR anti-abuso, sec. 7 caso 5).

Same sliding-window-over-a-dict pattern as whatsapp-clinic-agent's
_is_rate_limited (per-phone, hourly) adapted to per-API-key/IP, per-minute.
Single-worker assumption, same as app/cache.py and app/metrics.py: resets on
restart and does not coordinate across processes — acceptable for v1.
"""

import time

from app.config import RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS

_requests: dict[str, list[float]] = {}


def mask_key(key: str) -> str:
    return f"***{key[-4:]}" if len(key) >= 4 else "***"


def is_rate_limited(bucket_key: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _requests.get(bucket_key, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    recent.append(now)
    _requests[bucket_key] = recent
    return len(recent) > RATE_LIMIT_MAX_REQUESTS
