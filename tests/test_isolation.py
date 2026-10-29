"""Multi-tenant isolation and access-control tests."""
from app.config import settings
from app.services import retrieval
from app.db import get_conn
from conftest import ask


def test_each_assistant_answers_from_its_own_documents(client, two_orgs):
    a = ask(client, two_orgs["a"]["token"], "What time do the hostel gates close?").json()
    assert a["outcome"] == "answered"
    assert {r["document"] for r in a["references"]} <= {"Scholarship_Rules.pdf", "Academic_Policies.pdf", "Hostel_Handbook.pdf"}

    b = ask(client, two_orgs["b"]["token"], "How many days of annual leave do employees get?").json()
    assert b["outcome"] == "answered"
    assert {r["document"] for r in b["references"]} <= {"Leave_Policy.pdf", "Work_From_Home_Policy.pdf", "Learning_Assistance_Policy.pdf"}


def test_org_b_cannot_see_org_a_knowledge(client, two_orgs):
    r = ask(client, two_orgs["b"]["token"], "What is the GPA requirement for the Merit Scholarship?").json()
    assert r["outcome"] == "not_found"
    assert r["references"] == []
    assert "8.5" not in r["answer"]


def test_org_a_cannot_see_org_b_knowledge(client, two_orgs):
    r = ask(client, two_orgs["a"]["token"], "How many days of paternity leave do employees get?").json()
    assert r["outcome"] == "not_found"
    assert "10 working days" not in r["answer"]


def test_org_a_decision_rules_not_used_for_org_b(client, two_orgs):
    r = ask(client, two_orgs["b"]["token"], "I am in 3rd year with a GPA of 9.0. Am I eligible for the Merit Scholarship?").json()
    assert all(d["policy"] != "Merit Scholarship" for d in r["decisions"])


def test_retrieval_index_contains_only_own_chunks(two_orgs):
    with get_conn() as conn:
        org_ids = {row["org_id"]: row["id"] for row in conn.execute("SELECT id, org_id FROM assistants")}
        for org_id in org_ids:
            own = {r[0] for r in conn.execute("SELECT id FROM chunks WHERE org_id = ?", (org_id,))}
            index = retrieval.get_index(org_id)
            assert set(index.chunk_ids) == own


def test_admin_cannot_access_other_org_documents(client, two_orgs):
    b_docs = client.get("/api/documents", headers=two_orgs["b"]["headers"]).json()["documents"]
    some_b_doc = b_docs[0]["id"]
    # Org A's admin tries to read / delete Org B's document by id
    assert client.get(f"/api/documents/{some_b_doc}/rules", headers=two_orgs["a"]["headers"]).status_code == 404
    assert client.delete(f"/api/documents/{some_b_doc}", headers=two_orgs["a"]["headers"]).status_code == 404
    # still there for Org B
    assert any(d["id"] == some_b_doc for d in client.get("/api/documents", headers=two_orgs["b"]["headers"]).json()["documents"])
    # and Org A's listing never includes it
    assert all(d["id"] != some_b_doc for d in client.get("/api/documents", headers=two_orgs["a"]["headers"]).json()["documents"])


def test_assistant_token_cannot_access_admin_apis(client, two_orgs):
    token = two_orgs["a"]["token"]
    for method, path in [("get", "/api/documents"), ("get", "/api/assistant"), ("post", "/api/assistant/regenerate"),
                         ("get", "/api/usage"), ("get", "/api/auth/me")]:
        for headers in ({"Authorization": f"Bearer {token}"}, {"X-Assistant-Token": token}):
            r = getattr(client, method)(path, headers=headers)
            assert r.status_code == 401, (path, r.status_code)


def test_admin_apis_require_login(client):
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/documents", files=[("files", ("x.pdf", b"%PDF-1.4", "application/pdf"))]).status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer sess_forged"}).status_code == 401


def test_invalid_assistant_token_is_rejected(client):
    r = ask(client, "ast_not_a_real_token", "What is the hostel fee?")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert client.get("/a/ast_not_a_real_token").status_code == 404


def test_uploaded_pdfs_are_not_publicly_served(client, two_orgs):
    with get_conn() as conn:
        stored = conn.execute("SELECT stored_path FROM documents LIMIT 1").fetchone()[0]
    rel = stored.replace(str(settings.DATA_DIR), "").lstrip("/")
    for url in (f"/static/{rel}", f"/{rel}", f"/data/{rel}", "/static/../data/app.db"):
        assert client.get(url).status_code == 404


def test_token_does_not_leak_org_data(two_orgs):
    for org in two_orgs.values():
        tok = org["token"]
        assert tok.startswith("ast_") and len(tok) >= 30
        assert "greenfield" not in tok.lower() and "nimbus" not in tok.lower()


def test_regenerating_token_invalidates_old_link(client):
    from conftest import register, upload, SAMPLES
    h = register(client, "Rotation Org", "rotate@test.example")
    upload(client, h, [SAMPLES / "nimbus_technologies" / "Leave_Policy.pdf"])
    old = client.get("/api/assistant", headers=h).json()["token"]
    new = client.post("/api/assistant/regenerate", headers=h).json()["token"]
    assert old != new
    assert ask(client, old, "How do I apply for leave?").status_code == 401
    assert ask(client, new, "How do I apply for leave?").status_code == 200
