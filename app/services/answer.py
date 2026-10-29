"""Final answer generation (LLM), with a deterministic extractive fallback.

The LLM receives ONLY: the question, the tenant's retrieved chunks (numbered) and, when a
structured decision was made, the System-1 decision result as JSON. It is told the decision is
authoritative and must not be re-computed, and to reply NOT_IN_KB when the context is silent.
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services import llm
from app.services.retrieval import Hit, tokenize

NOT_IN_KB = "NOT_IN_KB"

ANSWER_SYSTEM = """You are the knowledge assistant for {org}. You answer visitors' questions using ONLY the numbered context passages from {org}'s documents.
Rules:
1. Use only facts stated in the context. Do not use outside knowledge. If the context does not contain the answer, reply with exactly: NOT_IN_KB
2. Cite every factual sentence with the passage number in square brackets, e.g. [1] or [2][3].
3. If a DECISION block is given, it was computed by a deterministic rules engine and is authoritative; never change or re-evaluate it. The visitor already sees a checklist of every condition, so do not repeat the full list. Instead: state the verdict in one sentence, explain the decisive conditions (the ones not met, or not provided) with citations, add any useful related detail from the context (e.g. award amount, how to apply), and if information is missing tell the visitor exactly what to provide.
4. For comparisons, use a short markdown table or bullet list.
5. For procedures, use numbered steps.
6. Be concise (under 180 words) and friendly. Start directly with the answer: no greeting.
7. Citations are ONLY passage numbers like [1]. Never write [DECISION], [Decision Block] or any other bracketed label, and do not mention 'context', 'passages' or 'decision block'."""


def build_context(hits: List[Hit]) -> str:
    return "\n\n".join(f"[{i}] ({h.filename}, page {h.page})\n{h.text}" for i, h in enumerate(hits, start=1))


def generate_llm(org_name: str, question: str, qtype: str, hits: List[Hit], decision: Optional[dict],
                 policy_facts: Optional[dict]) -> str:
    parts = [f"Question type: {qtype}", f"Question: {question}", "", "Context:", build_context(hits)]
    if decision:
        parts += ["", "DECISION:", json.dumps(decision, indent=1, default=str)]
    if policy_facts:
        parts += ["", "STRUCTURED POLICY RULES (for comparison):", json.dumps(policy_facts, indent=1, default=str)]
    text = llm.complete(ANSWER_SYSTEM.format(org=org_name), "\n".join(parts), max_tokens=900).strip()
    return clean_answer(text)


def clean_answer(text: str) -> str:
    """Remove non-numeric bracket labels the model sometimes invents ("[DECISION]") and leading greetings."""
    text = re.sub(r"\s*\[(?!\d{1,2}\])[A-Za-z][^\]\n]{0,30}\]", "", text)
    text = re.sub(r"^(hello|hi|hey)[!,.]?\s+", "", text, flags=re.I)
    return text.strip()


def cited_indices(answer: str, n: int) -> List[int]:
    seen = []
    for m in re.finditer(r"\[(\d{1,2})\]", answer):
        i = int(m.group(1))
        if 1 <= i <= n and i not in seen:
            seen.append(i)
    return seen


# ------------------------------------------------------------------ offline / fallback writer
def _units(text: str) -> List[str]:
    """Split a chunk into readable units: list items, headings and sentences.
    Wrapped lines (a line continuing in lowercase) are re-joined first."""
    lines: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if (lines and len(lines[-1].split()) <= 8 and not re.search(r"[.:;!?]$", lines[-1]) and len(line.split()) <= 8
                and re.match(r"^(\d|rs\.?|up to)", line, re.I) and not re.match(r"^\d+[.)]\s", line)):
            lines[-1] += ": " + line  # table row split into cells: "Sick leave" / "12 working days"
            continue
        if lines and not re.match(r"^(\d+[.)]|[-•*])\s", line) and (line[0].islower() or not re.search(r"[.:;!?)]$", lines[-1]) and len(lines[-1]) > 60):
            lines[-1] += " " + line
        else:
            lines.append(line)
    units: List[str] = []
    for line in lines:
        if re.match(r"^\d+[.)]\s", line):
            units.append(line)
        else:
            units += [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if p.strip()]
    return units


def _is_heading(unit: str) -> bool:
    if re.search(r": .*\d", unit):  # a merged table row ("Sick leave: 12 days") is content, not a heading
        return False
    return len(unit.split()) <= 8 and not re.search(r"[.!?]$", unit)


def extractive_answer(question: str, qtype: str, hits: List[Hit], max_units: int = 3) -> Tuple[str, List[int]]:
    """Deterministic fallback writer: quotes the most relevant lines from the top passages."""
    q = set(tokenize(question))
    scored = []
    for hi, h in enumerate(hits[:4], start=1):
        units = _units(h.text)
        for ui, u in enumerate(units):
            overlap = len(q & set(tokenize(u))) / (len(q) or 1)
            scored.append((overlap - 0.04 * (hi - 1) - (0.05 if _is_heading(u) else 0), hi, ui, u, units))
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return "", []
    scored.sort(key=lambda x: -x[0])
    _, hi, ui, unit, units = scored[0]

    if qtype == "procedural":
        # the best-matching heading/sentence followed by its numbered steps
        out = [] if _is_heading(unit) else [unit]
        if _is_heading(unit):
            out.append(f"**{unit.lstrip('0123456789. ')}**")
        for nxt in units[ui + 1: ui + 12]:
            if re.match(r"^\d+[.)]\s", nxt) and not _is_heading(nxt):
                out.append(nxt)
            elif len(out) > 1:
                break
        return "\n".join(out) + f" [{hi}]", [hi]

    picked = [(hi, ui, unit)]
    if ui + 1 < len(units) and not _is_heading(units[ui + 1]):  # the next sentence usually completes the thought
        picked.append((hi, ui + 1, units[ui + 1]))
    for _, h2, u2, text, _ in scored[1:]:
        if len(picked) >= max_units:
            break
        if (h2, u2) not in {(a, b) for a, b, _ in picked} and not _is_heading(text):
            picked.append((h2, u2, text))
    picked.sort()
    used = []
    lines = []
    for h, _, text in picked:
        lines.append(f"{text} [{h}]")
        if h not in used:
            used.append(h)
    return "\n".join(lines), used


def comparison_answer(policy_rules: Dict[str, List[dict]], rule_ref: Dict[Tuple[str, int], int]) -> Tuple[str, List[int]]:
    """Side-by-side table of the compiled eligibility conditions of the compared policies."""
    names = list(policy_rules)
    labels = []
    for p in names:
        for r in policy_rules[p]:
            if r["label"] not in labels:
                labels.append(r["label"])
    def cell(p, label):
        for r in policy_rules[p]:
            if r["label"] == label:
                v = r["value"]
                v = " / ".join(map(str, v)) if isinstance(v, list) else ("required" if v is True else "not allowed" if v is False else f"{r['operator']} {v:g}" if isinstance(v, (int, float)) else v)
                return v
        return "—"
    head = "| Condition | " + " | ".join(names) + " |\n|---|" + "---|" * len(names)
    rows = [f"| {l} | " + " | ".join(str(cell(p, l)) for p in names) + " |" for l in labels]
    used = sorted({rule_ref[(r["filename"], r["page"])] for p in names for r in policy_rules[p] if (r["filename"], r["page"]) in rule_ref})
    cites = "".join(f"[{i}]" for i in used)
    return f"Eligibility conditions compared {cites}:\n\n" + head + "\n" + "\n".join(rows), used


def decision_answer(decisions: List[Dict[str, Any]], rule_ref: Dict[Tuple[str, int], int]) -> str:
    """Short verdict text; the per-condition checklist is returned separately in `decisions`."""
    out = []
    for d in decisions:
        refs = sorted({rule_ref[(c["source"]["document"], c["source"]["page"])] for c in d["conditions"]
                       if (c["source"]["document"], c["source"]["page"]) in rule_ref})
        cite = "".join(f"[{i}]" for i in refs)
        failed = [c for c in d["conditions"] if c["outcome"] == "FAIL"]
        if d["verdict"] == "ELIGIBLE":
            out.append(f"**You appear to be eligible for the {d['policy']}.** Every condition in the policy is met by the details you gave {cite}.")
        elif d["verdict"] == "NOT_ELIGIBLE":
            reasons = "; ".join(_why(c) for c in failed)
            out.append(f"**You are not eligible for the {d['policy']}.** {reasons} {cite}")
            if d["missing"]:
                out.append(f"(Not checked because you didn't mention them: {', '.join(d['missing'])}.)")
        else:
            out.append(f"**I can't confirm your eligibility for the {d['policy']} yet.** Nothing you mentioned rules you out, "
                       f"but please also tell me: {', '.join(d['missing'])} {cite}.")
    return "\n\n".join(out).strip()


def _why(c: Dict[str, Any]) -> str:
    words = {">=": "at least", ">": "more than", "<=": "at most", "<": "less than", "in": "one of", "==": "", "!=": "not"}
    exp, got = c["expected"], c["actual"]
    if isinstance(exp, bool):
        return f"The policy requires: {c['source']['text'].rstrip('.')}."
    if isinstance(exp, list):
        exp = " / ".join(map(str, exp))
    elif isinstance(exp, float) and exp.is_integer():
        exp = int(exp)
    if isinstance(got, float) and got.is_integer():
        got = int(got)
    return f"{c['label']} must be {words.get(c['operator'], c['operator'])} {exp}, and yours is {got}."


def possessive(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def not_found_answer(org_name: str) -> str:
    return (f"I couldn't find this in {possessive(org_name)} knowledge base, so I won't guess. "
            "Please rephrase your question or contact the organization directly.")
