# Demo video script (about 12 minutes)

A ready-to-follow recording plan. Timings are approximate. Narration is written as you'd say it; put it in your own words.

## Before you record (5 minutes)

1. Put a Gemini key in `.env` (`LLM_PROVIDER=gemini`, `LLM_API_KEY=...`).
2. Start from a clean database: delete the `data/` folder.
3. Start the app: `uvicorn app.main:app --port 8000`.
4. Start the demo site: `cd demo_site && python -m http.server 5500`.
5. Keep these windows ready:
   - the README on GitHub (architecture diagrams)
   - two browser windows (normal and private) so two orgs can be logged in at once
   - the `sample_data` folder open in your file manager
6. Run `python scripts/seed_demo.py` **only for Nimbus**, or seed both and register a third org live. The simplest option: register Greenfield live and let the seed script create Nimbus.

---

## 1. Introduction (0:00–0:45)

"This is Rulebook, a multi-tenant assistant that turns an organization's PDFs into an assistant they can embed on their website. The key idea: the LLM handles language — understanding the question and writing the answer — while small, deterministic System-1 models make the decisions: what kind of question it is, whether the documents can answer it, which policy applies, and whether each rule is satisfied."

## 2. Architecture (0:45–3:30)

Show the README's architecture diagram and walk through it.

- **Frontend:** dashboard, chat widget, and `embed.js`, which injects a floating button and iframe into any site.
- **Backend:** FastAPI.
  - Admin APIs authenticate with a session token.
  - `/api/ask` authenticates with the public assistant token. The server resolves the token to the organization; the client never sends an org id.
- **Ingestion:** validate limits → extract text per page → page-bounded chunks, so every citation has an exact page → *compile decision rules*. Open the rules dialog later to show this.
- **Retrieval:** BM25 + TF-IDF fused with reciprocal rank fusion. One index per organization, built only from that org's rows.
- **System 1:**
  - classifier (question type)
  - relevance score (can we answer?)
  - choice (which policy?)
  - one Boolean evaluator per rule, run in parallel
  - eligibility score
- **Application logic** combines the results: any FAIL → not eligible; any unknown → needs info; otherwise eligible.
- **LLM:** used in only three narrow places — compiling rules at upload, extracting the asker's facts into a typed schema, and writing the final grounded answer with the decision passed in as data.

Show the sequence diagram. Point out the two parallel stages, and that an out-of-scope question is refused before any LLM call.

## 3. Product walkthrough — Organization A (3:30–6:30)

1. Open http://localhost:8000 → **Create account**: "Greenfield University".
2. Dashboard: empty knowledge base, limits meter "0 of 10".
3. **Validation errors:** upload `sample_data/invalid/Too_Many_Pages_22.pdf` → page-limit error. Upload `not_really_a_pdf.pdf` → invalid PDF error.
4. Upload the three Greenfield PDFs at once. Point at pages, passages and **rules** per document.
5. Click the **10** in Rules for Scholarship_Rules.pdf: "These were compiled from the PDF at upload. Each one keeps its source sentence and page."
6. **Your assistant** panel:
   - the URL
   - Copy and Open
   - the chat-bubble and inline-frame embed codes
   - mention that Regenerate kills the old link
7. Open the assistant link (no login) and ask:
   - "What is the amount of the Merit Scholarship?" → answer with the reference *Scholarship_Rules.pdf — Page 2*. Expand the reference snippet.
   - "How do I apply for re-evaluation of my exam paper?" → numbered steps from Academic_Policies.pdf.
   - "What is the university's policy on international student visas?" → explicit "not in the knowledge base". Open **How this answer was produced**: relevance score below threshold, and there is no LLM step.

## 4. AI decision flow (6:30–9:30) — the core of the demo

Ask:

> I am a 3rd year student with a GPA of 8.7 and 80% attendance, and I already have the Sports Excellence Scholarship. Am I eligible for the Merit Scholarship?

Walk through the response top to bottom:
- **Decision card:**
  - Merit Scholarship: Not eligible
  - 3 of 4 conditions met
  - per-condition rows: required vs. stated value, page number
- Expand **How this answer was produced** and narrate each step with its component badge:
  1. *System 1 · Classification* → eligibility (95%). *Retrieval* ran at the same time.
  2. *System 1 · Score* → answerable.
  3. *System 1 · Choice* → Merit Scholarship. Note that it recognised Sports Excellence as something the student *has*, not what they're asking about.
  4. *LLM · understanding* → turned the sentence into typed facts: year 3, GPA 8.7, attendance 80, has other scholarship = true. It was only given the four attributes this policy needs, and it does not decide anything.
  5. *System 1 · Boolean ×4 (parallel)* → PASS, PASS, PASS, FAIL. These are independent, so they run concurrently.
  6. *App logic + Score* → NOT_ELIGIBLE, score 0.75.
  7. *LLM* → wrote the explanation from the passages, with the verdict passed in as authoritative data.

Then show the other two outcomes:
- "I'm in second year, my CGPA is 9.1 and attendance is 82%. I don't have any other scholarship. Can I get the Merit Scholarship?" → **Eligible**.
- "My family income is 4.5 lakh per year. Am I eligible for need-based financial aid?" → **More information needed**: income met; GPA and full-time status not provided. The assistant asks for them instead of guessing.
- Optional: "Compare the Merit Scholarship and the Sports Excellence Scholarship" → Choice selects both policies; the answer includes a side-by-side table built from the compiled rules.

## 5. Embedding (9:30–10:30)

1. Copy the chat-bubble code from the dashboard.
2. Open `http://localhost:5500/index.html?token=<Greenfield token>&host=http://localhost:8000`. This is a different origin, standing in for the university's own website.
3. Click **Ask Student Services** and ask a question inside the embedded widget.
4. Optional: add `&inline=1` to show the iframe embed as well.

## 6. Multi-tenant isolation (10:30–12:00)

1. In the private window, log in as Nimbus Technologies (`hr@nimbus.example` / `nimbus12345`). Show its different documents and different assistant URL.
2. Ask Nimbus: "I have been with the company for 14 months, completed probation and my rating is 4. Can I work remotely from abroad for 20 days?" → Eligible, from Work_From_Home_Policy.pdf.
3. Ask Nimbus: **"What is the GPA requirement for the Merit Scholarship?"** → not found. Greenfield's documents are invisible to it.
4. Ask Greenfield: **"How many days of paternity leave does Nimbus give?"** → not found.
5. Show the terminal running `pytest -q tests/test_isolation.py` (12 tests). Name a few:
   - an assistant token is rejected on every admin API
   - Org A can't delete Org B's document
   - each retrieval index contains only that org's chunks
   - regenerating the token kills the old link
6. Back on the Greenfield dashboard, show **Questions from visitors**: asked, answered, not found and needs-info counts.

## 7. Close (12:00–12:30)

"To summarise: the LLM understands and explains; System-1 models classify, score, choose and decide, in parallel where possible; and application logic combines everything into an auditable verdict with page-level references. The limitations and production next steps are in the README: dense embeddings, OCR, admin editing of compiled rules, and multi-turn follow-ups."
