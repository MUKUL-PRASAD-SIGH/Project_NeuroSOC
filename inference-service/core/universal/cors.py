"""CORS for SDK routes only.

The SDK runs on customer websites whose origins are registered per site, so these routes cannot
use the service-wide ``CORS_ALLOWED_ORIGINS`` list. This middleware answers preflights and sets
CORS headers for ``/api/v1/sdk/`` paths alone, when the origin belongs to some registered site;
each request is then checked against its own site's origins inside the route. Every other path
passes through untouched, so the existing CORS policy is unchanged.
"""

from __future__ import annotations

from typing import Any, Callable

SDK_PREFIX = "/api/v1/sdk/"
ALLOWED_HEADERS = "content-type, x-neurosoc-key"


class SdkCorsMiddleware:
    def __init__(self, app: Any, origin_allowed: Callable[[str], bool]) -> None:
        self.app = app
        self.origin_allowed = origin_allowed

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(SDK_PREFIX):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        allowed = bool(origin) and self.origin_allowed(origin)

        if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            status = 204 if allowed else 403
            response_headers = [(b"content-length", b"0")]
            if allowed:
                response_headers += [
                    (b"access-control-allow-origin", origin.encode("latin-1")),
                    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                    (b"access-control-allow-headers", ALLOWED_HEADERS.encode("latin-1")),
                    (b"access-control-max-age", b"600"),
                    (b"vary", b"Origin"),
                ]
            await send({"type": "http.response.start", "status": status, "headers": response_headers})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message: dict) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if not k.lower().startswith(b"access-control-")]
                if allowed:
                    kept += [(b"access-control-allow-origin", origin.encode("latin-1")), (b"vary", b"Origin")]
                message = {**message, "headers": kept}
            await send(message)

        await self.app(scope, receive, send_with_cors)
