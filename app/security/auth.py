from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit


def safe_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Origin must be an absolute HTTP(S) origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("Origin must not contain a path, credentials, query, or fragment")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    port = parsed.port
    default = 443 if parsed.scheme.lower() == "https" else 80
    suffix = "" if not port or port == default else f":{port}"
    return f"{parsed.scheme.lower()}://{host}{suffix}"


def origin_matches(origin: str | None, allowed: list[str]) -> bool:
    if not origin:
        return False
    try:
        candidate = normalize_origin(origin)
        return any(candidate == normalize_origin(item) for item in allowed)
    except ValueError:
        return False
