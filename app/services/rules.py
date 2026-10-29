"""Rule compilation: turn policy text into structured, machine-checkable rules.

This runs ONCE per document at upload time ("compile knowledge"), so that at question time
the System-1 decision models can evaluate eligibility deterministically instead of asking an
LLM to "reason" about it.

Two compilers:
  * LLM compiler      – used when an LLM is configured; reads each page and emits JSON rules.
  * Pattern compiler  – deterministic fallback (also used if the LLM call fails); understands
                        common policy phrasing such as "minimum CGPA of 8.0", "Year 2 or above",
                        "must not hold any other scholarship", "one of A, B or C".
"""
import json
import logging
import re
from typing import Dict, List, Optional

from app.services import llm
from app.services.pdf_processing import Page

log = logging.getLogger("rules")

# Canonical attributes that many policies share. Order matters: more specific first.
LEXICON: List[dict] = [
    {"key": "attendance_pct", "label": "Attendance (%)", "aliases": ["attendance"]},
    {"key": "gpa", "label": "Cumulative GPA", "aliases": ["cgpa", "gpa", "grade point average", "grade point"]},
    {"key": "family_income", "label": "Annual family income", "aliases": ["family income", "household income", "parental income", "annual income", "income"]},
    {"key": "credit_score", "label": "Credit score", "aliases": ["credit score", "cibil score", "cibil"]},
    {"key": "performance_rating", "label": "Performance rating", "aliases": ["performance rating", "appraisal rating", "rating"]},
    {"key": "tenure_months", "label": "Length of service (months)", "aliases": ["months of continuous service", "continuous service", "months of service", "tenure", "service"]},
    {"key": "experience_years", "label": "Work experience (years)", "aliases": ["years of experience", "work experience", "experience"]},
    {"key": "age", "label": "Age", "aliases": ["years of age", "age"]},
    {"key": "year_of_study", "label": "Year of study", "aliases": ["year of study", "year"]},
    {"key": "distance_km", "label": "Distance from campus/office (km)", "aliases": ["km", "kilometres", "kilometers", "distance"]},
    {"key": "duration_weeks", "label": "Duration (weeks)", "aliases": ["weeks"]},
    {"key": "days_requested", "label": "Days requested", "aliases": ["working days", "consecutive days", "days"]},
]

POLICY_NOUNS = r"(scholarship|placement|posting|referral|internship|instalment|installment|laptop|aid|accommodation|hostel|sabbatical|admission|grant|fellowship|award|loan|leave|allowance|assistance|reimbursement|programme|program|benefit|bonus|policy|scheme|work from home|remote work|relocation|stipend|waiver)"
SECTION_TRIGGERS = r"(eligib|criteria|requirement|conditions|who can apply|qualif)"
GENERIC_WORDS = {"the", "any", "other", "a", "an", "of", "for", "at", "or", "and", "to", "in", "institutional", "existing", "active", "current", "valid", "university", "company"}

WORD_NUMBERS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "final": 4,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}


# ---------------------------------------------------------------- helpers
def parse_number(text: str) -> Optional[float]:
    """Parse '8.5', '75%', 'Rs. 6,00,000', '6 lakh', '₹4.5 lakhs', '2nd', 'second'."""
    t = text.lower().replace("₹", " ").replace("rs.", " ").replace("inr", " ")
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(lakh|lac|lakhs|crore|k\b|thousand)?", t)
    if m:
        value = float(m.group(1).replace(",", ""))
        unit = m.group(2) or ""
        if unit.startswith("la"):
            value *= 100_000
        elif unit == "crore":
            value *= 10_000_000
        elif unit in ("k", "thousand"):
            value *= 1_000
        return value
    for word, num in WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", t):
            return float(num)
    return None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]


def _operator_for(line: str) -> Optional[str]:
    l = line.lower()
    # \b on both sides so that e.g. "undergraduate" does not read as "under".
    if re.search(r"\b(minimum|at least|not less than|or above|or higher|or more|or later|and above|min\.?|greater than or equal|no less than)\b", l):
        return ">="
    if re.search(r"\b(maximum|at most|not exceed|or below|or less|or fewer|up to|max\.?|no more than|cannot exceed|must not exceed)\b", l):
        return "<="
    if re.search(r"\b(more than|greater than|above|over|exceeds?)\b", l):
        return ">"
    if re.search(r"\b(less than|below|under|fewer than)\b", l):
        return "<"
    if re.search(r"\b(exactly|equal to)\b", l):
        return "=="
    return None


def find_attribute_near(text: str, start: int, end: int, lexicon: List[dict] = None) -> Optional[dict]:
    """Pick the attribute whose alias is closest to the number at text[start:end].
    Words *before* a number are the usual subject ("minimum GPA of 8.5"), so words after it
    ("75% in the previous academic year") are penalised."""
    low = text.lower()
    best, best_dist = None, 10 ** 9
    for attr in lexicon or LEXICON:
        for alias in attr["aliases"]:
            for m in re.finditer(rf"\b{re.escape(alias)}\b", low):
                if m.end() <= start:
                    dist = start - m.end()
                elif m.start() >= end:
                    dist = int((m.start() - end) * 1.6) + 2
                else:
                    continue
                if dist < best_dist:
                    best, best_dist = attr, dist
    return best if best_dist <= 60 else None


def _object_phrase(fragment: str) -> str:
    fragment = re.split(r"[.;,(]| at the time| during| while| from the| in the| for the", fragment)[0]
    words = [w for w in fragment.strip().split() if w]
    return " ".join(words[:7])


# Single words too common to identify a fact on their own.
COMMON_WORDS = {"plan", "period", "service", "level", "time", "year", "days", "or", "and", "full", "other", "represented", "dues", "fee"}
PERSON_NOUNS = {"student", "employee", "applicant", "person", "candidate", "staff", "member"}


def _aliases_for_phrase(phrase: str) -> List[str]:
    words = re.findall(r"[a-z0-9][a-z0-9-]*", phrase.lower())
    content = [w for w in words if w not in GENERIC_WORDS and w not in {"a", "an", "on", "the"}]
    aliases = {" ".join(words), " ".join(content)}
    distinctive = [w for w in content if w not in PERSON_NOUNS]
    if distinctive:
        aliases.add(" ".join(distinctive))
        aliases.add(distinctive[-1])  # "completed probation" -> "probation"
    if len(content) >= 2:
        aliases.add(f"{content[0]} {content[-1]}")  # "sports excellence scholarship" -> "sports scholarship"
        aliases.add(f"{content[-2]} {content[-1]}")  # "represented ... state level" -> "state level"
    for a in list(aliases):
        if "-" in a:
            aliases.add(a.replace("-", " "))
    caps = re.findall(r"\b[A-Z][a-z]+", phrase)
    if len(caps) >= 2:  # "Performance Improvement Plan" -> "pip"
        aliases.add("".join(w[0] for w in caps).lower())
    return [a for a in aliases if a and a not in PERSON_NOUNS and a not in COMMON_WORDS]


def _is_policy_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 80) or s.endswith(".") or s.endswith(":") and len(s) > 60:
        return False
    if re.search(r"\b(must|should|will|may|is|are)\b", s, re.I):
        return False
    if not re.search(POLICY_NOUNS, s, re.I):
        return False
    words = re.findall(r"[A-Za-z]+", s)
    caps = sum(1 for w in words if w[0].isupper() or w.lower() in {"of", "and", "for", "the", "from", "to"})
    return bool(words) and caps / len(words) >= 0.8


def _clean_heading(line: str) -> str:
    s = re.sub(r"^(section\s+)?\d+(\.\d+)*[.)]?\s*", "", line.strip(), flags=re.I)
    s = re.sub(r"\s*[-–:]\s*(eligibility|criteria|overview|details).*$", "", s, flags=re.I)
    s = re.sub(r"\s+(eligibility criteria|eligibility requirements|eligibility|criteria|requirements|conditions)$", "", s, flags=re.I)
    return s.strip(" :-–")


# ---------------------------------------------------------------- pattern compiler
def compile_rules_pattern(pages: List[Page]) -> List[dict]:
    rules: List[dict] = []
    policy: Optional[str] = None
    in_criteria = False
    for page in pages:
        lines = [l.strip() for l in page.text.split("\n") if l.strip()]
        lines = [l for l in lines if not re.search(r"\bpage\s+\d+(\s+of\s+\d+)?\s*$", l, re.I)]  # running headers/footers
        # merge wrapped bullet lines: a line that doesn't start a new item continues the previous one
        merged: List[str] = []
        for l in lines:
            starts_item = re.match(r"^(\d+[.)]|[a-z][.)]|[-•*])\s", l) or _is_policy_heading(l) or l.endswith(":")
            if merged and re.fullmatch(r"(\d+|[a-z])[.)]", merged[-1]):
                merged[-1] += " " + l  # "1." on its own line, item text on the next
            elif merged and not starts_item and not merged[-1].endswith((".", ":")) and len(merged[-1]) > 40:
                merged[-1] += " " + l
            else:
                merged.append(l)
        for line in merged:
            if _is_policy_heading(line) and not re.search(SECTION_TRIGGERS, line, re.I):
                policy = _clean_heading(line)
                in_criteria = False
                continue
            if re.search(SECTION_TRIGGERS, line, re.I) and len(line) < 90 and not re.search(r"\bmust\b", line, re.I):
                if _is_policy_heading(line):
                    policy = _clean_heading(line)
                in_criteria, seen_items = True, False
                continue
            if not policy or not in_criteria:
                continue
            is_item = bool(re.match(r"^(\d+[.)]|[a-z][.)]|[-•*])\s", line))
            if (not is_item and seen_items) or (re.match(r"^[A-Z][A-Za-z &/]{2,60}$", line) and not re.search(r"\bmust\b", line, re.I)):
                in_criteria = False  # prose after the list, or a new heading, ends the criteria section
                continue
            seen_items = seen_items or is_item
            rule = _parse_criterion(line, policy, page.number)
            if rule:
                rules.append(rule)
    return _dedupe(rules)


def _parse_criterion(line: str, policy: str, page: int) -> Optional[dict]:
    text = re.sub(r"^(\d+[.)]|[a-z][.)]|[-•*])\s*", "", line).strip()
    low = text.lower()

    # 1) choice: "must be one of A, B or C" / "must be enrolled in A, B or C"
    m = re.search(r"(?:one of|either)\s*:?\s*(.+)", text, re.I)
    if m and re.search(r",| or ", m.group(1)):
        options = [o.strip(" .") for o in re.split(r",\s*|\s+or\s+", m.group(1)) if o.strip(" .")]
        options = [re.sub(r"^(and|or)\s+", "", o, flags=re.I) for o in options]
        subject = re.split(r"\bmust\b|\bshould\b", text, flags=re.I)[0].strip() or "category"
        subject_words = [w for w in re.findall(r"[a-z]+", subject.lower()) if w not in GENERIC_WORDS and w not in {"applicant", "student", "employee", "s"}]
        key = slug(" ".join(subject_words[-2:])) or "category"
        return _rule(policy, key, subject.capitalize(), "choice", "in", options, [key.replace("_", " ")] + [o.lower() for o in options], text, page)

    # 2) numeric threshold
    number_text = re.search(r"(₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d+)?\s*(%|lakh|lakhs|lac|crore)?|\b(first|second|third|fourth|final)\b", low)
    op = _operator_for(low)
    attr = find_attribute_near(low, number_text.start(), number_text.end()) if number_text else None
    if number_text and attr and (op or attr["key"] == "year_of_study"):
        value = parse_number(number_text.group(0))
        if value is not None:
            if attr["key"] == "year_of_study" and not op:
                op = ">="
            return _rule(policy, attr["key"], attr["label"], "number", op, value, attr["aliases"], text, page)

    # 3) negative boolean: "must not hold/have/be/receive ..."
    m = re.search(r"\b(?:must not|should not|cannot|may not|is not)\s+(?:currently\s+)?(?:be on|be serving|be under|already hold|already have|hold|have|be|receive|avail)\s+(?:an?\s+|any\s+)?(.+)", text, re.I)
    if m:
        phrase = _object_phrase(m.group(1))
        return _rule(policy, "has_" + slug(phrase), f"Has {phrase}", "boolean", "==", False, _aliases_for_phrase(phrase), text, page)
    m = re.search(r"\b(?:no|not)\s+(?:active|pending|current|existing)\s+(.+)", text, re.I)
    if m:
        phrase = _object_phrase(m.group(1))
        return _rule(policy, "has_" + slug(phrase), f"Has {phrase}", "boolean", "==", False, _aliases_for_phrase(phrase), text, page)

    # 4) positive boolean: "must be a full-time employee", "must have completed probation"
    m = re.search(r"\bmust\s+(?:be|have|hold)\s+(?:an?\s+|successfully\s+)?(.+)", text, re.I)
    if m:
        phrase = re.split(r"\s+(?:or above|or higher|or more|in the previous|within)\b", m.group(1))[0]
        phrase = _object_phrase(phrase)
        if phrase and not re.search(r"\d", phrase):
            return _rule(policy, "is_" + slug(phrase), phrase.capitalize(), "boolean", "==", True, _aliases_for_phrase(phrase), text, page)
    return None


def _rule(policy, attribute, label, value_type, operator, value, aliases, source_text, page, weight=1.0) -> dict:
    return {
        "policy": policy.strip(),
        "attribute": attribute,
        "label": label,
        "value_type": value_type,
        "operator": operator,
        "value": value,
        "aliases": sorted(set(a.lower() for a in aliases if a)),
        "weight": weight,
        "source_text": source_text[:400],
        "page": page,
    }


def _dedupe(rules: List[dict]) -> List[dict]:
    seen, out = set(), []
    for r in rules:
        key = (r["policy"].lower(), r["attribute"], r["operator"], json.dumps(r["value"]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ---------------------------------------------------------------- LLM compiler
LLM_RULE_SYSTEM = """You convert organizational policy text into machine-checkable eligibility rules.
Return ONLY JSON: {"rules": [ ... ]}. Each rule:
{
 "policy": "<exact policy/program name the rule belongs to>",
 "attribute": "<snake_case fact about the person being checked, e.g. gpa, year_of_study, has_sports_scholarship, tenure_months>",
 "label": "<short human label>",
 "value_type": "number" | "boolean" | "choice",
 "operator": ">=" | ">" | "<=" | "<" | "==" | "!=" | "in" | "not_in",
 "value": <number | true/false | list of strings>,
 "aliases": ["<words a person might use for this attribute>"],
 "source_text": "<the sentence the rule came from, verbatim>",
 "page": <page number>
}
Rules:
- Only extract hard eligibility/qualification conditions a person must satisfy. Skip benefits, amounts, deadlines and procedures.
- Prefer these canonical attribute names when they fit: gpa, year_of_study, attendance_pct, family_income (in rupees, absolute number), age, tenure_months, experience_years, performance_rating, credit_score.
- "Must not hold X" => boolean attribute has_<x> with operator == and value false.
- Convert "lakh" to absolute numbers (6 lakh => 600000) and years of service to months when the text says months.
- If the page has no eligibility conditions, return {"rules": []}. Never invent conditions."""


def compile_rules_llm(pages: List[Page], filename: str) -> List[dict]:
    rules: List[dict] = []
    for page in pages:
        prompt = f"Document: {filename}\nPage {page.number}:\n\"\"\"\n{page.text[:6000]}\n\"\"\""
        data = llm.complete_json(LLM_RULE_SYSTEM, prompt)
        for r in data.get("rules", []) if isinstance(data, dict) else []:
            try:
                rules.append(
                    _rule(
                        str(r["policy"]), slug(str(r["attribute"])), str(r.get("label") or r["attribute"]),
                        str(r["value_type"]), str(r["operator"]), r["value"], list(r.get("aliases") or []) + [str(r["attribute"]).replace("_", " ")],
                        str(r.get("source_text", "")), int(r.get("page") or page.number),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
    return _dedupe([r for r in rules if r["operator"] in {">=", ">", "<=", "<", "==", "!=", "in", "not_in"}])


def compile_rules(pages: List[Page], filename: str) -> Dict:
    """Deterministic compiler first; the LLM only fills gaps.

    The pattern compiler is exact, auditable and costs nothing, so it runs on every page. Pages
    that clearly contain eligibility criteria but yielded no rules (phrasing the patterns don't
    understand) are sent to the LLM compiler. This also keeps uploads fast and within free-tier
    LLM quotas. Returns {"rules": [...], "compiler": "pattern" | "pattern+llm"}.
    """
    rules = compile_rules_pattern(pages)
    covered = {r["page"] for r in rules}
    gaps = [p for p in pages if p.number not in covered and re.search(SECTION_TRIGGERS, p.text, re.I)
            and re.search(r"\bmust\b|minimum|maximum|at least|not exceed", p.text, re.I)]
    compiler = "pattern"
    if gaps and llm.is_enabled():
        try:
            extra = compile_rules_llm(gaps, filename)
            if extra:
                rules = _dedupe(rules + extra)
                compiler = "pattern+llm"
        except llm.LLMError as exc:
            log.warning("LLM rule compilation failed for %s (pages %s): %s", filename, [p.number for p in gaps], exc)
    return {"rules": rules, "compiler": compiler}
