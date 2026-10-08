# Indigenous Student Funding Navigator

**A free funding board for First Nations, Inuit and Métis students in Canada.** Answer a few optional questions, then browse scholarships, bursaries and funding programs the way you would browse a store. Each one shows its amount, its deadline, where the information came from, and what you still have to confirm with the provider.

> **Build Session 2:** a working local app on real data. The Build Session 1 submission is kept in [docs/build-session-1.md](docs/build-session-1.md). How this repository meets the Session 2 checklist, item by item, is in [docs/BUILD_SESSION_2.md](docs/BUILD_SESSION_2.md).

## 1. Idea and choices

**The problem.** Funding for Indigenous students sits in separate systems: PSSSP through First Nations and their organisations, Inuit and Métis programs run by their own governments, institutional awards and private foundations. Each has its own rules, dates and application. The best national lead, the federal [Indigenous Bursaries Search Tool](https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328), lists 540 entries but asks students to confirm everything with each provider, and Indspire covers its own awards. Nothing puts the rules, the dates and the source of each claim in one place (evidence in [Session 1](docs/build-session-1.md)).

**What the app does.** Five optional questions (who you are, where you live, what and where you study), then a store-like page: search, filters with live counts, sort, one card per option with its amount (the "price") and deadline, a detail page with the provider's own words and a link to apply, and "My list". It never decides for the student: a condition only the provider can judge is shown as *to confirm*, not as a yes or a no.

**Choices, and the evidence behind them**

| Choice | Why |
| --- | --- |
| Say where every fact comes from | In our data, the 15 federal-directory entries we kept state no deadline and were last updated in 2012 (6), 2013 (1), 2022 (7) and 2025 (1). The providers' own pages corrected some (the Cummins award at Vancouver Island University: $500 in the directory, $1,000 on the university's page) and showed one that is no longer offered (the First Citizens Fund bursary: paused by its provider, so students never see it). |
| Rules and verbatim quotes decide eligibility, not an LLM | Session 1 planned LLM extraction. A wrong "eligible" costs a student real effort, so each statement is a deterministic parser or a hand-written mapping tied to a quote that the pipeline re-checks against the stored page. The LLM path is off on purpose (it stops with an error). |
| A store-like page after a few skippable questions | Direction from the project owner: answer a little, then browse like a shop, with no long form. Skipped means unknown, never "no". |
| Free, no account, answers not stored | Direction from the project owner. Answers live in memory in the open tab; the service neither stores nor logs the profile. |
| Respect the sources | robots.txt, one request per second, a User-Agent that says who we are and why. UBC's pages refuse automated access (HTTP 403): we do not work around it, so UBC awards are missing until UBC agrees. A page that a person saves in a browser can be imported with its provenance. |

Developed with an LLM coding assistant (Claude) under the owner's direction. The app itself uses no LLM.

## 2. Data and how it supports the result

**The data** is [`data/awards.jsonl`](data/awards.jsonl): 58 published records ([schema](docs/schemas/opportunity-record-1.0.schema.json)), each with provider, official URL, deadline rule, amount, eligibility rules and the quotes that support them (396 in total). All of it comes from public web pages:

| Source | Records |
| --- | --- |
| Indigenous Services Canada: Indigenous Bursaries Search Tool (540 entries read, 25 detail pages of British Columbia and national entries) | 15 directory entries (the other 10 were replaced by their provider's own page) |
| Indigenous Services Canada: program pages (PSSSP, the Inuit and Métis Nation post-secondary strategies) | 3 |
| Métis Nation British Columbia: STEPS | 1 |
| Simon Fraser University: Indigenous awards | 8 |
| Vancouver Island University: scholarships and awards database (one shared application) | 25 |
| AFOA Canada, The Canadian Press, Fraser Basin Council (2), Indspire portal (Cenovus), Registered Nurses Foundation of BC | 6 |

**Permission.** Information from Indigenous Services Canada is reproduced under the Government of Canada's non-commercial reproduction terms, with the statement those terms ask for (shown on every affected page and on the About page). For the other providers we use public facts and short quotations with a link back and the date checked, honour robots.txt, and copy no page wholesale; their terms of use have not been read by a person yet (`access_status: unreviewed` in [sources.yaml](sources.yaml)), and the About page gives a contact for corrections or removal. Nothing is taken from sites that refuse automated access. The app collects no personal data.

**How it supports the result.** 43 of 58 records show an amount, 28 show a deadline or a yearly rule (4 more say rolling or set locally), and 25 share one application. [`tests/test_export_path.py`](tests/test_export_path.py) loads the dataset into a fresh database without the saved pages and checks that the API serves exactly the dataset's titles, amounts and links, that **every amount and date shown appears in the quote that supports it**, and that the demo student's results are the expected ones. The freshness report is in [docs/freshness-report.md](docs/freshness-report.md).

## 3. Run it locally

You need Python 3.12 (tested with 3.12.10 on Windows) and Git. Optional: Node.js 20+ (JavaScript tests) and Chrome (browser test).

```powershell
git clone https://github.com/YuzhengShi/Datathon-Season-2026.git
cd Datathon-Season-2026
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
.\scripts\start_app.ps1        # builds the database from data/awards.jsonl, then opens http://127.0.0.1:8000/
```

On macOS or Linux use `source .venv/bin/activate` and `scripts/start_app.sh` (the Windows script is the one that has been run). If Windows refuses port 8000, add `-Port 8080`.

**Data preparation.** None is needed to run: the prepared dataset is in the repository and `start_app` loads it. To rebuild and re-check it from the sources (network access, about 100 polite requests): copy `.env.example` to `.env`, put your contact address in `USER_AGENT`, then `python -m navigator.cli pipeline --mode live --limit 200 --max-pages 200`. The hand-written mappings are in [data/curated](data/curated); the Vancouver Island University ones are generated by `scripts/generate_viu_curated.py`. More: [docs/RUNBOOK.md](docs/RUNBOOK.md), [docs/TECHNICAL_README.md](docs/TECHNICAL_README.md).

**Checks.**

```powershell
.\.venv\Scripts\python -m pytest -q                       # 267 tests (includes the JavaScript logic tests when Node is installed)
node tests/e2e/smoke.mjs --base=http://127.0.0.1:8000    # 30 checks in a real browser; the server must be running
```

## 4. Demo path

**Situation.** A First Nations undergraduate at Simon Fraser University in British Columbia wants to know which funding she can apply for this fall, and by when.

**Action.** Start the app, choose *Start*, and answer: First Nations, registered under the Indian Act: yes, British Columbia, university bachelor's degree, full-time, Simon Fraser University. Choose *Show my scholarships*.

**Result.**
- 30 of the 58 options are shown; 28 are hidden because she cannot apply: the 25 Vancouver Island University awards are for that university's students, and the Inuit and Métis programs and MNBC STEPS are for Inuit beneficiaries and Métis citizens.
- The first cards are the eight SFU Indigenous awards ($1,000 to $5,000), each "Checked on the provider's page", "Meets what we can check" and "2 to confirm with the provider". The Nutrien award shows "Open now" and "Apply by Nov 23, 2026".
- *A skipped question:* leave "registered under the Indian Act" unanswered and the federal PSSSP card says "More answers would help"; its page asks exactly that question and says no card number is needed.
- *A shared application:* choose *Browse everything* and open the Laura Finch Memorial Scholarship: $1,000, "Due every year on Apr 30", "One application covers 24 other awards".

**Before and after.** Before: open the federal tool (540 entries, none of the 25 detail pages we read has a deadline), then each provider's site to find the amount, the date and the rules. After: one list where each option says what it pays, when it is due, whether she meets what can be checked, and where each fact was read. A three-minute script is in [docs/DEMO.md](docs/DEMO.md).

## 5. What works now, and what remains before Build Session 3

**Works now.** The three things promised in Session 1 exist: the dataset ([`data/awards.jsonl`](data/awards.jsonl)), a matching endpoint that returns evidence and flags missing information (`POST /match`), and a freshness report ([docs/freshness-report.md](docs/freshness-report.md), `GET /reports/freshness`). On top of them: the web app described above, a questionnaire whose skipped answers become follow-up questions, and the demo path end to end (267 Python tests and 30 browser checks pass on Windows).

**Remains.** No student interviews or user tests have taken place yet; that is the focus of Build Session 3. Everything shown was checked by the builders and by automated tests.
- *Put it in front of people:* deploy it (the app needs the Python service; a static export with matching in the browser is one option), get feedback from students and advisors, and test matching on manually labelled opportunity and profile pairs, as planned in Session 1.
- *Data:* UBC, which needs UBC's permission; 15 directory-only entries to replace with provider pages; 5 provider pages fetched but not yet mapped; a person's review of the 58 records ("machine-checked" is not "reviewed"); reading each provider's terms of use.
- *Product:* a French version; tests beyond Chrome and Windows; a screen-reader test.
