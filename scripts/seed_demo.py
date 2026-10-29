"""Seeds the two demo organizations into a RUNNING server via its public API.

    uvicorn app.main:app --port 8000          # terminal 1
    python scripts/seed_demo.py               # terminal 2  (optional: --base http://localhost:8000)

Safe to run twice: existing accounts are logged into and already-uploaded files are skipped.
Prints each organization's login, assistant URL and a ready-made demo-site URL.
"""
import argparse
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--demo-site", default="http://localhost:5500")
    args = ap.parse_args()
    spec = json.loads((ROOT / "sample_data" / "test_questions.json").read_text())

    with httpx.Client(base_url=args.base, timeout=180) as c:
        for org in spec["organizations"]:
            r = c.post("/api/auth/register", json={"org_name": org["name"], "email": org["email"], "password": org["password"]})
            if r.status_code == 409:
                r = c.post("/api/auth/login", json={"email": org["email"], "password": org["password"]})
            r.raise_for_status()
            h = {"Authorization": f"Bearer {r.json()['token']}"}

            existing = {d["filename"] for d in c.get("/api/documents", headers=h).json()["documents"]}
            pdfs = [p for p in sorted((ROOT / "sample_data" / org["folder"]).glob("*.pdf")) if p.name not in existing]
            if pdfs:
                files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]
                for res in c.post("/api/documents", files=files, headers=h).json().get("results", []):
                    print(f"  {'+' if res['ok'] else '!'} {res.get('filename')}: " +
                          (f"{res['pages']} pages, {res['chunks']} passages, {res['rules']} rules ({res['rule_compiler']})" if res["ok"] else res["error"]))
            a = c.get("/api/assistant", headers=h).json()
            print(f"\n{org['name']}\n  login:      {org['email']} / {org['password']}\n  assistant:  {a['url']}\n"
                  f"  demo site:  {args.demo_site}/index.html?token={a['token']}&host={args.base}\n")


if __name__ == "__main__":
    main()
