"""Unit tests for the System-1 decision models, rule compiler and fact extraction."""
from app.services.facts import extract_facts_pattern, _schema
from app.services.pdf_processing import validate_and_extract
from app.services.rules import compile_rules_pattern, parse_number
from app.system1.classifier import get_classifier
from app.system1.decisions import BooleanModel, ChoiceModel, RelevanceScore, combine, evaluate_parallel
from conftest import SAMPLES


def rule(attr, op, value, vtype="number", policy="Merit Scholarship", rid=1):
    return {"id": rid, "policy": policy, "attribute": attr, "label": attr, "operator": op, "value": value,
            "value_type": vtype, "aliases": [attr], "filename": "x.pdf", "page": 1, "source_text": "", "document_id": 1, "weight": 1.0}


def test_boolean_model_outcomes():
    assert BooleanModel.evaluate(rule("gpa", ">=", 8.5), {"gpa": 8.7}).outcome == "PASS"
    assert BooleanModel.evaluate(rule("gpa", ">=", 8.5), {"gpa": 8.4}).outcome == "FAIL"
    assert BooleanModel.evaluate(rule("gpa", ">=", 8.5), {}).outcome == "UNKNOWN"
    assert BooleanModel.evaluate(rule("has_x", "==", False, "boolean"), {"has_x": True}).outcome == "FAIL"
    assert BooleanModel.evaluate(rule("course", "in", ["degree", "online course"], "choice"), {"course": "Online Course"}).outcome == "PASS"


def test_combiner_verdicts():
    rules = [rule("gpa", ">=", 8.5, rid=1), rule("year", ">=", 2, rid=2)]
    assert combine("P", evaluate_parallel(rules, {"gpa": 9, "year": 3}))["verdict"] == "ELIGIBLE"
    assert combine("P", evaluate_parallel(rules, {"gpa": 9}))["verdict"] == "NEEDS_INFO"
    d = combine("P", evaluate_parallel(rules, {"gpa": 7, "year": None}))
    assert d["verdict"] == "NOT_ELIGIBLE" and d["failed"] == ["gpa"] and d["missing"] == ["year"]
    assert d["score"]["score"] == 0.0 and d["score"]["coverage"] == 0.5


def test_rule_compiler_on_sample_policy():
    pages = validate_and_extract("Scholarship_Rules.pdf", (SAMPLES / "greenfield_university" / "Scholarship_Rules.pdf").read_bytes())
    rules = compile_rules_pattern(pages)
    merit = {r["attribute"]: r for r in rules if r["policy"] == "Merit Scholarship"}
    assert merit["gpa"]["operator"] == ">=" and merit["gpa"]["value"] == 8.5
    assert merit["year_of_study"]["value"] == 2
    assert merit["attendance_pct"]["value"] == 75
    assert merit["has_other_institutional_scholarship"]["value"] is False
    need = {r["attribute"]: r for r in rules if r["policy"] == "Need-Based Financial Aid"}
    assert need["family_income"]["operator"] == "<=" and need["family_income"]["value"] == 600000
    assert all(r["page"] in (2, 3) for r in rules)


def test_parse_number_variants():
    assert parse_number("Rs. 6,00,000") == 600000
    assert parse_number("4.5 lakh") == 450000
    assert parse_number("75%") == 75
    assert parse_number("second") == 2


def test_fact_extraction_pattern():
    pages = validate_and_extract("Scholarship_Rules.pdf", (SAMPLES / "greenfield_university" / "Scholarship_Rules.pdf").read_bytes())
    merit_rules = [r for r in compile_rules_pattern(pages) if r["policy"] == "Merit Scholarship"]
    schema = _schema(merit_rules)
    f = extract_facts_pattern("I'm a third-year student, CGPA 8.9, attendance 78%, and I hold the Sports Excellence Scholarship. "
                              "Am I eligible for the Merit Scholarship?", schema, ["Merit Scholarship"])
    assert f["year_of_study"] == 3 and f["gpa"] == 8.9 and f["attendance_pct"] == 78
    assert f["has_other_institutional_scholarship"] is True
    f2 = extract_facts_pattern("I'm in 2nd year with GPA 9 and I don't have any other scholarship. Merit Scholarship?", schema, ["Merit Scholarship"])
    assert f2["has_other_institutional_scholarship"] is False and f2["attendance_pct"] is None


def test_choice_model_prefers_requested_policy():
    policies = {"Merit Scholarship": [rule("gpa", ">=", 8.5)], "Sports Excellence Scholarship": [rule("gpa", ">=", 6, policy="Sports Excellence Scholarship")]}
    c = ChoiceModel.choose("I already have the Sports Excellence Scholarship. Am I eligible for the Merit Scholarship?", policies, [])
    assert c.selected == ["Merit Scholarship"]
    assert ChoiceModel.choose("What is the weather today?", policies, []).selected == []


def test_classifier_labels():
    clf = get_classifier()
    assert clf.predict("How do I apply for the scholarship?").label == "procedural"
    assert clf.predict("Compare annual leave and sick leave").label == "comparison"
    assert clf.predict("My GPA is 9 and I'm in second year. Am I eligible for the merit scholarship?").label == "eligibility"
    assert clf.predict("hello").label == "greeting"


def test_relevance_score_separates_in_and_out_of_scope():
    assert RelevanceScore.score({"idf_coverage": 0.9, "top_cosine": 0.3, "bm25_norm": 0.5}, 0.35).answerable
    assert not RelevanceScore.score({"idf_coverage": 0.2, "top_cosine": 0.1, "bm25_norm": 0.15}, 0.35).answerable
