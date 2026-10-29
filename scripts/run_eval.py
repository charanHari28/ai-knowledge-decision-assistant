"""Runs the sample question set end-to-end against a fresh, isolated database.

    python scripts/run_eval.py            # uses LLM settings from .env (or offline)
    python scripts/run_eval.py --offline  # force the no-LLM fallback path
    python scripts/run_eval.py --verbose  # also print answers and pipeline traces

Creates the two demo organizations, uploads their PDFs through the real API, asks every
question in sample_data/test_questions.json through POST /api/ask and checks the outcome,
the decision verdict, expected text and the cited document.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="kda_eval_")
    if args.offline:
        os.environ["LLM_PROVIDER"] = "offline"

    from fastapi.testclient import TestClient
    from app.main import app

    spec = json.loads((ROOT / "sample_data" / "test_questions.json").read_text())
    passed = 0
    with TestClient(app) as client:
        tokens = {}
        for org in spec["organizations"]:
            r = client.post("/api/auth/register", json={"org_name": org["name"], "email": org["email"], "password": org["password"]})
            headers = {"Authorization": f"Bearer {r.json()['token']}"}
            pdfs = sorted((ROOT / "sample_data" / org["folder"]).glob("*.pdf"))
            files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]
            res = client.post("/api/documents", files=files, headers=headers).json()["results"]
            print(f"[{org['name']}] uploaded: " + ", ".join(f"{x['filename']} ({x.get('pages')}p, {x.get('rules')} rules)" for x in res))
            tokens[org["folder"]] = client.get("/api/assistant", headers=headers).json()["token"]
        print(f"LLM: {client.get('/health').json()['llm']}\n")

        print(f"{'ID':4} {'RESULT':6} {'TYPE':12} {'OUTCOME':11} {'VERDICT':14} QUESTION")
        for q in spec["questions"]:
            r = client.post("/api/ask", json={"token": tokens[q["org"]], "question": q["question"]}).json()
            exp = q["expect"]
            problems = []
            if r.get("outcome") != exp["outcome"]:
                problems.append(f"outcome {r.get('outcome')} != {exp['outcome']}")
            verdicts = [d["verdict"] for d in r.get("decisions", [])]
            if "verdict" in exp and exp["verdict"] not in verdicts:
                problems.append(f"verdict {verdicts} != {exp['verdict']}")
            if "contains_any" in exp and not any(s.lower() in r.get("answer", "").lower() for s in exp["contains_any"]):
                problems.append(f"answer lacks {exp['contains_any']}")
            if "reference" in exp and exp["reference"] not in [x["document"] for x in r.get("references", [])]:
                problems.append(f"no reference to {exp['reference']}")
            ok = not problems
            passed += ok
            print(f"{q['id']:4} {'PASS' if ok else 'FAIL':6} {str(r.get('question_type')):12} {str(r.get('outcome')):11} {(','.join(verdicts) or '-'):14} {q['question'][:70]}")
            for p in problems:
                print(f"{'':12}- {p}")
            if args.verbose or not ok:
                print("      " + r.get("answer", json.dumps(r)).replace("\n", "\n      ")[:900])
                print("      refs:", [(x["document"], x["page"]) for x in r.get("references", [])])
                if args.verbose:
                    for s in r.get("pipeline", []):
                        print(f"        · {s['step']:18} {s['component']:45} {s['ms']:>7}ms")
                print()
    total = len(spec["questions"])
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
