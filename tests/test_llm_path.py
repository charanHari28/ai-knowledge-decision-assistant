"""Tests the LLM-enabled path with a fake LLM (no network), including failure fallbacks."""
import json

import pytest

from app.services import llm
from conftest import ask


@pytest.fixture
def fake_llm():
    calls = []

    def install(fn):
        def wrapper(system, user, json_mode):
            calls.append({"system": system, "user": user, "json": json_mode})
            return fn(system, user, json_mode)
        llm.set_override(wrapper)
        return calls

    yield install
    llm.set_override(None)


def test_llm_extracts_facts_and_writes_answer_but_system1_decides(client, two_orgs, fake_llm):
    def fn(system, user, json_mode):
        if "extract facts" in system:
            # LLM returns facts only; it is never asked for the verdict
            return json.dumps({"facts": {"year_of_study": 3, "gpa": 8.7, "attendance_pct": 80, "has_other_institutional_scholarship": True}})
        assert "DECISION:" in user and '"verdict": "NOT_ELIGIBLE"' in user  # verdict passed in as data
        return "You are not eligible for the Merit Scholarship because you already hold another institutional scholarship [1]."

    calls = fake_llm(fn)
    r = ask(client, two_orgs["a"]["token"], "3rd year, GPA 8.7, 80% attendance, I hold the Sports Excellence Scholarship. "
                                            "Am I eligible for the Merit Scholarship?").json()
    assert r["decisions"][0]["verdict"] == "NOT_ELIGIBLE"
    assert r["answer"].startswith("You are not eligible")
    assert r["references"] and r["references"][0]["document"] == "Scholarship_Rules.pdf"
    steps = {s["step"]: s for s in r["pipeline"]}
    assert steps["extract_facts"]["output"]["extractor"] == "llm"
    assert steps["generate_answer"]["component"] == "LLM"
    # the LLM never saw another tenant's documents
    assert all("Nimbus" not in c["user"] and "HRMS" not in c["user"] for c in calls)


def test_llm_says_not_in_kb(client, two_orgs, fake_llm):
    fake_llm(lambda s, u, j: "NOT_IN_KB")
    r = ask(client, two_orgs["a"]["token"], "What are the hostel mess timings for dinner?").json()
    assert r["outcome"] == "not_found"


def test_llm_failure_falls_back_to_extractive_answer(client, two_orgs, fake_llm):
    def boom(*_):
        raise llm.LLMError("LLM rate limit reached.")
    fake_llm(boom)
    r = ask(client, two_orgs["b"]["token"], "How many days of annual leave do employees get?").json()
    assert r["degraded"] is True and r["notices"]
    assert "24" in r["answer"]


def test_llm_failure_during_fact_extraction_uses_pattern_extractor(client, two_orgs, fake_llm):
    def fn(system, user, json_mode):
        if "extract facts" in system:
            raise llm.LLMError("timeout")
        return "Eligible [1]."
    fake_llm(fn)
    r = ask(client, two_orgs["b"]["token"], "I have 14 months of service, completed probation, rating 4. "
                                            "Can I work remotely abroad for 20 days?").json()
    assert r["decisions"][0]["verdict"] == "ELIGIBLE"
    assert {s["step"]: s for s in r["pipeline"]}["extract_facts"]["output"]["extractor"] == "pattern"


def test_decision_model_failure_is_handled(client, two_orgs, monkeypatch):
    from app.services import pipeline

    def broken(*a, **k):
        raise RuntimeError("decision engine down")
    monkeypatch.setattr(pipeline, "evaluate_parallel", broken)
    r = ask(client, two_orgs["a"]["token"], "I'm in 2nd year with GPA 9.1. Am I eligible for the Merit Scholarship?")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "needs_review" and body["notices"]


def test_loose_policy_match_without_facts_shows_no_checklist(client, two_orgs):
    r = ask(client, two_orgs["b"]["token"], "can i take work from home").json()
    assert r["decisions"] == []
    assert r["outcome"] == "answered"
    assert any(x["document"] == "Work_From_Home_Policy.pdf" for x in r["references"])


def test_named_policy_without_facts_asks_for_details(client, two_orgs):
    r = ask(client, two_orgs["b"]["token"], "Am I eligible for sabbatical leave?").json()
    assert r["decisions"] and r["decisions"][0]["verdict"] == "NEEDS_INFO"
