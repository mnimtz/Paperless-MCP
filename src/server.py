"""
Paperless-ngx MCP Server
FastMCP + uvicorn ASGI

Middleware-Stack (von außen nach innen):
  OAuthMiddleware → BearerAuthMiddleware → mcp.sse_app()

Alle MCP-Tools sprechen die Paperless REST API über PaperlessClient.
"""

import os
import sys
import json
import logging
import asyncio
from typing import Optional

import uvicorn
from mcp.server.sse import SseServerTransport
from mcp.server import Server
from mcp import types

from auth import BearerAuthMiddleware
from oauth import OAuthMiddleware
from paperless_client import PaperlessClient

# ── Logging Setup ─────────────────────────────────────────────────────────────
log_level = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
# Drittbibliotheken ruhigstellen
for noisy in ("mcp.server.sse", "urllib3", "uvicorn.access", "httpx"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("paperless-mcp")

# ── MCP Server + Client ───────────────────────────────────────────────────────
server = Server("paperless-ngx-mcp")
client = PaperlessClient()

# ── MCP Tools ─────────────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_documents",
            description="Volltext-Suche in Paperless-ngx. Kombiniert Suchbegriff mit optionalen Filtern.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Suchbegriff (Volltext)"},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 10, "maximum": 100},
                    "correspondent_name": {"type": "string", "description": "Korrespondent (Teilstring)"},
                    "document_type_name": {"type": "string", "description": "Dokumenttyp (Teilstring)"},
                    "tag_name": {"type": "string", "description": "Tag-Name (Teilstring)"},
                    "created_after": {"type": "string", "description": "Erstellt nach YYYY-MM-DD"},
                    "created_before": {"type": "string", "description": "Erstellt vor YYYY-MM-DD"},
                },
            },
        ),
        types.Tool(
            name="get_document",
            description="Einzelnes Dokument abrufen — inkl. vollem OCR-Text, Tags, Korrespondent, Typ.",
            inputSchema={
                "type": "object",
                "required": ["document_id"],
                "properties": {
                    "document_id": {"type": "integer", "description": "Dokument-ID"},
                },
            },
        ),
        types.Tool(
            name="get_document_content",
            description="OCR-Text eines Dokuments für Q&A lesen.",
            inputSchema={
                "type": "object",
                "required": ["document_id"],
                "properties": {
                    "document_id": {"type": "integer"},
                },
            },
        ),
        types.Tool(
            name="update_document",
            description="Dokumentmetadaten aktualisieren: Titel, Korrespondent, Dokumenttyp, Datum.",
            inputSchema={
                "type": "object",
                "required": ["document_id"],
                "properties": {
                    "document_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "correspondent_id": {"type": "integer"},
                    "document_type_id": {"type": "integer"},
                    "created_date": {"type": "string", "description": "YYYY-MM-DD"},
                },
            },
        ),
        types.Tool(
            name="add_tag_to_document",
            description="Tag zu einem Dokument hinzufügen. Bestehende Tags bleiben erhalten.",
            inputSchema={
                "type": "object",
                "required": ["document_id", "tag_id"],
                "properties": {
                    "document_id": {"type": "integer"},
                    "tag_id": {"type": "integer"},
                },
            },
        ),
        types.Tool(
            name="list_tags",
            description="Alle Tags aus Paperless auflisten (sortiert nach Dokumentanzahl).",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_size": {"type": "integer", "default": 50},
                },
            },
        ),
        types.Tool(
            name="create_tag",
            description="Neuen Tag anlegen.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string", "default": "#3498db", "description": "Hex-Farbe"},
                },
            },
        ),
        types.Tool(
            name="list_correspondents",
            description="Alle Korrespondenten auflisten.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_size": {"type": "integer", "default": 50},
                },
            },
        ),
        types.Tool(
            name="create_correspondent",
            description="Neuen Korrespondenten anlegen.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="list_document_types",
            description="Alle Dokumenttypen auflisten.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_size": {"type": "integer", "default": 50},
                },
            },
        ),
        types.Tool(
            name="create_document_type",
            description="Neuen Dokumenttyp anlegen.",
            inputSchema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="get_archive_stats",
            description="Statistik über das Paperless-Archiv: Anzahl Dokumente, Tags, Korrespondenten, Typen.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="build_lookup_cache",
            description="Lädt alle Tags, Korrespondenten und Typen als ID→Name Tabelle. Für intelligente Suche verwenden.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        log.error(f"Tool {name} error: {e}", exc_info=True)
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "search_documents":
        filters = {}
        if args.get("correspondent_name"):
            filters["correspondent__name__icontains"] = args["correspondent_name"]
        if args.get("document_type_name"):
            filters["document_type__name__icontains"] = args["document_type_name"]
        if args.get("tag_name"):
            filters["tags__name__icontains"] = args["tag_name"]
        if args.get("created_after"):
            filters["created__date__gte"] = args["created_after"]
        if args.get("created_before"):
            filters["created__date__lte"] = args["created_before"]
        return await client.search_documents(
            query=args.get("query", ""),
            page=args.get("page", 1),
            page_size=args.get("page_size", 10),
            **filters,
        )

    elif name == "get_document":
        return await client.get_document(args["document_id"])

    elif name == "get_document_content":
        content = await client.get_document_content(args["document_id"])
        return {"document_id": args["document_id"], "content": content}

    elif name == "update_document":
        fields = {}
        for field in ("title", "created_date"):
            if args.get(field):
                fields[field] = args[field]
        if args.get("correspondent_id"):
            fields["correspondent"] = args["correspondent_id"]
        if args.get("document_type_id"):
            fields["document_type"] = args["document_type_id"]
        return await client.update_document(args["document_id"], **fields)

    elif name == "add_tag_to_document":
        return await client.add_tag_to_document(args["document_id"], args["tag_id"])

    elif name == "list_tags":
        return await client.list_tags(page_size=args.get("page_size", 50))

    elif name == "create_tag":
        return await client.create_tag(args["name"], args.get("color", "#3498db"))

    elif name == "list_correspondents":
        return await client.list_correspondents(page_size=args.get("page_size", 50))

    elif name == "create_correspondent":
        return await client.create_correspondent(args["name"])

    elif name == "list_document_types":
        return await client.list_document_types(page_size=args.get("page_size", 50))

    elif name == "create_document_type":
        return await client.create_document_type(args["name"])

    elif name == "get_archive_stats":
        return await client.get_stats()

    elif name == "build_lookup_cache":
        return await client.build_lookup_cache()

    else:
        return {"error": f"Unbekanntes Tool: {name}"}


# ── ASGI App zusammenbauen ────────────────────────────────────────────────────

def build_app():
    sse = SseServerTransport("/messages")

    async def handle_sse(scope, receive, send):
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(
                streams[0], streams[1],
                server.create_initialization_options()
            )

    async def asgi_app(scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/sse":
            await handle_sse(scope, receive, send)
        elif scope["type"] == "http" and scope["path"] == "/messages":
            await sse.handle_post_message(scope, receive, send)
        else:
            await send({"type": "http.response.start", "status": 404,
                        "headers": [[b"content-type", b"application/json"]]})
            await send({"type": "http.response.body",
                        "body": b'{"error": "not found"}'})

    # Middleware-Stack: OAuth → Bearer → MCP
    app = OAuthMiddleware(BearerAuthMiddleware(asgi_app))
    return app


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "3020"))
    log.info(f"Paperless-ngx MCP Server startet auf Port {port}")

    app = build_app()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
