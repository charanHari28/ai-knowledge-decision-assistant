"""Document ingestion: validate -> store privately -> extract -> chunk -> compile rules -> index."""
import json
import logging
import uuid
from pathlib import Path

from app.config import settings
from app.db import get_conn
from app.services import retrieval
from app.services.pdf_processing import DocumentError, chunk_pages, validate_and_extract
from app.services.rules import compile_rules

log = logging.getLogger("ingest")


def ingest_pdf(org_id: int, filename: str, data: bytes) -> dict:
    filename = Path(filename or "document.pdf").name[:200]  # strip any client-side path

    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM documents WHERE org_id = ? AND status != 'failed'", (org_id,)).fetchone()[0]
        duplicate = conn.execute(
            "SELECT 1 FROM documents WHERE org_id = ? AND filename = ? AND status != 'failed'", (org_id, filename)
        ).fetchone()
    if count >= settings.MAX_DOCS_PER_ORG:
        raise DocumentError(
            f"Your knowledge base already has {count} documents (limit {settings.MAX_DOCS_PER_ORG}). Delete a document before uploading another.",
            "document_limit", 409,
        )
    if duplicate:
        raise DocumentError(f"A document named '{filename}' already exists. Delete it first to upload a replacement.", "duplicate", 409)

    pages = validate_and_extract(filename, data)  # raises DocumentError with a user-facing message

    org_dir = settings.UPLOAD_DIR / str(org_id)
    org_dir.mkdir(parents=True, exist_ok=True)
    stored = org_dir / f"{uuid.uuid4().hex}.pdf"  # random name: never derived from user input
    stored.write_bytes(data)

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO documents (org_id, filename, stored_path, size_bytes, page_count, status) VALUES (?,?,?,?,?, 'processing')",
            (org_id, filename, str(stored), len(data), len(pages)),
        )
        doc_id = cur.lastrowid

    try:
        chunks = chunk_pages(pages)
        compiled = compile_rules(pages, filename)
        with get_conn() as conn:
            conn.executemany(
                "INSERT INTO chunks (org_id, document_id, page, ordinal, text) VALUES (?,?,?,?,?)",
                [(org_id, doc_id, c.page, c.ordinal, c.text) for c in chunks],
            )
            conn.executemany(
                """INSERT INTO rules (org_id, document_id, page, policy, attribute, label, value_type, operator, value, aliases, weight, source_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(org_id, doc_id, r["page"], r["policy"], r["attribute"], r["label"], r["value_type"], r["operator"],
                  json.dumps(r["value"]), json.dumps(r["aliases"]), r["weight"], r["source_text"]) for r in compiled["rules"]],
            )
            conn.execute(
                "UPDATE documents SET status='ready', chunk_count=?, rule_count=? WHERE id=? AND org_id=?",
                (len(chunks), len(compiled["rules"]), doc_id, org_id),
            )
    except Exception as exc:
        log.exception("processing failed for %s", filename)
        with get_conn() as conn:  # roll back completely so the failed upload doesn't use up the quota
            conn.execute("DELETE FROM documents WHERE id=? AND org_id=?", (doc_id, org_id))
        stored.unlink(missing_ok=True)
        raise DocumentError(f"'{filename}' was uploaded but could not be processed. Please try again.", "processing_failed", 500) from exc
    finally:
        retrieval.invalidate(org_id)

    return {"id": doc_id, "filename": filename, "pages": len(pages), "chunks": len(chunks),
            "rules": len(compiled["rules"]), "rule_compiler": compiled["compiler"]}


def delete_document(org_id: int, doc_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT stored_path FROM documents WHERE id = ? AND org_id = ?", (doc_id, org_id)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM documents WHERE id = ? AND org_id = ?", (doc_id, org_id))  # cascades to chunks/rules
    try:
        Path(row["stored_path"]).unlink(missing_ok=True)
    except OSError:
        log.warning("could not remove file for document %s", doc_id)
    retrieval.invalidate(org_id)
    return True
