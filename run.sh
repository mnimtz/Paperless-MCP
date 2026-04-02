#!/usr/bin/with-contenv bashio
set -e

SECRETS_FILE="/data/mcp_secrets.json"
[ -f "${SECRETS_FILE}" ] || echo "{}" > "${SECRETS_FILE}"

read_secret() { jq -r ".${1} // empty" "${SECRETS_FILE}"; }
save_secret() { local tmp; tmp=$(jq --arg k "$1" --arg v "$2" '.[$k]=$v' "${SECRETS_FILE}"); echo "$tmp" > "${SECRETS_FILE}"; }
gen_token()   { cat /dev/urandom | tr -dc 'A-Za-z0-9_-' | head -c 43; }
gen_hex()     { cat /dev/urandom | tr -dc 'a-f0-9' | head -c 12; }

# ── HA Config lesen ───────────────────────────────────────────────────────────
PAPERLESS_URL=$(bashio::config 'paperless_url')
PAPERLESS_API_KEY=$(bashio::config 'paperless_api_key')
PAPERLESS_PUBLIC_URL=$(bashio::config 'paperless_public_url' '')
LOG_LEVEL=$(bashio::config 'log_level' 'info')
MCP_PORT="3020"
INTERNAL_PORT="3021"

bashio::var.is_empty "${PAPERLESS_URL}"     && bashio::log.fatal "paperless_url fehlt!"     && exit 1
bashio::var.is_empty "${PAPERLESS_API_KEY}" && bashio::log.fatal "paperless_api_key fehlt!" && exit 1
bashio::var.is_empty "${PAPERLESS_PUBLIC_URL}" && PAPERLESS_PUBLIC_URL="${PAPERLESS_URL}"

# ── Secrets: Config → gespeichert → neu generieren ───────────────────────────
BEARER_TOKEN=$(bashio::config 'bearer_token' '')
[ -z "${BEARER_TOKEN}" ] && BEARER_TOKEN=$(read_secret "bearer_token")
[ -z "${BEARER_TOKEN}" ] && BEARER_TOKEN=$(gen_token) && bashio::log.info "Bearer Token generiert"
save_secret "bearer_token" "${BEARER_TOKEN}"

OAUTH_CLIENT_ID=$(bashio::config 'oauth_client_id' '')
[ -z "${OAUTH_CLIENT_ID}" ] && OAUTH_CLIENT_ID=$(read_secret "oauth_client_id")
[ -z "${OAUTH_CLIENT_ID}" ] && OAUTH_CLIENT_ID="paperless-mcp-$(gen_hex)" && bashio::log.info "OAuth Client ID generiert"
save_secret "oauth_client_id" "${OAUTH_CLIENT_ID}"

OAUTH_CLIENT_SECRET=$(bashio::config 'oauth_client_secret' '')
[ -z "${OAUTH_CLIENT_SECRET}" ] && OAUTH_CLIENT_SECRET=$(read_secret "oauth_client_secret")
[ -z "${OAUTH_CLIENT_SECRET}" ] && OAUTH_CLIENT_SECRET=$(gen_token) && bashio::log.info "OAuth Client Secret generiert"
save_secret "oauth_client_secret" "${OAUTH_CLIENT_SECRET}"

# ── Exports ───────────────────────────────────────────────────────────────────
export PAPERLESS_URL PAPERLESS_API_KEY PAPERLESS_PUBLIC_URL
export BEARER_TOKEN OAUTH_CLIENT_ID OAUTH_CLIENT_SECRET
export MCP_PORT INTERNAL_PORT

# ── Log-Block ─────────────────────────────────────────────────────────────────
bashio::log.info "════════════════════════════════════════════════════════"
bashio::log.info "  Paperless-ngx MCP Server — Verbindungsdaten"
bashio::log.info "════════════════════════════════════════════════════════"
bashio::log.info "  ── Claude (Einstellungen → Konnektoren) ──────────────"
bashio::log.info "  MCP URL:         ${PAPERLESS_PUBLIC_URL}/mcp"
bashio::log.info "  OAuth Client-ID: ${OAUTH_CLIENT_ID}"
bashio::log.info "  OAuth Secret:    ${OAUTH_CLIENT_SECRET}"
bashio::log.info ""
bashio::log.info "  ── ChatGPT (Neue App → OAuth) ────────────────────────"
bashio::log.info "  MCP Server URL:  ${PAPERLESS_PUBLIC_URL}/mcp"
bashio::log.info "  Client-ID:       ${OAUTH_CLIENT_ID}"
bashio::log.info "  Client Secret:   ${OAUTH_CLIENT_SECRET}"
bashio::log.info "  Token-Methode:   client_secret_post"
bashio::log.info "  Auth-URL:        ${PAPERLESS_PUBLIC_URL}/oauth/authorize"
bashio::log.info "  Token-URL:       ${PAPERLESS_PUBLIC_URL}/oauth/token"
bashio::log.info "  Scopes:          (leer lassen)"
bashio::log.info ""
bashio::log.info "  ── Bearer Token & Download ───────────────────────────"
bashio::log.info "  Bearer Token:    ${BEARER_TOKEN}"
bashio::log.info "  Download URL:    ${PAPERLESS_PUBLIC_URL}/download/<doc-id>?token=${BEARER_TOKEN}"
bashio::log.info "════════════════════════════════════════════════════════"

# ── Baruchiro MCP Server intern starten (Port 3021) ───────────────────────────
bashio::log.info "Starte internen MCP Server auf Port ${INTERNAL_PORT}..."
paperless-mcp --http --port "${INTERNAL_PORT}" &
MCP_PID=$!

# Kurz warten bis interner Server bereit
sleep 2

# ── OAuth Proxy starten (Port 3020, öffentlich) ───────────────────────────────
bashio::log.info "Starte OAuth Proxy auf Port ${MCP_PORT}..."
exec node /app/src/oauth-proxy.js
