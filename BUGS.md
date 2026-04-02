# Bug & Issue Tracker — Paperless-ngx MCP Addon

## Status: Smoke Test 2026-04-02 ✅

---

## 🔴 BUG-001: get_document_thumbnail — Validierungsfehler bei Binärrückgabe

**Severity:** Medium  
**Status:** Open  
**Komponente:** baruchiro/paperless-mcp (upstream)

**Beschreibung:**  
`get_document_thumbnail` schlägt mit einem Validierungsfehler fehl statt ein Thumbnail zu liefern.

**Repro-Schritte:**
1. MCP Tool `get_document_thumbnail` mit beliebiger Dokument-ID aufrufen
2. z.B. `get_document_thumbnail({ id: 2925 })`

**Expected:** Base64-kodiertes WebP-Bild wird zurückgegeben  
**Actual:** Tool-/Response-Validierungsfehler, kein Bild

**Einschätzung:** Bug in der Binärressourcen-Verarbeitung im upstream baruchiro/paperless-mcp.  
Workaround: Dokument-URL direkt aufrufen (`/api/documents/<id>/thumb/`)

---

## 🟡 INFO-001: post_document erwartet Base64, keinen Dateipfad

**Severity:** Info / Dokumentation  
**Status:** Dokumentiert  
**Komponente:** baruchiro/paperless-mcp (upstream, by design)

**Beschreibung:**  
`post_document` akzeptiert nur Base64-kodierte Dateiinhalte, keinen lokalen Dateipfad.

**Korrekte Verwendung:**
```json
{
  "file": "<base64-encoded-pdf-content>",
  "filename": "dokument.pdf",
  "title": "Mein Dokument",
  "created": "2025-03-15"
}
```

**Hinweis:** Das ist kein Bug sondern Design. Claude muss die Datei zuerst lesen 
und als Base64 übergeben.

---

## 🟡 INFO-002: created_date wird aus PDF-Inhalt abgeleitet

**Severity:** Info  
**Status:** Beobachtet, kein Bug  
**Komponente:** Paperless-ngx (by design)

**Beschreibung:**  
Beim Upload eines PDFs setzt Paperless das `created_date` nicht auf das Upload-Datum,
sondern leitet es aus dem PDF-Metadaten oder OCR-Inhalt ab.

**Beispiel:** Upload am 2026-04-02, gesetztes Datum: 2026-02-04

**Einschätzung:** Normales Paperless-Verhalten. Kann mit explizitem `created`-Parameter
beim Upload übersteuert werden:
```json
{ "created": "2026-04-02" }
```

---

## ✅ VERIFIZIERT — Funktioniert korrekt

| Tool | Status |
|---|---|
| list_documents | ✅ |
| list_tags | ✅ |
| list_document_types | ✅ |
| list_correspondents | ✅ |
| list_custom_fields | ✅ |
| get_document | ✅ |
| get_document_content | ✅ |
| search_documents | ✅ |
| post_document | ✅ (Base64) |
| get_document_thumbnail | ❌ BUG-001 |
| download_document | ⚠️ Nicht verifiziert |

---

## 📋 Empfohlene nächste Tests

### Smoke Test 2 — Update-Operationen (Testdokument ID 2925)
- [ ] Titel ändern via `update_document`
- [ ] Tag hinzufügen via `bulk_edit_documents` (add_tag)
- [ ] Korrespondent setzen
- [ ] Custom Field setzen
- [ ] Dokument danach wieder löschen (Cleanup)

### Sicherheitscheck
- [ ] Cloudflare Access Service Token einrichten
- [ ] Verifizieren dass `/mcp` ohne Token nicht erreichbar ist
