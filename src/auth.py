"""
BearerAuthMiddleware
Prüft Authorization: Bearer <token> Header.
Whitelist: /health, /.well-known/*, /oauth/*
"""

import os
import logging

log = logging.getLogger(__name__)

# Pfade die ohne Auth zugänglich sind
AUTH_WHITELIST = (
    "/health",
    "/.well-known/",
    "/oauth/",
)


class BearerAuthMiddleware:
    def __init__(self, app):
        self.app = app
        self.bearer_token = os.environ.get("BEARER_TOKEN", "")

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Whitelist prüfen
        for prefix in AUTH_WHITELIST:
            if path.startswith(prefix):
                await self.app(scope, receive, send)
                return

        # Kein Token konfiguriert → alles erlauben
        if not self.bearer_token:
            await self.app(scope, receive, send)
            return

        # Authorization Header prüfen
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == self.bearer_token:
                await self.app(scope, receive, send)
                return

        # Unauthorized
        log.warning(f"Unauthorized request to {path}")
        await self._send_401(send)

    async def _send_401(self, send):
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                [b"content-type", b"application/json"],
                [b"www-authenticate", b'Bearer realm="Paperless MCP"'],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"error": "unauthorized", "message": "Bearer token required"}',
        })
