"""Question understanding: extract the asker's personal facts into a typed schema.

This is a natural-language-understanding job, so the LLM does it when available. It is
*schema-guided*: the LLM is handed exactly the attributes the selected policy's rules need
(e.g. gpa:number, year_of_study:number, has_other_institutional_scholarship:boolean) and must
return a value or null for each. It never decides eligibility — that's System 1's job.

A deterministic extractor is used when no LLM is configured or the LLM call fails.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.services import llm
from app.services.rules import find_attribute_near, parse_number

log = logging.getLogger("facts")

# Extra words people use in questions (not in policy text) for canonical attributes.
FACT_HINTS = {
    "tenure_months": ["months", "joined", "with the company", "worked here", "working here", "years"],
    "year_of_study": ["year"],
    "days_requested": ["days", "weeks"],
    "performance_rating": ["rating", "rated"],
    "attendance_pct": ["attendance", "%"],
    "family_income": ["lakh", "income", "earn", "salary"],
    "distance_km": ["km", "away"],
    "gpa": ["gpa", "cgpa", "pointer"],
    "age": ["years old", "age"],
    "duration_weeks": ["week", "weeks"],
}

NEGATION = re.compile(r"\b(not|no|never|without|don'?t|do not|haven'?t|have not|isn'?t|am not|i'?m not|yet to|none|neither|nor|still on|still in|pending)\b", re.I)
POSSESSION = re.compile(r"\b(have|has|hold|holding|got|get|receive|receiving|received|on|under|placed|already|currently|am|i'?m|availing|awarded|been given|completed|done|cleared|finished|represented|played)\b", re.I)


def extract_facts(question: str, rules: List[dict], policy_names: List[str]) -> Dict[str, Any]:
    """Returns {"facts": {attribute: value|None}, "extractor": "llm"|"pattern"}."""
    schema = _schema(rules)
    if not schema:
        return {"facts": {}, "extractor": "none"}
    if llm.is_enabled():
        try:
            return {"facts": _extract_llm(question, schema), "extractor": "llm"}
        except llm.LLMError as exc:
            log.warning("LLM fact extraction failed, using pattern extractor: %s", exc)
    return {"facts": extract_facts_pattern(question, schema, policy_names), "extractor": "pattern"}


def _schema(rules: List[dict]) -> List[dict]:
    seen, schema = set(), []
    for r in rules:
        if r["attribute"] in seen:
            continue
        seen.add(r["attribute"])
        schema.append({
            "key": r["attribute"],
            "label": r["label"],
            "type": r["value_type"],
            "options": r["value"] if r["value_type"] == "choice" else None,
            "aliases": list(r.get("aliases", [])),
        })
    return schema


# ------------------------------------------------------------------ LLM extractor
FACTS_SYSTEM = """You extract facts that a person states about THEMSELVES in a question.
You are given a list of attributes. For each attribute return the value the person explicitly stated, or null if they did not state it.
- number: return a plain number (convert '8 lakh' to 800000, '2 years' of service to 24 when the key is in months, 'third year' to 3).
- boolean: true/false only if the person clearly said so (e.g. 'I already have the sports scholarship' -> has_other_institutional_scholarship: true; 'I have no other scholarship' -> false).
- choice: return one of the given options exactly, or null.
Never guess or infer missing values. Return ONLY JSON: {"facts": {"<key>": <value|null>, ...}}"""


def _extract_llm(question: str, schema: List[dict]) -> Dict[str, Any]:
    lines = []
    for a in schema:
        extra = f" options={a['options']}" if a["options"] else ""
        lines.append(f"- {a['key']} ({a['type']}): {a['label']}{extra}")
    data = llm.complete_json(FACTS_SYSTEM, f"Attributes:\n" + "\n".join(lines) + f"\n\nQuestion: {question}")
    raw = data.get("facts", {}) if isinstance(data, dict) else {}
    facts = {}
    for a in schema:
        facts[a["key"]] = _coerce(raw.get(a["key"]), a)
    return facts


def _coerce(value, attr) -> Any:
    if value is None or value == "":
        return None
    if attr["type"] == "number":
        if isinstance(value, (int, float)):
            return float(value)
        return parse_number(str(value))
    if attr["type"] == "boolean":
        if isinstance(value, bool):
            return value
        return {"true": True, "yes": True, "false": False, "no": False}.get(str(value).lower())
    if attr["type"] == "choice":
        for opt in attr["options"] or []:
            if str(value).lower() == str(opt).lower():
                return opt
        return None
    return value


# ------------------------------------------------------------------ pattern extractor
def extract_facts_pattern(question: str, schema: List[dict], policy_names: List[str]) -> Dict[str, Any]:
    q = question
    # Remove the names of the policies being asked about so "eligible for the Merit Scholarship"
    # is not mistaken for "already holds a scholarship".
    for name in sorted(policy_names, key=len, reverse=True):
        q = re.sub(re.escape(name), " ", q, flags=re.I)
    low = q.lower()
    facts: Dict[str, Any] = {a["key"]: None for a in schema}

    numeric = [a for a in schema if a["type"] == "number"]
    if numeric:
        facts.update(_numbers(low, numeric))
    for a in schema:
        if a["type"] == "boolean":
            facts[a["key"]] = _boolean(low, a)
        elif a["type"] == "choice":
            facts[a["key"]] = _choice(low, a)
    return facts


def _numbers(low: str, attrs: List[dict]) -> Dict[str, Optional[float]]:
    found: Dict[str, Optional[float]] = {}
    keys = {a["key"] for a in attrs}

    # Special forms first.
    if "year_of_study" in keys:
        m = re.search(r"\b(\d)(?:st|nd|rd|th)?[- ]year\b|\byear\s*(\d)\b|\b(first|second|third|fourth|final)[- ]year\b", low)
        if m:
            found["year_of_study"] = parse_number(next(g for g in m.groups() if g))
            low = low[: m.start()] + " " * (m.end() - m.start()) + low[m.end():]
    if "tenure_months" in keys:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(months?|years?|yrs?)\b(?![^.,;]*\b(?:old|age)\b)", low)
        ctx = re.search(r"(with the company|joined|service|working|worked|tenure|employed|been here|at nimbus|in the company)", low)
        if m and ctx:
            value = float(m.group(1)) * (12 if m.group(2).startswith(("y")) else 1)
            found["tenure_months"] = value
            low = low[: m.start()] + " " * (m.end() - m.start()) + low[m.end():]

    lexicon = [
        {"key": a["key"], "aliases": sorted(set(a["aliases"]) | set(FACT_HINTS.get(a["key"], [])), key=len, reverse=True)}
        for a in attrs if a["key"] not in found
    ]
    for m in re.finditer(r"(₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?\s*(%|lakhs?|lac|crore|k\b)?", low):
        if not lexicon:
            break
        attr = find_attribute_near(low, m.start(), m.end(), lexicon)
        if attr and attr["key"] not in found:
            found[attr["key"]] = parse_number(m.group(0))
    return found


def _clause_before(low: str, idx: int, width: int = 40) -> str:
    window = low[max(0, idx - width): idx]
    parts = re.split(r"[,.;!?]|\band\b|\bbut\b", window)
    return parts[-1] if parts else window


def _boolean(low: str, attr: dict) -> Optional[bool]:
    key = attr["key"]
    if "full_time" in key:
        if re.search(r"\bpart[- ]time\b", low):
            return False
    for alias in sorted(attr["aliases"], key=len, reverse=True):
        m = re.search(rf"\b{re.escape(alias)}\b", low)
        if not m:
            continue
        before = _clause_before(low, m.start())
        after = low[m.end(): m.end() + 12]
        negated = bool(NEGATION.search(before)) or bool(re.match(r"\s*(?:is\s+)?(?:not|pending)\b", after))
        if key.startswith("has_"):
            if negated:
                return False
            if POSSESSION.search(before):
                return True
            continue  # mentioned without saying they have it — unknown
        # is_* : the phrase itself states the condition ("completed probation", "full-time student")
        if "probation" in key and re.search(r"\b(still on|on probation|under probation|in probation|not completed|yet to complete)\b", low):
            return False
        return not negated
    return None


def _choice(low: str, attr: dict) -> Optional[str]:
    for opt in attr.get("options") or []:
        if re.search(rf"\b{re.escape(str(opt).lower())}\b", low):
            return opt
    # singular/plural tolerance: "online courses", "a certification"
    for opt in attr.get("options") or []:
        head = str(opt).lower().split()[-1].rstrip("s")
        first = str(opt).lower().split()[0]
        if re.search(rf"\b{re.escape(first)}\b", low) and re.search(rf"\b{re.escape(head)}", low):
            return opt
    return None
