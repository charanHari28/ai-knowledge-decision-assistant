"""Upload limits, validation and user-facing error handling."""
import io

from reportlab.pdfgen import canvas

from app.config import settings
from conftest import SAMPLES, ask, register, upload


def make_pdf(pages=1, text="Hello policy document with some text."):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(72, 720, f"{text} Page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def post_file(client, headers, name, data, ctype="application/pdf"):
    return client.post("/api/documents", files=[("files", (name, data, ctype))], headers=headers)


def test_rejects_non_pdf_and_fake_pdf(client):
    h = register(client, "Limits Org 1", "l1@test.example")
    r = post_file(client, h, "notes.txt", b"plain text", "text/plain")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_type"
    r = post_file(client, h, "fake.pdf", (SAMPLES / "invalid" / "not_really_a_pdf.pdf").read_bytes())
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_pdf"
    r = post_file(client, h, "empty.pdf", b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_file"


def test_rejects_more_than_20_pages(client):
    h = register(client, "Limits Org 2", "l2@test.example")
    r = post_file(client, h, "long.pdf", make_pdf(pages=21))
    assert r.status_code == 400
    body = r.json()["error"]
    assert body["code"] == "too_many_pages" and "21 pages" in body["message"]
    assert post_file(client, h, "ok20.pdf", make_pdf(pages=20)).status_code == 201


def test_rejects_files_over_10mb(client):
    h = register(client, "Limits Org 3", "l3@test.example")
    big = b"%PDF-1.4\n" + b"0" * (settings.MAX_PDF_BYTES + 10)
    r = post_file(client, h, "big.pdf", big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


def test_enforces_10_document_limit(client):
    h = register(client, "Limits Org 4", "l4@test.example")
    for i in range(settings.MAX_DOCS_PER_ORG):
        assert post_file(client, h, f"doc{i}.pdf", make_pdf(text=f"Document number {i} about policy.")).status_code == 201
    r = post_file(client, h, "one_too_many.pdf", make_pdf())
    assert r.status_code == 409 and r.json()["error"]["code"] == "document_limit"
    # deleting one frees a slot (replacement flow)
    first = client.get("/api/documents", headers=h).json()["documents"][0]["id"]
    assert client.delete(f"/api/documents/{first}", headers=h).status_code == 200
    assert post_file(client, h, "replacement.pdf", make_pdf()).status_code == 201


def test_duplicate_filename_needs_delete_first(client):
    h = register(client, "Limits Org 5", "l5@test.example")
    assert post_file(client, h, "same.pdf", make_pdf()).status_code == 201
    r = post_file(client, h, "same.pdf", make_pdf())
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate"


def test_multi_upload_reports_per_file_results(client):
    h = register(client, "Limits Org 6", "l6@test.example")
    files = [("files", ("good.pdf", make_pdf(), "application/pdf")), ("files", ("bad.txt", b"x", "text/plain"))]
    r = client.post("/api/documents", files=files, headers=h)
    assert r.status_code == 201
    results = {x["filename"]: x for x in r.json()["results"]}
    assert results["good.pdf"]["ok"] is True and results["bad.txt"]["ok"] is False


def test_empty_and_too_long_questions(client, two_orgs):
    r = ask(client, two_orgs["a"]["token"], "   ")
    assert r.status_code == 400 and r.json()["error"]["code"] == "empty_question"
    r = ask(client, two_orgs["a"]["token"], "x" * 1001)
    assert r.status_code == 400 and r.json()["error"]["code"] == "question_too_long"


def test_org_with_empty_knowledge_base(client):
    h = register(client, "Empty Org", "empty@test.example")
    token = client.get("/api/assistant", headers=h).json()["token"]
    r = ask(client, token, "What is the leave policy?").json()
    assert r["outcome"] == "not_found"


def test_auth_errors(client):
    register(client, "Auth Org", "auth@test.example", "correct-horse")
    assert client.post("/api/auth/register", json={"org_name": "Dup", "email": "auth@test.example", "password": "whatever123"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "auth@test.example", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "auth@test.example", "password": "correct-horse"}).status_code == 200
    assert client.post("/api/auth/register", json={"org_name": "Weak", "email": "weak@test.example", "password": "short"}).status_code == 400


def test_usage_counters(client, two_orgs):
    ask(client, two_orgs["b"]["token"], "What is the company's stock option vesting schedule?")
    u = client.get("/api/usage", headers=two_orgs["b"]["headers"]).json()
    assert u["asked"] >= 1 and u["unable_to_answer"] >= 1
