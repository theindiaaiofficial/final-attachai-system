"""Opaque, database-backed admin sessions. No API credential reaches browser storage."""
from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from app.security.auth import hash_api_key, safe_equal

COOKIE = "orbit_admin_session"


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Cross-origin administrative request rejected")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site administrative request rejected")


def session_record(request: Request) -> dict | None:
    current = request.app.state.state
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 200:
        return None
    record = current.repository.admin_session(hash_api_key(token))
    if not record:
        return None
    expiry = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    expected = hash_api_key(current.settings.admin_api_key.get_secret_value())
    if expiry <= datetime.now(UTC) or not safe_equal(record["credential_hash"], expected):
        current.repository.delete_admin_session(hash_api_key(token))
        return None
    return record


def require_admin(request: Request):
    current = request.app.state.state
    header = request.headers.get("x-admin-api-key")
    if header is not None:
        if not safe_equal(header, current.settings.admin_api_key.get_secret_value()):
            raise HTTPException(401, "Admin authentication required")
        return current
    record = session_record(request)
    if not record:
        raise HTTPException(401, "Your administrative session has expired. Please sign in.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        same_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not safe_equal(csrf, record["csrf_token"]):
            raise HTTPException(403, "Invalid CSRF token")
    return current


class LoginLimiter:
    """Bounded process-local login throttle; deploy one instance or edge-limit login."""

    def __init__(self):
        self.attempts: dict[str, list[float]] = {}

    def check(self, address: str) -> None:
        now = time.monotonic()
        self.attempts = {k: [v for v in values if now - v < 300] for k, values in self.attempts.items() if values and now - values[-1] < 300}
        values = self.attempts.setdefault(address, [])
        if len(values) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
        if len(self.attempts) > 10000:
            raise HTTPException(429, "Sign-in temporarily busy. Please retry.")
        values.append(now)
