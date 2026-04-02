"""
OAuthMiddleware
Implementiert OAuth 2.0 Authorization Code Flow (RFC 6749)
+ OAuth Discovery (RFC 8414 + RFC 9728)

Routen:
  GET  /.well-known/oauth-authorization-server  → Discovery
  GET  /.well-known/oauth-protected-resource    → Resource Metadata
  GET  /oauth/authorize                          → Auth-Seite (HTML)
  POST /oauth/authorize                          → Code ausstellen
  POST /oauth/token                              → Token austauschen
  GET  /health                                   → Health Check
"""

import os
import json
import time
import secrets
import logging
import urllib.parse
from typing import Optional

log = logging.getLogger(__name__)

# In-Memory Auth-Code-Store {code: {client_id, redirect_uri, expires_at}}
_auth_codes: dict = {}
AUTH_CODE_TTL = 600  # 10 Minuten


def _public_url() -> str:
    return os.environ.get("PAPERLESS_PUBLIC_URL", "http://localhost:3020").rstrip("/")


def _oauth_client_id() -> str:
    return os.environ.get("OAUTH_CLIENT_ID", "")


def _oauth_client_secret() -> str:
    return os.environ.get("OAUTH_CLIENT_SECRET", "")


def _bearer_token() -> str:
    return os.environ.get("BEARER_TOKEN", "")


# ── Discovery Documents ───────────────────────────────────────────────────────

def _authorization_server_metadata() -> dict:
    base = _public_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "grant_types_supported": ["authorization_code"],
        "response_types_supported": ["code"],
        "scopes_supported": ["paperless"],
        "code_challenge_methods_supported": [],
    }


def _protected_resource_metadata() -> dict:
    base = _public_url()
    return {
        "resource": f"{base}/sse",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["paperless"],
    }


# ── HTML Authorize Seite ──────────────────────────────────────────────────────

def _authorize_html(client_id: str, redirect_uri: str, state: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Paperless-ngx MCP — Zugriff erlauben</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f8fafc; display: flex; align-items: center;
    justify-content: center; min-height: 100vh; padding: 20px;
  }}
  .card {{
    background: white; border-radius: 16px; padding: 32px;
    max-width: 420px; width: 100%;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    border: 1px solid #e2e8f0;
  }}
  .icon {{ font-size: 40px; margin-bottom: 16px; }}
  h1 {{ font-size: 20px; color: #1e293b; margin-bottom: 8px; }}
  p {{ color: #64748b; font-size: 14px; line-height: 1.6; margin-bottom: 24px; }}
  .app {{ background: #f1f5f9; border-radius: 8px; padding: 12px 16px;
          margin-bottom: 24px; font-size: 13px; color: #475569; }}
  .app strong {{ color: #1e293b; }}
  .permissions {{ margin-bottom: 24px; }}
  .perm {{ display: flex; align-items: center; gap: 10px; padding: 8px 0;
           font-size: 14px; color: #334155; border-bottom: 1px solid #f1f5f9; }}
  .perm:last-child {{ border-bottom: none; }}
  .perm-icon {{ font-size: 16px; }}
  .buttons {{ display: flex; gap: 12px; }}
  .btn-allow {{
    flex: 1; background: #3b82f6; color: white; border: none;
    border-radius: 8px; padding: 12px; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }}
  .btn-allow:hover {{ background: #2563eb; }}
  .btn-deny {{
    flex: 1; background: white; color: #64748b; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 12px; font-size: 14px;
    cursor: pointer; transition: background 0.2s;
  }}
  .btn-deny:hover {{ background: #f8fafc; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">📚</div>
  <h1>Zugriff auf Paperless-ngx</h1>
  <p>Eine Anwendung möchte auf dein Dokumentenarchiv zugreifen.</p>

  <div class="app">
    <strong>App:</strong> {client_id}<br>
    <strong>Redirect:</strong> {redirect_uri[:50]}{'...' if len(redirect_uri) > 50 else ''}
  </div>

  <div class="permissions">
    <div class="perm"><span class="perm-icon">🔍</span> Dokumente suchen und lesen</div>
    <div class="perm"><span class="perm-icon">🏷️</span> Tags, Korrespondenten, Typen lesen</div>
    <div class="perm"><span class="perm-icon">✏️</span> Dokumentmetadaten bearbeiten</div>
    <div class="perm"><span class="perm-icon">📤</span> Dokumente hochladen</div>
  </div>

  <form method="POST">
    <input type="hidden" name="client_id" value="{client_id}">
    <input type="hidden" name="redirect_uri" value="{redirect_uri}">
    <input type="hidden" name="state" value="{state}">
    <div class="buttons">
      <button type="submit" name="action" value="allow" class="btn-allow">
        ✅ Zugriff erlauben
      </button>
      <button type="submit" name="action" value="deny" class="btn-deny">
        ✕ Ablehnen
      </button>
    </div>
  </form>
</div>
</body>
</html>"""


# ── ASGI Middleware ───────────────────────────────────────────────────────────

class OAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        # Route zu eigenem Handler oder weiterleiten
        if path == "/.well-known/oauth-authorization-server":
            await self._json_response(send, _authorization_server_metadata())
        elif path == "/.well-known/oauth-protected-resource":
            await self._json_response(send, _protected_resource_metadata())
        elif path == "/health":
            await self._json_response(send, {"status": "ok", "service": "paperless-mcp"})
        elif path == "/oauth/authorize" and method == "GET":
            await self._handle_authorize_get(scope, send)
        elif path == "/oauth/authorize" and method == "POST":
            await self._handle_authorize_post(scope, receive, send)
        elif path == "/oauth/token" and method == "POST":
            await self._handle_token(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    # ── GET /oauth/authorize ──────────────────────────────────────────────────
    async def _handle_authorize_get(self, scope, send):
        params = dict(urllib.parse.parse_qsl(scope.get("query_string", b"").decode()))
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")

        if not client_id or not redirect_uri:
            await self._error_response(send, 400, "client_id und redirect_uri erforderlich")
            return

        if client_id != _oauth_client_id():
            await self._error_response(send, 401, "Unbekannte Client-ID")
            return

        html = _authorize_html(client_id, redirect_uri, state)
        await self._html_response(send, html)

    # ── POST /oauth/authorize ─────────────────────────────────────────────────
    async def _handle_authorize_post(self, scope, receive, send):
        body = await self._read_body(receive)
        params = dict(urllib.parse.parse_qsl(body.decode()))

        action = params.get("action", "deny")
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")

        if action != "allow":
            # Ablehnen → zurück mit error
            redirect = f"{redirect_uri}?error=access_denied"
            if state:
                redirect += f"&state={urllib.parse.quote(state)}"
            await self._redirect(send, redirect)
            return

        if client_id != _oauth_client_id():
            await self._error_response(send, 401, "Unbekannte Client-ID")
            return

        # Auth-Code generieren
        code = secrets.token_urlsafe(32)
        _auth_codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "expires_at": time.time() + AUTH_CODE_TTL,
        }

        log.info(f"Auth-Code ausgestellt für client_id={client_id}")

        redirect = f"{redirect_uri}?code={code}"
        if state:
            redirect += f"&state={urllib.parse.quote(state)}"
        await self._redirect(send, redirect)

    # ── POST /oauth/token ─────────────────────────────────────────────────────
    async def _handle_token(self, scope, receive, send):
        body = await self._read_body(receive)
        params = dict(urllib.parse.parse_qsl(body.decode()))

        grant_type = params.get("grant_type", "")
        code = params.get("code", "")
        client_id = params.get("client_id", "")
        client_secret = params.get("client_secret", "")
        redirect_uri = params.get("redirect_uri", "")

        # Validierung
        if grant_type != "authorization_code":
            await self._oauth_error(send, "unsupported_grant_type")
            return

        if client_id != _oauth_client_id() or client_secret != _oauth_client_secret():
            log.warning("Token-Request: ungültige Client-Credentials")
            await self._oauth_error(send, "invalid_client")
            return

        entry = _auth_codes.get(code)
        if not entry:
            await self._oauth_error(send, "invalid_grant", "Ungültiger oder abgelaufener Code")
            return

        if time.time() > entry["expires_at"]:
            del _auth_codes[code]
            await self._oauth_error(send, "invalid_grant", "Auth-Code abgelaufen")
            return

        if entry["client_id"] != client_id:
            await self._oauth_error(send, "invalid_grant", "Client-ID stimmt nicht überein")
            return

        # Code einlösen — Bearer Token zurückgeben
        del _auth_codes[code]
        log.info(f"Token ausgestellt für client_id={client_id}")

        await self._json_response(send, {
            "access_token": _bearer_token(),
            "token_type": "bearer",
            "scope": "paperless",
        })

    # ── Helpers ───────────────────────────────────────────────────────────────
    async def _read_body(self, receive) -> bytes:
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body", False):
                break
        return body

    async def _json_response(self, send, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [[b"content-type", b"application/json"]]})
        await send({"type": "http.response.body", "body": body})

    async def _html_response(self, send, html: str, status: int = 200):
        body = html.encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [[b"content-type", b"text/html; charset=utf-8"]]})
        await send({"type": "http.response.body", "body": body})

    async def _redirect(self, send, url: str):
        await send({"type": "http.response.start", "status": 302,
                    "headers": [[b"location", url.encode()]]})
        await send({"type": "http.response.body", "body": b""})

    async def _error_response(self, send, status: int, message: str):
        await self._json_response(send, {"error": message}, status)

    async def _oauth_error(self, send, error: str, description: str = ""):
        data = {"error": error}
        if description:
            data["error_description"] = description
        await self._json_response(send, data, 400)
