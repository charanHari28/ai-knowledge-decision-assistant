"""The question-processing pipeline (application logic / orchestration).

  1. Tenant         token -> org (done by the API layer before we get here)
  2. Classify  ┐    System 1  question type (classification)          ┐ run in parallel
     Retrieve  ┘    Hybrid BM25 + TF-IDF over THIS org's chunks only   ┘
  3. Relevance      System 1  score: can the KB answer this at all?  -> if not, refuse (no LLM call)
  4. Choice         System 1  which policy is the question about?
  5. Understand     LLM       extract the asker's facts into the policy's typed schema
  6. Decide         System 1  one Boolean model per rule, evaluated in parallel
  7. Combine        App logic ELIGIBLE / NOT_ELIGIBLE / NEEDS_INFO + Score model
  8. Generate       LLM       grounded answer with citations (decision passed in as data)
  9. References     App logic map citations back to document + page
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import settings
from app.db import get_conn
from app.services import answer as writer
from app.services import llm, retrieval
from app.services.facts import extract_facts
from app.system1.classifier import get_classifier
from app.system1.decisions import ChoiceModel, RelevanceScore, combine, evaluate_parallel

log = logging.getLogger("pipeline")

GREETING_REPLY = ("Hi! I'm {assistant}. Ask me anything covered by {org}'s documents — for example policies, "
                  "procedures, or whether you're eligible for something (tell me your details and I'll check each rule).")
PERSONAL_FACTS = re.compile(r"\b(i|i'm|im|my|me|i've|i am)\b.*\d|\d.*\b(i|i'm|my|me)\b", re.I)


class PipelineError(Exception):
    def __init__(self, message: str, code: str, status_code: int = 400):
        super().__init__(message)
        self.message, self.code, self.status_code = message, code, status_code


@dataclass
class Trace:
    steps: List[Dict[str, Any]] = field(default_factory=list)
    _t: float = field(default_factory=time.perf_counter)

    def add(self, step: str, component: str, started: float, **output):
        self.steps.append({"step": step, "component": component,
                           "ms": round((time.perf_counter() - started) * 1000, 1), "output": output})


def load_rules(org_id: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT r.*, d.filename FROM rules r JOIN documents d ON d.id = r.document_id
               WHERE r.org_id = ? AND d.org_id = ? AND d.status = 'ready'""",
            (org_id, org_id),
        ).fetchall()
    rules = []
    for row in rows:
        r = dict(row)
        r["value"] = json.loads(r["value"])
        r["aliases"] = json.loads(r["aliases"])
        rules.append(r)
    return rules


def ask(org_id: int, org_name: str, assistant_name: str, question: str) -> Dict[str, Any]:
    started = time.perf_counter()
    question = (question or "").strip()
    if not question:
        raise PipelineError("Please type a question.", "empty_question")
    if len(question) > settings.MAX_QUESTION_CHARS:
        raise PipelineError(f"Questions can be at most {settings.MAX_QUESTION_CHARS} characters.", "question_too_long")

    trace = Trace()
    result: Dict[str, Any] = {"answer": "", "references": [], "outcome": "answered", "question_type": None,
                              "decisions": [], "degraded": False, "notices": []}

    # ---- 2. classification || retrieval (independent -> parallel) ----
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_cls = pool.submit(get_classifier().predict, question)
        f_ret = pool.submit(retrieval.search, org_id, question, settings.TOP_K + 3)
        cls, hits = f_cls.result(), f_ret.result()
    qtype = cls.label
    result["question_type"] = qtype
    trace.add("classify_question", "System 1 · Classification", t, label=qtype, confidence=round(cls.confidence, 3),
              probabilities=cls.probabilities)
    trace.add("retrieve", "Retrieval · hybrid BM25 + TF-IDF", t,
              hits=[{"document": h.filename, "page": h.page, "score": round(h.score, 4)} for h in hits[:settings.TOP_K]])

    if qtype == "greeting" and cls.confidence >= 0.6 and len(question.split()) <= 8:
        result["answer"] = GREETING_REPLY.format(assistant=assistant_name, org=org_name)
        return _finish(org_id, question, result, trace, started)

    # ---- 3. relevance / answerability (Score) ----
    t = time.perf_counter()
    features = {
        "idf_coverage": retrieval.idf_weighted_coverage(org_id, question, hits),
        "top_cosine": max((h.cosine for h in hits), default=0.0),
        "bm25_norm": (lambda b: b / (b + 6.0))(max((h.bm25 for h in hits), default=0.0)),
    }
    relevance = RelevanceScore.score(features, settings.RELEVANCE_THRESHOLD)
    trace.add("score_relevance", "System 1 · Score", t, **relevance.to_dict())

    # ---- 4-7. structured decision path ----
    rules = load_rules(org_id)
    policies: Dict[str, List[dict]] = {}
    for r in rules:
        policies.setdefault(r["policy"], []).append(r)

    decision_payload: Optional[dict] = None
    comparison_rules: Optional[dict] = None
    wants_decision = qtype == "eligibility" or (qtype in ("policy", "factual") and PERSONAL_FACTS.search(question))

    if policies and (wants_decision or qtype == "comparison"):
        t = time.perf_counter()
        choice = ChoiceModel.choose(question, policies, hits)
        trace.add("choose_policy", "System 1 · Choice", t, **choice.to_dict())

        if choice.selected and wants_decision:
            try:
                decision_payload = _decide(question, choice.selected, policies, choice.selected, trace)
                # A checklist where nothing could be checked is only useful if the person named the
                # policy ("Am I eligible for sabbatical leave?"). For a loose match (e.g. "work from
                # home" -> Remote Work Abroad) drop it and answer from the documents instead.
                kept = [d for d in decision_payload["policies"]
                        if d["score"]["coverage"] > 0 or _names_policy(question, d["policy"])]
                if len(kept) < len(decision_payload["policies"]):
                    trace.add("skip_decision", "App logic", time.perf_counter(),
                              reason="no stated facts and policy not named in the question",
                              dropped=[d["policy"] for d in decision_payload["policies"] if d not in kept])
                decision_payload = {**decision_payload, "policies": kept} if kept else None
                result["decisions"] = kept
            except Exception as exc:  # decision-model failure must not take the whole answer down
                log.exception("decision stage failed")
                result["notices"].append("The eligibility checker failed for this question; the answer below is based on the documents only and should be reviewed.")
                result["outcome"] = "needs_review"
                trace.add("decision_error", "System 1", time.perf_counter(), error=type(exc).__name__)
        elif choice.selected and qtype == "comparison":
            comparison_rules = {p: [{k: r[k] for k in ("label", "operator", "value", "page", "filename")} for r in policies[p]]
                                for p in choice.selected}
            # make sure the pages holding the compared rules are available as citable context
            rule_docs_cmp = {(r["filename"], r["page"]) for p in choice.selected for r in policies[p]}

    # Not answerable and no decision could be made -> refuse without calling the LLM.
    if not hits or (not relevance.answerable and not decision_payload):
        result["answer"] = writer.not_found_answer(org_name)
        result["outcome"] = "not_found"
        return _finish(org_id, question, result, trace, started)

    # ---- 8. answer generation ----
    context_hits = hits[: settings.TOP_K]
    rule_docs = list(rule_docs_cmp) if comparison_rules else []
    if decision_payload:
        for d in decision_payload["policies"]:
            for c in d["conditions"]:
                rule_docs.append((c["source"]["document"], c["source"]["page"]))
    if rule_docs:  # make sure the pages the rules came from are in the context for citation
        have = {(h.filename, h.page) for h in context_hits}
        for h in hits:
            if (h.filename, h.page) in set(rule_docs) - have:
                context_hits.append(h)
                have.add((h.filename, h.page))
        if set(rule_docs) - have:
            context_hits += _page_chunks(org_id, set(rule_docs) - have)

    t = time.perf_counter()
    text, used = None, []
    if llm.is_enabled():
        try:
            text = writer.generate_llm(org_name, question, qtype, context_hits, decision_payload, comparison_rules)
            if writer.NOT_IN_KB in text and not decision_payload:
                result["answer"] = writer.not_found_answer(org_name)
                result["outcome"] = "not_found"
                trace.add("generate_answer", "LLM", t, provider=llm.provider_label(), result="NOT_IN_KB")
                return _finish(org_id, question, result, trace, started)
            used = writer.cited_indices(text, len(context_hits))
            trace.add("generate_answer", "LLM", t, provider=llm.provider_label(), citations=used)
        except llm.LLMError as exc:
            result["degraded"] = True
            result["notices"].append("The AI writer is temporarily unavailable, so this answer was assembled directly from the documents.")
            trace.add("generate_answer", "LLM", t, provider=llm.provider_label(), error=str(exc))
            text = None

    if text is None:
        t2 = time.perf_counter()
        rule_ref = {}
        for i, h in enumerate(context_hits, start=1):
            rule_ref.setdefault((h.filename, h.page), i)
        if decision_payload:
            text = writer.decision_answer(decision_payload["policies"], rule_ref)
            used = sorted({rule_ref[k] for k in rule_docs if k in rule_ref})
        else:
            text, used = writer.extractive_answer(question, qtype, context_hits)
            if comparison_rules:
                table, cited = writer.comparison_answer(comparison_rules, rule_ref)
                text = table + ("\n\n" + text if text else "")
                used = list(dict.fromkeys(cited + used))
        trace.add("compose_answer", "App logic (extractive fallback)", t2, citations=used)

    if not text:
        result["answer"] = writer.not_found_answer(org_name)
        result["outcome"] = "not_found"
        return _finish(org_id, question, result, trace, started)

    # ---- 9. references ----
    if not used:
        used = list(range(1, min(2, len(context_hits)) + 1))
    text, result["references"] = _merge_references(text, used, context_hits)
    result["answer"] = text
    if result["outcome"] == "answered" and decision_payload and any(d["verdict"] == "NEEDS_INFO" for d in decision_payload["policies"]):
        result["outcome"] = "needs_info"
    return _finish(org_id, question, result, trace, started)


def _decide(question: str, selected: List[str], policies: Dict[str, List[dict]], all_policy_names: List[str], trace: Trace) -> dict:
    rules = [r for p in selected for r in policies[p]]

    t = time.perf_counter()
    extracted = extract_facts(question, rules, all_policy_names)
    facts = extracted["facts"]
    trace.add("extract_facts", "LLM · understanding" if extracted["extractor"] == "llm" else "Pattern extractor (LLM fallback)",
              t, facts=facts, extractor=extracted["extractor"])

    t = time.perf_counter()
    # Each (policy, rule) pair is an independent Boolean decision -> evaluate all in parallel.
    results = evaluate_parallel(rules, facts)
    trace.add("evaluate_rules", "System 1 · Boolean ×%d (parallel)" % len(results), t,
              results=[{"policy": r.policy, "condition": r.label, "outcome": r.outcome} for r in results])

    t = time.perf_counter()
    combined = [combine(p, [r for r in results if r.policy == p]) for p in selected]
    trace.add("combine", "App logic + System 1 · Score", t,
              verdicts={c["policy"]: {"verdict": c["verdict"], "score": c["score"]["score"]} for c in combined})
    return {"facts": facts, "policies": combined}


def _merge_references(text: str, used: List[int], hits: List[retrieval.Hit]):
    """One reference per (document, page): passages from the same page share a number, and the
    answer's [n] markers are renumbered 1..k in order of first use."""
    page_num: Dict[tuple, int] = {}
    old_to_new: Dict[int, int] = {}
    refs: List[Dict[str, Any]] = []
    for i in used:
        h = hits[i - 1]
        key = (h.filename, h.page)
        if key not in page_num:
            page_num[key] = len(refs) + 1
            refs.append({"n": page_num[key], "document": h.filename, "page": h.page,
                         "snippet": h.text[:240] + ("…" if len(h.text) > 240 else "")})
        old_to_new[i] = page_num[key]
    text = re.sub(r"\[(\d{1,2})\]", lambda m: f"[{old_to_new.get(int(m.group(1)), m.group(1))}]", text)
    text = re.sub(r"(\[\d{1,2}\])(\1)+", r"\1", text)  # "[1][1]" -> "[1]"
    return text, refs


def _names_policy(question: str, policy: str) -> bool:
    """True when every distinctive word of the policy's name appears in the question."""
    generic = {"policy", "program", "programme", "scheme"}
    name = set(retrieval.tokenize(policy)) - generic
    return bool(name) and name <= set(retrieval.tokenize(question))


def _page_chunks(org_id: int, pages) -> List[retrieval.Hit]:
    out = []
    with get_conn() as conn:
        for filename, page in pages:
            row = conn.execute(
                """SELECT c.id, c.document_id, c.page, c.text, d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                   WHERE c.org_id=? AND d.org_id=? AND d.filename=? AND c.page=? ORDER BY c.ordinal LIMIT 1""",
                (org_id, org_id, filename, page),
            ).fetchone()
            if row:
                out.append(retrieval.Hit(row["id"], row["document_id"], row["filename"], row["page"], row["text"], 0, 0, 0))
    return out


def _finish(org_id: int, question: str, result: Dict[str, Any], trace: Trace, started: float) -> Dict[str, Any]:
    latency = int((time.perf_counter() - started) * 1000)
    verdict = ",".join(f"{d['policy']}:{d['verdict']}" for d in result["decisions"]) or None
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO questions (org_id, question, question_type, outcome, decision, latency_ms) VALUES (?,?,?,?,?,?)",
            (org_id, question[:1000], result["question_type"], result["outcome"], verdict, latency),
        )
    result["pipeline"] = trace.steps
    result["latency_ms"] = latency
    return result
