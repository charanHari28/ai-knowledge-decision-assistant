import os
import sys
import tempfile
from pathlib import Path

# Isolated database + offline LLM for every test run. Must be set before `app` is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kda_test_")
os.environ["LLM_PROVIDER"] = "offline"
os.environ["ASK_RATE_LIMIT_PER_MINUTE"] = "1000"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLES = ROOT / "sample_data"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def register(client, name, email, password="password123"):
    r = client.post("/api/auth/register", json={"org_name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def upload(client, headers, paths):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in paths]
    return client.post("/api/documents", files=files, headers=headers)


@pytest.fixture(scope="session")
def two_orgs(client):
    """Org A = Greenfield University, Org B = Nimbus Technologies, with their sample PDFs."""
    a = register(client, "Greenfield University", "a@test.example")
    b = register(client, "Nimbus Technologies", "b@test.example")
    assert upload(client, a, sorted((SAMPLES / "greenfield_university").glob("*.pdf"))).status_code == 201
    assert upload(client, b, sorted((SAMPLES / "nimbus_technologies").glob("*.pdf"))).status_code == 201
    return {
        "a": {"headers": a, "token": client.get("/api/assistant", headers=a).json()["token"]},
        "b": {"headers": b, "token": client.get("/api/assistant", headers=b).json()["token"]},
    }


def ask(client, token, question):
    return client.post("/api/ask", json={"token": token, "question": question})
