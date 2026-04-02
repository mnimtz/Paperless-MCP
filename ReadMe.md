# Paperless-ngx MCP Server

MCP-Server (Model Context Protocol) für Paperless-ngx mit OAuth 2.0.
Claude und ChatGPT greifen damit direkt auf dein Dokumentenarchiv zu.

## Einrichtung

### 1. API Token aus Paperless holen
Paperless → Profil oben rechts → **Mein Profil** → 🔄 Token generieren → kopieren.

### 2. Addon konfigurieren

| Option | Beschreibung | Beispiel |
|---|---|---|
| `paperless_url` | Interne URL | `http://192.168.1.179:100` |
| `paperless_api_key` | API Token | `127f9cff...` |
| `paperless_public_url` | Externe HTTPS-URL | `https://paperless-mcp.deine.domain` |
| `bearer_token` | Auto-generiert | leer lassen |
| `oauth_client_id` | Auto-generiert | leer lassen |
| `oauth_client_secret` | Auto-generiert | leer lassen |

### 3. Addon starten → Logs öffnen

Nach dem Start erscheint im Log ein vollständiger Verbindungsblock:

```
════════════════════════════════════════════════════════
  Paperless-ngx MCP Server — Verbindungsdaten
════════════════════════════════════════════════════════
  ── Claude (claude.ai → Einstellungen → Konnektoren) ──
  MCP URL:         https://paperless-mcp.deine.domain/sse
  OAuth Client-ID: paperless-mcp-abc123
  OAuth Secret:    xxxxxxxxxxxxxxxxxxx

  ── ChatGPT (Neue App → Authentifizierung: OAuth) ─────
  MCP Server URL:  https://paperless-mcp.deine.domain/sse
  Client-ID:       paperless-mcp-abc123
  Client Secret:   xxxxxxxxxxxxxxxxxxx
  Token-Methode:   client_secret_post
  Auth-URL:        https://paperless-mcp.deine.domain/oauth/authorize
  Token-URL:       https://paperless-mcp.deine.domain/oauth/token
════════════════════════════════════════════════════════
```

### 4. Cloudflare Tunnel

Zero Trust → Tunnels → Edit → Add public hostname:
- Subdomain: `paperless-mcp`
- Type: `HTTP`
- URL: `192.168.1.179:3020`

### 5. Claude Connector einrichten

claude.ai → Settings → Connectors → Add:
- URL: `https://paperless-mcp.deine.domain/sse`
- OAuth Client-ID + Secret aus dem Log

## Verfügbare MCP-Tools

| Tool | Beschreibung |
|---|---|
| `search_documents` | Volltext-Suche mit Filtern |
| `get_document` | Einzelnes Dokument abrufen |
| `get_document_content` | OCR-Text lesen (für Q&A) |
| `update_document` | Titel, Typ, Datum, Korrespondent ändern |
| `add_tag_to_document` | Tag hinzufügen |
| `list_tags` | Alle Tags auflisten |
| `create_tag` | Neuen Tag anlegen |
| `list_correspondents` | Korrespondenten auflisten |
| `create_correspondent` | Neuen Korrespondenten anlegen |
| `list_document_types` | Dokumenttypen auflisten |
| `create_document_type` | Neuen Typ anlegen |
| `get_archive_stats` | Archiv-Statistik |
| `build_lookup_cache` | ID→Name Tabellen laden |

## Troubleshooting

**Addon startet nicht:**
- `paperless_url` und `paperless_api_key` prüfen
- Interner Test: `curl http://192.168.1.179:100/api/`

**Claude findet keine Dokumente:**
- MCP URL im Browser testen: `https://paperless-mcp.deine.domain/sse`
- Erwartete Antwort: Redirect oder SSE-Stream

**OAuth-Fehler:**
- Logs prüfen: Sind Client-ID und Secret korrekt übertragen?
- Cloudflare Access deaktivieren zum Testen
