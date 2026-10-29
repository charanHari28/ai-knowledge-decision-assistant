"""Authenticated admin APIs: knowledge base, assistant settings, usage.
Every query is filtered by the org_id resolved from the admin session — never by an id
supplied in the request body or URL alone."""
import json
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.db import get_conn
from app.security import AdminOrg, new_assistant_token
from app.services import llm
from app.services.ingest import delete_document, ingest_pdf
from app.services.pdf_processing import DocumentError

router = APIRouter(prefix="/api", tags=["admin"])


# ------------------------------------------------------------- knowledge base
@router.get("/documents")
def list_documents(org_id: int = AdminOrg):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, filename, size_bytes, page_count, chunk_count, rule_count, status, error, uploaded_at
               FROM documents WHERE org_id = ? ORDER BY uploaded_at DESC, id DESC""",
            (org_id,),
        ).fetchall()
    docs = [dict(r) for r in rows]
    return {
        "documents": docs,
        "limits": {
            "max_documents": settings.MAX_DOCS_PER_ORG,
            "max_pages": settings.MAX_PAGES_PER_PDF,
            "max_mb": settings.MAX_PDF_BYTES // (1024 * 1024),
            "used_documents": len([d for d in docs if d["status"] != "failed"]),
        },
    }


@router.post("/documents", status_code=201)
async def upload_documents(files: List[UploadFile] = File(...), org_id: int = AdminOrg):
    """Accepts one or more PDFs. Each file is validated and processed independently, so one bad
    file does not block the others; per-file results/errors are returned."""
    if not files:
        raise HTTPException(400, "No file was uploaded.")
    results = []
    for f in files:
        data = await f.read(settings.MAX_PDF_BYTES + 1)  # read at most limit+1 bytes
        try:
            if len(data) > settings.MAX_PDF_BYTES:
                raise DocumentError(f"'{f.filename}' exceeds the {settings.MAX_PDF_BYTES // (1024 * 1024)} MB limit.", "file_too_large", 413)
            results.append({"ok": True, **ingest_pdf(org_id, f.filename, data)})
        except DocumentError as exc:
            results.append({"ok": False, "filename": f.filename, "code": exc.code, "error": exc.message})
    status_ok = any(r["ok"] for r in results)
    if not status_ok and len(results) == 1:
        r = results[0]
        raise DocumentError(r["error"], r["code"], 413 if r["code"] == "file_too_large" else (409 if r["code"] in ("document_limit", "duplicate") else 400))
    return {"results": results}


@router.delete("/documents/{doc_id}")
def remove_document(doc_id: int, org_id: int = AdminOrg):
    if not delete_document(org_id, doc_id):
        raise HTTPException(404, "Document not found.")  # also returned for other orgs' ids: no existence leak
    return {"ok": True}


@router.get("/documents/{doc_id}/rules")
def document_rules(doc_id: int, org_id: int = AdminOrg):
    """Shows the decision rules compiled from a document (transparency for admins)."""
    with get_conn() as conn:
        doc = conn.execute("SELECT id, filename FROM documents WHERE id = ? AND org_id = ?", (doc_id, org_id)).fetchone()
        if not doc:
            raise HTTPException(404, "Document not found.")
        rows = conn.execute(
            "SELECT policy, label, attribute, value_type, operator, value, page, source_text FROM rules WHERE document_id = ? AND org_id = ? ORDER BY policy, id",
            (doc_id, org_id),
        ).fetchall()
    return {"document": dict(doc), "rules": [{**dict(r), "value": json.loads(r["value"])} for r in rows]}


# ------------------------------------------------------------- assistant
def _assistant_payload(org_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT token, name, created_at, rotated_at FROM assistants WHERE org_id = ?", (org_id,)).fetchone()
    base = settings.PUBLIC_BASE_URL
    url = f"{base}/a/{row['token']}"
    return {
        "name": row["name"],
        "token": row["token"],
        "url": url,
        "rotated_at": row["rotated_at"],
        "embed": {
            "iframe": f'<iframe src="{url}?embed=1" title="{row["name"]}" style="width:100%;max-width:420px;height:600px;border:1px solid #ddd;border-radius:12px" loading="lazy"></iframe>',
            "script": f'<script src="{base}/embed.js" data-assistant="{row["token"]}" async></script>',
        },
        "llm": llm.provider_label(),
    }


@router.get("/assistant")
def get_assistant(org_id: int = AdminOrg):
    return _assistant_payload(org_id)


@router.post("/assistant/regenerate")
def regenerate_token(org_id: int = AdminOrg):
    """Rotates the public token. The old URL and every embed using it stop working immediately."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE assistants SET token = ?, rotated_at = datetime('now') WHERE org_id = ?",
            (new_assistant_token(), org_id),
        )
    return _assistant_payload(org_id)


# ------------------------------------------------------------- usage
@router.get("/usage")
def usage(org_id: int = AdminOrg):
    with get_conn() as conn:
        rows = conn.execute("SELECT outcome, COUNT(*) AS n FROM questions WHERE org_id = ? GROUP BY outcome", (org_id,)).fetchall()
        by_type = conn.execute(
            "SELECT question_type, COUNT(*) AS n FROM questions WHERE org_id = ? GROUP BY question_type", (org_id,)
        ).fetchall()
        recent = conn.execute(
            "SELECT question, question_type, outcome, decision, latency_ms, created_at FROM questions WHERE org_id = ? ORDER BY id DESC LIMIT 15",
            (org_id,),
        ).fetchall()
    counts = {r["outcome"]: r["n"] for r in rows}
    return {
        "asked": sum(counts.values()),
        "answered": counts.get("answered", 0),
        "unable_to_answer": counts.get("not_found", 0),
        "needs_review": counts.get("needs_info", 0) + counts.get("needs_review", 0) + counts.get("error", 0),
        "by_type": {(r["question_type"] or "unknown"): r["n"] for r in by_type},
        "recent": [dict(r) for r in recent],
    }
