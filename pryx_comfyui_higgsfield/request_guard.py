"""Same-origin and per-process CSRF protection for the local settings API.

This is not user authentication. Network-exposed ComfyUI installations still
need authentication at their deployment boundary.
"""

from __future__ import annotations

import hmac
import secrets
from functools import wraps
from urllib.parse import urlsplit

TOKEN_HEADER = "X-PRYX-Higgsfield-Token"


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Invalid origin")
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def same_origin(request) -> bool:
    """Fail closed on foreign, opaque, or unidentifiable browser requests."""
    site = request.headers.get("Sec-Fetch-Site", "")
    if site and site != "same-origin":
        return False
    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            return _origin(origin) == _origin(f"{request.scheme}://{request.host}")
        except (ValueError, TypeError):
            return False
    return site == "same-origin"


class RequestGuard:
    def __init__(self) -> None:
        self._token = secrets.token_urlsafe(32)

    def protect(self, handler):
        @wraps(handler)
        async def guarded(request):
            from aiohttp import web

            # Older browsers and plain HTTP LAN origins can omit fetch
            # metadata on GET. A valid token is still mandatory; conflicting
            # metadata must never be accepted, even with a valid token.
            has_origin = "Origin" in request.headers or "Sec-Fetch-Site" in request.headers
            if has_origin and not same_origin(request):
                return web.json_response({"error": "Same-origin request required."}, status=403)
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not supplied.isascii() or not hmac.compare_digest(supplied, self._token):
                return web.json_response(
                    {"error": "Settings session expired. Please retry.", "code": "session_token_invalid"},
                    status=403,
                )
            response = await handler(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        return guarded

    async def session(self, request):
        from aiohttp import web

        if not same_origin(request):
            return web.json_response({"error": "Same-origin request required."}, status=403)
        return web.json_response({"token": self._token}, headers={"Cache-Control": "no-store"})
