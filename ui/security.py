from __future__ import annotations

import os
import threading
import time
from collections import deque
from urllib.parse import urlparse

from config import is_truthy


_rate_lock = threading.Lock()
_rate_buckets: dict[tuple[str, str], deque[float]] = {}

# Window/limit defaults: tuned for an interactive UI where humans drive the
# requests. Overridable per-deployment via env vars.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    # bucket: (max_requests, window_seconds)
    "auth_sms_send": (5, 60.0),
    "auth_login": (10, 60.0),
    "auth_register": (5, 60.0),
    "auth_other": (30, 60.0),
}

CSRF_ENFORCE = is_truthy(os.environ.get("WEWALLET_CSRF_ENFORCE", "1"))
CSRF_ALLOW_MISSING_ORIGIN = is_truthy(os.environ.get("WEWALLET_CSRF_ALLOW_MISSING_ORIGIN", "1"))


def bucket_for_path(path: str) -> str | None:
    if path == "/api/auth/sms/send":
        return "auth_sms_send"
    if path in {"/api/auth/password/login", "/api/auth/sms/verify"}:
        return "auth_login"
    if path == "/api/auth/register":
        return "auth_register"
    if path.startswith("/api/auth/"):
        return "auth_other"
    return None


def check_rate_limit(client_ip: str, bucket: str) -> bool:
    limit = RATE_LIMITS.get(bucket)
    if not limit:
        return True
    max_requests, window_seconds = limit
    now = time.monotonic()
    key = (client_ip, bucket)
    with _rate_lock:
        events = _rate_buckets.setdefault(key, deque())
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= max_requests:
            return False
        events.append(now)
        return True


def reset_rate_limits() -> None:
    """Clear all rate-limit state. Intended for tests."""
    with _rate_lock:
        _rate_buckets.clear()


def _origin_host(origin_or_referer: str) -> str:
    if not origin_or_referer:
        return ""
    parsed = urlparse(origin_or_referer)
    return parsed.netloc or ""


def check_csrf(origin_header: str, referer_header: str, host_header: str) -> bool:
    """Return True if the request passes the CSRF check.

    Defense-in-depth on top of SameSite=Lax cookies: if the browser sent an
    Origin or Referer, it must match the server's host. Non-browser clients
    (no Origin and no Referer) are allowed when CSRF_ALLOW_MISSING_ORIGIN is
    on, so backend scripts and integration tests keep working.
    """
    if not CSRF_ENFORCE:
        return True
    if not origin_header and not referer_header:
        return CSRF_ALLOW_MISSING_ORIGIN
    expected = (host_header or "").strip().lower()
    if not expected:
        # Without a Host header we cannot verify; reject for safety.
        return False
    origin_host = _origin_host(origin_header).lower()
    referer_host = _origin_host(referer_header).lower()
    if origin_host and origin_host == expected:
        return True
    if referer_host and referer_host == expected:
        return True
    return False
