# Changelog

## 1.0.2 - 2026-04-02

### Fixed
- Base Image nochmals korrigiert: `ghcr.io/home-assistant/base-python:3.13-alpine3.23` (offizielles Multi-Arch Image seit 2026.03.1)

## 1.0.1 - 2026-04-02

### Fixed
- Base Image korrigiert: `ghcr.io/hassio-addons/base-python:latest` statt nicht mehr existierendem `ghcr.io/home-assistant/aarch64-base-python:3.11`
- Dockerfile vereinfacht: Python bereits im Base Image enthalten

## 1.0.0 - 2026-04-02

### Added
- Initialer Release
- FastMCP + uvicorn ASGI Stack
- OAuth 2.0 Authorization Code Flow (RFC 6749)
- OAuth Discovery Endpoints (RFC 8414, RFC 9728)
- Bearer Token Auth Middleware
- Persistente Secrets in /data/mcp_secrets.json (überleben Updates)
- Auto-Generierung von Bearer Token, OAuth Client-ID und Secret
- Vollständiger Verbindungsinfo-Block im Log beim Start
- 13 MCP-Tools für Paperless-ngx REST API
- Multi-Arch: aarch64 (Raspberry Pi), amd64, armhf, armv7
- Cloudflare Tunnel kompatibel
- Claude und ChatGPT kompatibel

## 1.0.3 - 2026-04-02

### Changed
- Dockerfile: Multi-Stage Build — HA Base Image für bashio + baruchiro/paperless-mcp als fertiges MCP-Image
- Kein eigener Python-Server mehr, stattdessen bewährtes Node.js MCP-Image als Basis
- Löst alle Build-Probleme mit Python Base Images

## 1.0.4 - 2026-04-02

### Fixed
- Dockerfile vereinfacht: Node.js direkt via apk installieren (native aarch64)
- MCP Package via npm install -g statt Multi-Stage-Copy (war fehlerhaft auf ARM)
- run.sh: paperless-mcp Binary direkt aufrufen statt node /app/dist/index.js

## 1.0.4 - 2026-04-02

### Changed
- Dockerfile: Direkt ghcr.io/baruchiro/paperless-mcp als Basis — kein Multi-Stage mehr
- run.sh: Kein bashio mehr, liest options.json direkt mit Python
- build.yaml: Kein build_from nötig da eigenes FROM im Dockerfile
- Löst "cannot execute: required file not found" Fehler

## 1.0.4 - 2026-04-02

### Fixed
- Dockerfile: Node.js per apk installieren + baruchiro/paperless-mcp via npm -g
- Kein Multi-Stage Copy mehr (Alpine/Debian Binary-Inkompatibilität)
- run.sh: paperless-mcp Binary direkt aufrufen (npm global install)

## 1.0.5 - 2026-04-02

### Fixed
- run.sh: Python3 komplett entfernt — HA Base Image hat kein Python3
- Secrets-Logik komplett in Bash + jq umgeschrieben (jq ist im HA Base Image enthalten)
- Token-Generierung via /dev/urandom statt Python secrets-Modul

## 1.0.6 - 2026-04-02

### Added
- OAuth 2.0 Proxy (oauth-proxy.js) in Node.js — kein Python mehr
- Läuft auf Port 3020 (öffentlich), leitet /mcp an internen Port 3021 weiter
- Unterstützt: /oauth/authorize, /oauth/token, /.well-known/* Discovery
- ChatGPT und Claude OAuth voll kompatibel
- Baruchiro MCP Server läuft intern auf Port 3021

## 1.1.0 - 2026-04-02

### ✅ Erstes funktionierendes Release — Smoke Test bestanden

Verifiziert:
- list_documents, list_tags, list_document_types, list_correspondents, list_custom_fields
- get_document, get_document_content, search_documents
- post_document (Base64-Upload)
- End-to-End: Upload → Listung → Inhaltsabruf → Volltextsuche

Bekannte Issues:
- get_document_thumbnail schlägt fehl (upstream Bug in baruchiro/paperless-mcp)
- post_document erwartet Base64, keinen Dateipfad (by design, dokumentiert)

### Added
- BUGS.md: Bug-Tracker und Smoke-Test-Ergebnisse

## 1.1.1 - 2026-04-02

### Added
- Download-Route im OAuth Proxy: `GET /download/<id>?token=<bearer>`
- Unterstützt `?original=true` für Originaldatei statt archivierter Version
- Token-in-URL Auth für Browser-kompatible Download-Links
- Download-URL wird beim Start im Log angezeigt
- Schließt BUG-001 Workaround: Thumbnails weiterhin upstream-Bug, aber Downloads funktionieren

## 1.1.2 - 2026-04-02

### Fixed
- oauth-proxy.js: SyntaxError durch verwaisten checkAuth-Funktionskörper behoben (str_replace-Artefakt)

## 1.1.3 - 2026-04-02

### Added
- Neuer Endpoint GET /download-url/<id>: gibt fertigen Download-Link mit eingebettetem Token zurück
- Claude/ChatGPT rufen diesen Endpoint auf und können den Link direkt als klickbare URL ausgeben
- Optional: ?original=true für Originaldatei

### How it works
Claude ruft /download-url/2925 auf → bekommt:
  { "download_url": "https://paperless-mcp.../download/2925?token=xxx" }
Claude gibt diesen Link als Antwort aus → User klickt → PDF lädt herunter

## 1.1.4 - 2026-04-02

### Fixed
- MCP Tool-Call Interceptor: download_document und get_document_thumbnail werden
  im Proxy abgefangen bevor sie den baruchiro-Server (424-Bug) erreichen
- download_document gibt jetzt fertigen Download-Link zurück statt 424
- get_document_thumbnail gibt klare Fehlermeldung + Download-Link als Alternative
- proxyToInternal: akzeptiert optionalen Body-Buffer für bereits gelesene Requests
- Nur POST/PUT/PATCH lesen den Body — GET-Requests werden direkt weitergeleitet
