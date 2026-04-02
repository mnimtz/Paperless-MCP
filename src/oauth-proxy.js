/**
 * OAuth 2.0 Proxy für paperless-mcp
 * Läuft auf Port 3020 (öffentlich)
 * Leitet /mcp weiter an internen paperless-mcp auf Port 3021
 * 
 * Routen:
 *   GET  /.well-known/oauth-authorization-server  → Discovery
 *   GET  /.well-known/oauth-protected-resource    → Resource Metadata  
 *   GET  /oauth/authorize                          → HTML Bestätigungsseite
 *   POST /oauth/authorize                          → Code ausstellen
 *   POST /oauth/token                              → Token austauschen
 *   GET  /download/<id>                          → PDF Download (Auth via ?token=...)
 *   GET  /download/<id>?original=true            → Original-Datei Download
 *   *    /mcp                                      → Proxy zu Port 3021
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const url = require('url');

const PUBLIC_URL    = (process.env.PAPERLESS_PUBLIC_URL || 'http://localhost:3020').replace(/\/$/, '');
const BEARER_TOKEN  = process.env.BEARER_TOKEN  || '';
const CLIENT_ID     = process.env.OAUTH_CLIENT_ID     || '';
const CLIENT_SECRET = process.env.OAUTH_CLIENT_SECRET || '';
const PUBLIC_PORT   = parseInt(process.env.MCP_PORT || '3020');
const INTERNAL_PORT = PUBLIC_PORT + 1; // baruchiro läuft hier

// In-Memory Auth-Code Store
const authCodes = new Map();
const CODE_TTL = 600_000; // 10 min

// ── Helpers ───────────────────────────────────────────────────────────────────

function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

function sendHtml(res, html) {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  res.end(html);
}

function redirect(res, location) {
  res.writeHead(302, { Location: location });
  res.end();
}

function readBody(req) {
  return new Promise(resolve => {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => resolve(body));
  });
}

function parseForm(body) {
  return Object.fromEntries(new URLSearchParams(body));
}

function parseQuery(reqUrl) {
  return Object.fromEntries(new URL(reqUrl, 'http://x').searchParams);
}

// ── OAuth Discovery ───────────────────────────────────────────────────────────

function authServerMeta() {
  return {
    issuer: PUBLIC_URL,
    authorization_endpoint: `${PUBLIC_URL}/oauth/authorize`,
    token_endpoint: `${PUBLIC_URL}/oauth/token`,
    token_endpoint_auth_methods_supported: ['client_secret_post'],
    grant_types_supported: ['authorization_code'],
    response_types_supported: ['code'],
    scopes_supported: ['paperless'],
  };
}

function protectedResourceMeta() {
  return {
    resource: `${PUBLIC_URL}/mcp`,
    authorization_servers: [PUBLIC_URL],
    bearer_methods_supported: ['header'],
  };
}

// ── HTML Authorize Page ───────────────────────────────────────────────────────

function authorizeHtml(clientId, redirectUri, state) {
  return `<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paperless-ngx — Zugriff erlauben</title>
<style>
  body{font-family:-apple-system,sans-serif;background:#f1f5f9;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;box-sizing:border-box}
  .card{background:white;border-radius:16px;padding:32px;max-width:420px;width:100%;box-shadow:0 4px 24px rgba(0,0,0,.08)}
  h1{font-size:20px;margin:0 0 8px;color:#1e293b}.icon{font-size:40px;margin-bottom:16px}
  p{color:#64748b;font-size:14px;line-height:1.6;margin:0 0 20px}
  .app{background:#f1f5f9;border-radius:8px;padding:12px;font-size:13px;color:#475569;margin-bottom:20px}
  .perm{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #f1f5f9;font-size:14px}
  .perm:last-child{border:none}.perms{margin-bottom:24px}
  .btns{display:flex;gap:10px}
  .allow{flex:1;background:#3b82f6;color:white;border:none;border-radius:8px;padding:12px;font-size:14px;font-weight:600;cursor:pointer}
  .allow:hover{background:#2563eb}
  .deny{flex:1;background:white;color:#64748b;border:1px solid #e2e8f0;border-radius:8px;padding:12px;font-size:14px;cursor:pointer}
</style></head>
<body><div class="card">
  <div class="icon">📚</div>
  <h1>Zugriff auf Paperless-ngx</h1>
  <p>Eine Anwendung möchte auf dein Dokumentenarchiv zugreifen.</p>
  <div class="app"><strong>App:</strong> ${clientId}</div>
  <div class="perms">
    <div class="perm">🔍 Dokumente suchen und lesen</div>
    <div class="perm">🏷️ Tags und Korrespondenten lesen</div>
    <div class="perm">✏️ Metadaten bearbeiten</div>
  </div>
  <form method="POST">
    <input type="hidden" name="client_id" value="${clientId}">
    <input type="hidden" name="redirect_uri" value="${redirectUri}">
    <input type="hidden" name="state" value="${state}">
    <div class="btns">
      <button type="submit" name="action" value="allow" class="allow">✅ Erlauben</button>
      <button type="submit" name="action" value="deny"  class="deny">✕ Ablehnen</button>
    </div>
  </form>
</div></body></html>`;
}

// ── MCP Tool-Call Interceptor ─────────────────────────────────────────────────
// Fängt download_document und get_document_thumbnail ab bevor sie
// zum baruchiro-Server weitergeleitet werden (dort 424-Bug).

async function interceptMcpToolCall(req, res, body) {
  let parsed;
  try { parsed = JSON.parse(body); } catch { return false; }

  // Nur tool-Aufrufe abfangen
  if (parsed.method !== 'tools/call') return false;

  const toolName = parsed.params?.name;
  const args     = parsed.params?.arguments || {};
  const id       = parsed.id;

  // download_document → Download-Link zurückgeben
  if (toolName === 'download_document') {
    const docId   = args.id;
    const original = args.original === true;
    const downloadUrl = `${PUBLIC_URL}/download/${docId}?token=${BEARER_TOKEN}${original ? '&original=true' : ''}`;

    const result = {
      jsonrpc: '2.0',
      id,
      result: {
        content: [{
          type: 'text',
          text: JSON.stringify({
            document_id: docId,
            download_url: downloadUrl,
            original: original,
            message: `Klicke den Link um das Dokument herunterzuladen: ${downloadUrl}`
          }, null, 2)
        }]
      }
    };
    sendJson(res, 200, result);
    return true;
  }

  // get_document_thumbnail → klaren Fehler zurückgeben statt 424
  if (toolName === 'get_document_thumbnail') {
    const docId = args.id;
    const thumbUrl = `${PUBLIC_URL}/download/${docId}?token=${BEARER_TOKEN}`;
    const result = {
      jsonrpc: '2.0',
      id,
      result: {
        content: [{
          type: 'text',
          text: JSON.stringify({
            document_id: docId,
            thumbnail_unavailable: true,
            reason: 'Thumbnail-Binärrückgabe wird nicht unterstützt (upstream baruchiro Bug #424)',
            alternative: `Dokument als PDF herunterladen: ${thumbUrl}`
          }, null, 2)
        }]
      }
    };
    sendJson(res, 200, result);
    return true;
  }

  return false; // nicht abgefangen → normal weiterleiten
}

// ── Proxy zu internem MCP Server ──────────────────────────────────────────────

function proxyToInternal(req, res, bodyBuffer) {
  const options = {
    hostname: '127.0.0.1',
    port: INTERNAL_PORT,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: `127.0.0.1:${INTERNAL_PORT}` },
  };

  const proxy = http.request(options, internalRes => {
    res.writeHead(internalRes.statusCode, internalRes.headers);
    internalRes.pipe(res);
  });

  proxy.on('error', err => {
    console.error('Proxy error:', err.message);
    sendJson(res, 502, { error: 'upstream_unavailable' });
  });

  if (bodyBuffer !== undefined) {
    // Body bereits gelesen — direkt schreiben
    proxy.write(bodyBuffer);
    proxy.end();
  } else {
    req.pipe(proxy);
  }
}

// ── Download Route ────────────────────────────────────────────────────────────

async function handleDownload(req, res, docId, original) {
  const paperlessUrl = (process.env.PAPERLESS_URL || '').replace(/\/$/, '');
  const apiKey       = process.env.PAPERLESS_API_KEY || '';

  const suffix = original ? '?original=true' : '';
  const target = `${paperlessUrl}/api/documents/${docId}/download/${suffix}`;

  console.log(`Download: doc #${docId} → ${target}`);

  const mod = target.startsWith('https') ? require('https') : require('http');
  const preq = mod.get(target, { headers: { Authorization: `Token ${apiKey}` } }, pres => {
    if (pres.statusCode === 404) {
      return sendJson(res, 404, { error: 'document_not_found', id: docId });
    }
    if (pres.statusCode !== 200) {
      return sendJson(res, 502, { error: 'upstream_error', status: pres.statusCode });
    }

    // Filename aus Content-Disposition übernehmen oder Fallback
    const cd = pres.headers['content-disposition'] || `attachment; filename="document-${docId}.pdf"`;
    const ct = pres.headers['content-type'] || 'application/pdf';

    res.writeHead(200, {
      'Content-Type': ct,
      'Content-Disposition': cd,
    });
    pres.pipe(res);
  });

  preq.on('error', err => {
    console.error('Download error:', err.message);
    sendJson(res, 502, { error: 'upstream_unavailable' });
  });
}

// ── Token-in-URL Auth Check ────────────────────────────────────────────────────

function checkAuthWithQuery(req) {
  if (!BEARER_TOKEN) return true;
  // 1. Bearer Header
  const auth = req.headers['authorization'] || '';
  if (auth === `Bearer ${BEARER_TOKEN}`) return true;
  // 2. ?token=... Query Parameter (für Browser-Downloads)
  const q = parseQuery(req.url);
  if (q.token === BEARER_TOKEN) return true;
  return false;
}


// ── Whitelist (kein Auth nötig) ────────────────────────────────────────────────

const NO_AUTH = ['/.well-known/', '/oauth/', '/health'];

function needsAuth(path) {
  return !NO_AUTH.some(p => path.startsWith(p));
}

// ── Main Request Handler ──────────────────────────────────────────────────────

async function handler(req, res) {
  const { pathname } = new URL(req.url, 'http://x');
  const method = req.method;

  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
  if (method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // Health
  if (pathname === '/health') {
    return sendJson(res, 200, { status: 'ok', service: 'paperless-mcp' });
  }

  // OAuth Discovery
  if (pathname === '/.well-known/oauth-authorization-server') {
    return sendJson(res, 200, authServerMeta());
  }
  if (pathname === '/.well-known/oauth-protected-resource') {
    return sendJson(res, 200, protectedResourceMeta());
  }

  // GET /oauth/authorize → HTML
  if (pathname === '/oauth/authorize' && method === 'GET') {
    const q = parseQuery(req.url);
    if (q.client_id !== CLIENT_ID) return sendJson(res, 401, { error: 'invalid_client' });
    return sendHtml(res, authorizeHtml(q.client_id, q.redirect_uri, q.state || ''));
  }

  // POST /oauth/authorize → code ausstellen
  if (pathname === '/oauth/authorize' && method === 'POST') {
    const body = parseForm(await readBody(req));
    if (body.action !== 'allow') {
      const loc = `${body.redirect_uri}?error=access_denied${body.state ? '&state='+encodeURIComponent(body.state) : ''}`;
      return redirect(res, loc);
    }
    if (body.client_id !== CLIENT_ID) return sendJson(res, 401, { error: 'invalid_client' });

    const code = crypto.randomBytes(32).toString('base64url');
    authCodes.set(code, { clientId: body.client_id, redirectUri: body.redirect_uri, expiresAt: Date.now() + CODE_TTL });
    setTimeout(() => authCodes.delete(code), CODE_TTL);

    const loc = `${body.redirect_uri}?code=${code}${body.state ? '&state='+encodeURIComponent(body.state) : ''}`;
    return redirect(res, loc);
  }

  // POST /oauth/token → access_token
  if (pathname === '/oauth/token' && method === 'POST') {
    const body = parseForm(await readBody(req));
    if (body.grant_type !== 'authorization_code') return sendJson(res, 400, { error: 'unsupported_grant_type' });
    if (body.client_id !== CLIENT_ID || body.client_secret !== CLIENT_SECRET) return sendJson(res, 401, { error: 'invalid_client' });

    const entry = authCodes.get(body.code);
    if (!entry || Date.now() > entry.expiresAt) return sendJson(res, 400, { error: 'invalid_grant' });
    authCodes.delete(body.code);

    return sendJson(res, 200, { access_token: BEARER_TOKEN, token_type: 'bearer', scope: 'paperless' });
  }

  // GET /download/<id> → PDF direkt ausliefern
  // Unterstützt ?token=... für Browser-Downloads
  // Optional: ?original=true für Originaldatei statt archivierter Version
  const dlMatch = pathname.match(/^\/download\/(\d+)$/);
  if (dlMatch && method === 'GET') {
    const q = parseQuery(req.url);
    if (!checkAuthWithQuery(req)) {
      res.setHeader('WWW-Authenticate', 'Bearer realm="paperless-mcp"');
      return sendJson(res, 401, { error: 'unauthorized', hint: 'Add ?token=<bearer_token> to the URL' });
    }
    return handleDownload(req, res, dlMatch[1], q.original === 'true');
  }

  // GET /download-url/<id> → gibt fertigen Download-Link zurück (für Claude/ChatGPT)
  // Claude ruft diesen Endpoint auf und bekommt den klickbaren Link als Text zurück
  const dlUrlMatch = pathname.match(/^\/download-url\/(\d+)$/);
  if (dlUrlMatch && method === 'GET') {
    if (!checkAuthWithQuery(req)) {
      res.setHeader('WWW-Authenticate', 'Bearer realm="paperless-mcp"');
      return sendJson(res, 401, { error: 'unauthorized' });
    }
    const docId = dlUrlMatch[1];
    const q = parseQuery(req.url);
    const original = q.original === 'true';
    const downloadUrl = `${PUBLIC_URL}/download/${docId}?token=${BEARER_TOKEN}${original ? '&original=true' : ''}`;
    return sendJson(res, 200, {
      document_id: parseInt(docId),
      download_url: downloadUrl,
      original: original,
      hint: 'Diesen Link im Browser öffnen um das Dokument herunterzuladen'
    });
  }

  // Auth prüfen für alle anderen Routen
  if (needsAuth(pathname) && !checkAuthWithQuery(req)) {
    res.setHeader('WWW-Authenticate', 'Bearer realm="paperless-mcp"');
    return sendJson(res, 401, { error: 'unauthorized' });
  }

  // Alles andere → Body nur bei POST/PUT lesen
  const needsBody = ['POST', 'PUT', 'PATCH'].includes(method);
  const body = needsBody ? await readBody(req) : undefined;

  // MCP POST /mcp → Tool-Call Interceptor
  if (pathname === '/mcp' && method === 'POST' && body) {
    const intercepted = await interceptMcpToolCall(req, res, body);
    if (intercepted) return;
  }

  // Nicht abgefangen → an internen Server weiterleiten
  proxyToInternal(req, res, body);
}

// ── Start ─────────────────────────────────────────────────────────────────────

const server = http.createServer((req, res) => {
  handler(req, res).catch(err => {
    console.error('Handler error:', err);
    sendJson(res, 500, { error: 'internal_error' });
  });
});

server.listen(PUBLIC_PORT, '0.0.0.0', () => {
  console.log(`OAuth Proxy listening on port ${PUBLIC_PORT}`);
  console.log(`Forwarding /mcp to internal port ${INTERNAL_PORT}`);
});
