"""System-1 model #1 — Question-type CLASSIFICATION.

A small supervised model (TF-IDF word+char n-grams -> logistic regression) trained at
startup on labelled example questions. It runs in ~1 ms, is deterministic, and returns a
calibrated probability per class, so the application can route the question without an
LLM call. Classes:

  factual      direct information lookup            "What is the hostel fee?"
  procedural   steps / how-to                       "How do I apply for re-evaluation?"
  policy       rules, permissions, consequences     "Can I hold two scholarships?"
  eligibility  personal multi-condition decision    "I have a GPA of 8.7 ... am I eligible?"
  comparison   contrast two or more items           "Compare annual and sick leave"
  greeting     small talk / meta                    "hi", "what can you do?"
"""
import itertools
import random
import threading
from dataclasses import dataclass
from typing import Dict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

THINGS = ["merit scholarship", "sabbatical leave", "hostel accommodation", "education reimbursement", "remote work",
          "annual leave", "sick leave", "need-based aid", "the loan", "the internship program", "travel allowance",
          "maternity leave", "the relocation benefit", "health insurance", "the refund", "re-evaluation", "the bonus"]
PAIRS = list(itertools.combinations(["annual leave", "sick leave", "merit scholarship", "sports scholarship",
                                     "single room", "double room", "hybrid work", "remote work abroad",
                                     "plan A", "plan B", "need-based aid", "education reimbursement"], 2))
FACTS = ["my GPA is 8.2", "I have 14 months of service", "I am in third year", "my attendance is 80%",
         "my rating is 4", "my family income is 5 lakh", "I am on a PIP", "I already hold a sports scholarship",
         "I have completed probation", "I joined 8 months ago", "I am 23 years old", "my credit score is 720",
         "I don't have any other scholarship", "I live 120 km away", "I want 20 days abroad"]

TEMPLATES: Dict[str, list] = {
    "factual": ["What is the amount of {t}?", "How much is {t}?", "How many days of {t} do we get?",
                "When is the deadline for {t}?", "What is {t}?", "Who handles {t}?", "What are the timings for {t}?",
                "Tell me about {t}", "What is the fee for {t}?", "Where is the office for {t}?",
                "how many {t} days are there", "what does {t} cover", "what's the value of {t}",
                "What is the contact email for {t}?", "What are the mess timings?", "What time do the hostel gates close?"],
    "procedural": ["How do I apply for {t}?", "What are the steps to get {t}?", "What is the process for {t}?",
                   "What documents do I need for {t}?", "How can I request {t}?", "how to claim {t}",
                   "Walk me through applying for {t}", "Where do I submit the {t} form?", "how do i appeal {t}",
                   "What is the procedure to apply for {t}?", "how should I raise a request for {t}"],
    "policy": ["Can I hold {t} and another benefit at the same time?", "Is it allowed to carry forward {t}?",
               "What happens if I miss the deadline for {t}?", "What is the rule about {t}?", "Are visitors allowed in {t}?",
               "Is {t} paid or unpaid?", "Can {t} be cancelled?", "What is the policy on {t}?", "Is smoking allowed?",
               "Can a student hold two scholarships?", "What are the rules for {t}?", "Is there a penalty for {t}?",
               "What are the eligibility criteria for {t}?", "Who is eligible for {t}?", "What are the requirements for {t}?"],
    "eligibility": ["{f} and {f2}. Am I eligible for {t}?", "{f}, {f2}. Can I get {t}?", "Do I qualify for {t}? {f}.",
                    "I want {t}. {f} and {f2}.", "Am I eligible for {t} if {f}?", "{f}. Will I get {t}?",
                    "Can I apply for {t}? {f}, {f2}", "{f} and {f2}, is that enough for {t}?",
                    "Given that {f}, am I allowed to take {t}?", "Would I qualify for {t} since {f}?",
                    "Am I eligible for {t}?", "Can I get {t}?", "Do I qualify for {t}?"],
    "comparison": ["Compare {a} and {b}", "What is the difference between {a} and {b}?", "{a} vs {b}",
                   "Which is better, {a} or {b}?", "How does {a} differ from {b}?", "Compare {a} with {b} in terms of benefits",
                   "difference between {a} and {b}", "Is {a} more than {b}?", "{a} or {b}: which gives more?",
                   "Compare the eligibility for {a} and {b}", "Compare the eligibility criteria of {a} and {b}",
                   "How do the requirements for {a} and {b} differ?", "Difference in eligibility between {a} and {b}"],
    "greeting": ["hi", "hello", "hey there", "good morning", "thanks", "thank you!", "who are you?",
                 "what can you do?", "help", "ok", "bye", "hello, can you help me?", "how are you"],
}


def _training_set(seed: int = 7):
    rng = random.Random(seed)
    X, y = [], []
    for label, templates in TEMPLATES.items():
        for tpl in templates:
            for _ in range(6 if "{" in tpl else 2):
                a, b = rng.choice(PAIRS)
                f, f2 = rng.sample(FACTS, 2)
                X.append(tpl.format(t=rng.choice(THINGS), a=a, b=b, f=f[0].upper() + f[1:], f2=f2))
                y.append(label)
    return X, y


@dataclass
class Classification:
    label: str
    confidence: float
    probabilities: Dict[str, float]


class QuestionClassifier:
    def __init__(self):
        X, y = _training_set()
        self.model = Pipeline([
            ("features", FeatureUnion([
                ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True)),
                ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)),
            ])),
            ("clf", LogisticRegression(max_iter=2000, C=8.0)),
        ])
        self.model.fit(X, y)
        self.training_size = len(X)

    def predict(self, question: str) -> Classification:
        probs = self.model.predict_proba([question])[0]
        classes = list(self.model.classes_)
        best = int(probs.argmax())
        return Classification(classes[best], float(probs[best]), {c: round(float(p), 3) for c, p in zip(classes, probs)})


_instance = None
_lock = threading.Lock()


def get_classifier() -> QuestionClassifier:
    global _instance
    with _lock:
        if _instance is None:
            _instance = QuestionClassifier()
        return _instance
