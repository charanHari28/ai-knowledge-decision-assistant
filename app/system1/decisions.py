"""System-1 decision models: fast, typed, deterministic, explainable.

  ChoiceModel     (Choice)   which policy/program does the question concern?
  BooleanModel    (Boolean)  does a stated fact satisfy one rule?  PASS / FAIL / UNKNOWN
  EligibilityScore(Score)    how strongly do the facts satisfy the policy? 0..1
  RelevanceScore  (Score)    does the knowledge base actually contain an answer? 0..1

Each returns a small typed result object (inputs, output, confidence, source), never prose.
"""
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.services.retrieval import Hit, tokenize


# ============================================================ Boolean
@dataclass
class BooleanResult:
    rule_id: int
    policy: str
    attribute: str
    label: str
    operator: str
    expected: Any
    actual: Any
    outcome: str  # PASS | FAIL | UNKNOWN
    source: Dict[str, Any]
    weight: float = 1.0

    def to_dict(self):
        return asdict(self)


OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class BooleanModel:
    """Evaluates ONE rule against the extracted facts."""

    @staticmethod
    def evaluate(rule: dict, facts: Dict[str, Any]) -> BooleanResult:
        actual = facts.get(rule["attribute"])
        outcome = "UNKNOWN"
        if actual is not None:
            try:
                if rule["operator"] in ("in", "not_in"):
                    options = [str(o).lower() for o in rule["value"]]
                    hit = str(actual).lower() in options
                    outcome = "PASS" if hit == (rule["operator"] == "in") else "FAIL"
                elif rule["value_type"] == "boolean":
                    outcome = "PASS" if bool(actual) == bool(rule["value"]) else "FAIL"
                else:
                    outcome = "PASS" if OPS[rule["operator"]](float(actual), float(rule["value"])) else "FAIL"
            except (KeyError, TypeError, ValueError):
                outcome = "UNKNOWN"
        return BooleanResult(
            rule_id=rule["id"], policy=rule["policy"], attribute=rule["attribute"], label=rule["label"],
            operator=rule["operator"], expected=rule["value"], actual=actual, outcome=outcome,
            source={"document": rule["filename"], "page": rule["page"], "text": rule["source_text"]},
            weight=rule.get("weight", 1.0),
        )


def evaluate_parallel(rules: List[dict], facts: Dict[str, Any], max_workers: int = 8) -> List[BooleanResult]:
    """Rules are independent of each other, so they are evaluated concurrently."""
    if not rules:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(rules))) as pool:
        return list(pool.map(lambda r: BooleanModel.evaluate(r, facts), rules))


# ============================================================ Choice
@dataclass
class ChoiceResult:
    selected: List[str]
    confidence: float
    scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class ChoiceModel:
    """Picks which policy (from the org's compiled rules) the question is about.

    Score per policy = 3.0 * share of the policy name's words present in the question
                     + 1.0 * policy's source page is among the top retrieved pages
                     + 0.5 * share of the policy's attributes the question mentions
    Softmax over scores gives the confidence. A second policy is also selected when the
    question names it explicitly (e.g. "merit or need-based aid?").
    """

    @staticmethod
    def choose(question: str, policies: Dict[str, List[dict]], hits: List[Hit]) -> ChoiceResult:
        if not policies:
            return ChoiceResult([], 0.0)
        q_tokens = set(tokenize(question))
        q_low = question.lower()
        hit_pages = {(h.document_id, h.page) for h in hits[:4]}
        raw: Dict[str, float] = {}
        name_match: Dict[str, float] = {}
        for name, rules in policies.items():
            name_tokens = set(tokenize(name)) - {"scholarship", "leave", "program", "policy"} or set(tokenize(name))
            nm = len(name_tokens & q_tokens) / max(len(name_tokens), 1)
            in_hits = any((r["document_id"], r["page"]) in hit_pages for r in rules)
            attrs = {r["attribute"]: r for r in rules}
            mentioned = sum(1 for r in attrs.values() if any(re.search(rf"\b{re.escape(a)}\b", q_low) for a in r["aliases"]))
            score = 3.0 * nm + 1.0 * in_hits + 0.5 * mentioned / max(len(attrs), 1)
            raw[name] = round(score, 3)
            name_match[name] = nm
        # Policies the person asks to be checked for ("eligible for the Merit ...") vs. ones they
        # merely mention ("I already have the Sports ... Scholarship").
        requested = [p for p in policies if name_match[p] >= 0.99 and _is_requested(q_low, p)]
        ranked = sorted(raw, key=raw.get, reverse=True)
        if requested:
            requested.sort(key=raw.get, reverse=True)
            exp = {k: math.exp(v) for k, v in raw.items()}
            return ChoiceResult(requested[:2], round(exp[requested[0]] / sum(exp.values()), 3), raw)
        exp = {k: math.exp(v) for k, v in raw.items()}
        total = sum(exp.values())
        best = ranked[0]
        if raw[best] < 1.0:  # neither named nor supported by retrieval
            return ChoiceResult([], round(exp[best] / total, 3), raw)
        selected = [best] + [p for p in ranked[1:3] if name_match[p] >= 0.99 and name_match[best] >= 0.99]
        return ChoiceResult(selected, round(exp[best] / total, 3), raw)


REQUEST_VERBS = r"(eligible|eligibility|qualify|apply|applying|get|avail|receive|take|claim|for)"


def _is_requested(q_low: str, policy: str) -> bool:
    words = [w for w in re.findall(r"[a-z]+", policy.lower()) if w not in {"the", "of", "for", "and"}]
    if not words:
        return False
    return bool(re.search(rf"\b{REQUEST_VERBS}\W+(?:[\w-]+\W+){{0,3}}?{re.escape(words[0])}", q_low))


# ============================================================ Score: eligibility
@dataclass
class EligibilityScoreResult:
    score: float          # weighted share of rules passed (0..1)
    coverage: float       # share of rules for which a fact was available
    passed: int
    failed: int
    unknown: int

    def to_dict(self):
        return asdict(self)


class EligibilityScore:
    @staticmethod
    def score(results: List[BooleanResult]) -> EligibilityScoreResult:
        total_w = sum(r.weight for r in results) or 1.0
        passed = [r for r in results if r.outcome == "PASS"]
        failed = [r for r in results if r.outcome == "FAIL"]
        unknown = [r for r in results if r.outcome == "UNKNOWN"]
        return EligibilityScoreResult(
            score=round(sum(r.weight for r in passed) / total_w, 3),
            coverage=round((len(passed) + len(failed)) / max(len(results), 1), 3),
            passed=len(passed), failed=len(failed), unknown=len(unknown),
        )


# ============================================================ Score: relevance / answerability
@dataclass
class RelevanceResult:
    score: float
    answerable: bool
    features: Dict[str, float]

    def to_dict(self):
        return asdict(self)


class RelevanceScore:
    """Logistic model over retrieval features deciding if the KB can answer the question.
    Weights were calibrated on the sample question set (scripts/run_eval.py) so that
    out-of-scope questions fall below the threshold and in-scope ones clear it."""

    W = {"idf_coverage": 3.0, "top_cosine": 4.0, "bm25_norm": 6.0}
    BIAS = -4.0

    @classmethod
    def score(cls, features: Dict[str, float], threshold: float) -> RelevanceResult:
        z = cls.BIAS + sum(cls.W[k] * features.get(k, 0.0) for k in cls.W)
        p = 1 / (1 + math.exp(-z))
        return RelevanceResult(round(p, 3), p >= threshold, {k: round(v, 3) for k, v in features.items()})


# ============================================================ Application logic: combine
VERDICTS = {
    "ELIGIBLE": "All conditions are met.",
    "NOT_ELIGIBLE": "At least one condition is not met.",
    "NEEDS_INFO": "No condition failed, but some could not be checked from the information given.",
}


def combine(policy: str, results: List[BooleanResult]) -> Dict[str, Any]:
    """Deterministic combination: any FAIL -> NOT_ELIGIBLE; else any UNKNOWN -> NEEDS_INFO; else ELIGIBLE."""
    score = EligibilityScore.score(results)
    if any(r.outcome == "FAIL" for r in results):
        verdict = "NOT_ELIGIBLE"
    elif any(r.outcome == "UNKNOWN" for r in results):
        verdict = "NEEDS_INFO"
    else:
        verdict = "ELIGIBLE"
    return {
        "policy": policy,
        "verdict": verdict,
        "verdict_meaning": VERDICTS[verdict],
        "score": score.to_dict(),
        "conditions": [r.to_dict() for r in results],
        "failed": [r.label for r in results if r.outcome == "FAIL"],
        "missing": [r.label for r in results if r.outcome == "UNKNOWN"],
    }
