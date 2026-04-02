"""
Paperless-ngx API Client
Spricht die Paperless REST API an.
Alle wichtigen Erkenntnisse aus unserem Entwicklungsprozess:
- Trailing Slashes sind Pflicht (Cloudflare/Django)
- List-Endpoints geben Tags/Correspondent als IDs zurück (nicht Objekte)
- Detail-Endpoints (/api/documents/<id>/) geben nested Objekte zurück
- page_size=500 für Tags/Correspondents, zwei Seiten für >500 Correspondents
"""

import os
import json
import logging
import urllib.parse
from typing import Optional

import httpx

log = logging.getLogger(__name__)


class PaperlessClient:
    def __init__(self):
        self.base_url = os.environ.get("PAPERLESS_URL", "").rstrip("/")
        self.api_key = os.environ.get("PAPERLESS_API_KEY", "")
        self._headers = {
            "Authorization": f"Token {self.api_key}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        """Baut die vollständige URL. Trailing Slash wird sichergestellt."""
        if not path.endswith("/") and "?" not in path:
            path = path + "/"
        return f"{self.base_url}{path}"

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = self._url(path)
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers)
            r.raise_for_status()
            return r.json()

    async def _patch(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.patch(
                self._url(path), headers={**self._headers, "Content-Type": "application/json"},
                content=json.dumps(data)
            )
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self._url(path), headers={**self._headers, "Content-Type": "application/json"},
                content=json.dumps(data)
            )
            r.raise_for_status()
            return r.json()

    async def _post_multipart(self, path: str, files: dict, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                self._url(path), headers={"Authorization": f"Token {self.api_key}"},
                files=files, data=data
            )
            r.raise_for_status()
            return r.json()

    # ── Lookup-Cache ──────────────────────────────────────────────────────────

    async def build_lookup_cache(self) -> dict:
        """
        Lädt Tags, Korrespondenten und Dokumenttypen als ID→Name Maps.
        Notwendig weil List-Endpoints nur IDs zurückgeben.
        """
        tags_data = await self._get("/api/tags", {"page_size": 500})
        tags = {t["id"]: t["name"] for t in tags_data.get("results", [])}

        types_data = await self._get("/api/document_types", {"page_size": 500})
        types = {t["id"]: t["name"] for t in types_data.get("results", [])}

        corr_map = {}
        for page in [1, 2]:
            corr_data = await self._get("/api/correspondents", {"page_size": 500, "page": page})
            corr_map.update({c["id"]: c["name"] for c in corr_data.get("results", [])})
            if not corr_data.get("next"):
                break

        return {"tags": tags, "types": types, "correspondents": corr_map}

    # ── Dokumente ─────────────────────────────────────────────────────────────

    async def search_documents(self, query: str = "", page: int = 1,
                                page_size: int = 10, **filters) -> dict:
        params = {"page": page, "page_size": page_size, "ordering": "-created"}
        if query:
            params["query"] = query
        params.update(filters)
        return await self._get("/api/documents", params)

    async def get_document(self, doc_id: int) -> dict:
        """Detail-Endpoint gibt nested Objekte zurück — kein Cache nötig."""
        return await self._get(f"/api/documents/{doc_id}")

    async def get_document_content(self, doc_id: int) -> str:
        """OCR-Text eines Dokuments."""
        doc = await self.get_document(doc_id)
        return doc.get("content", "")

    async def update_document(self, doc_id: int, **fields) -> dict:
        return await self._patch(f"/api/documents/{doc_id}", fields)

    async def add_tag_to_document(self, doc_id: int, tag_id: int) -> dict:
        """Sicheres Tag-Hinzufügen — bestehende Tags bleiben erhalten."""
        doc = await self.get_document(doc_id)
        existing = [t["id"] if isinstance(t, dict) else t for t in doc.get("tags", [])]
        if tag_id not in existing:
            existing.append(tag_id)
        return await self._patch(f"/api/documents/{doc_id}", {"tags": existing})

    async def bulk_edit(self, document_ids: list, method: str, **params) -> dict:
        payload = {"documents": document_ids, "method": method, "parameters": params}
        return await self._post("/api/documents/bulk_edit", payload)

    # ── Tags ──────────────────────────────────────────────────────────────────

    async def list_tags(self, page_size: int = 100) -> dict:
        return await self._get("/api/tags", {"page_size": page_size,
                                              "ordering": "-document_count"})

    async def create_tag(self, name: str, color: str = "#3498db") -> dict:
        return await self._post("/api/tags", {"name": name, "color": color})

    # ── Korrespondenten ───────────────────────────────────────────────────────

    async def list_correspondents(self, page_size: int = 50) -> dict:
        return await self._get("/api/correspondents", {"page_size": page_size,
                                                        "ordering": "-document_count"})

    async def create_correspondent(self, name: str) -> dict:
        return await self._post("/api/correspondents", {"name": name})

    # ── Dokumenttypen ─────────────────────────────────────────────────────────

    async def list_document_types(self, page_size: int = 100) -> dict:
        return await self._get("/api/document_types", {"page_size": page_size,
                                                         "ordering": "-document_count"})

    async def create_document_type(self, name: str) -> dict:
        return await self._post("/api/document_types", {"name": name})

    # ── Statistik ─────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        docs = await self._get("/api/documents", {"page_size": 1})
        tags = await self._get("/api/tags", {"page_size": 1})
        corrs = await self._get("/api/correspondents", {"page_size": 1})
        types = await self._get("/api/document_types", {"page_size": 1})
        return {
            "documents": docs.get("count", 0),
            "tags": tags.get("count", 0),
            "correspondents": corrs.get("count", 0),
            "document_types": types.get("count", 0),
        }
