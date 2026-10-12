# Indigenous Student Funding Navigator

**A free funding board for First Nations, Inuit and Métis students in Canada.** Browse scholarships, bursaries and funding programs, see on a map where support is, or ask in plain words. Each record shows its amount, deadline, source and what is still to confirm with the provider.

## 1. Idea and choices

**The problem.** Funding for Indigenous students sits in separate systems (PSSSP, Inuit and Métis programs, institutional awards, private foundations), each with its own rules and dates. The best national lead, the federal [Indigenous Bursaries Search Tool](https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328) (540 entries), asks students to confirm everything with each provider, and Indspire covers only its own awards. Nothing puts rules, dates and sources in one place or shows where support is ([evidence](docs/build-session-1.md)).

**What the site does.** *Explore*: search, filters, and a detail page per record with the provider's own words and a link to its page. *Statistics*: a map of Canada and charts that narrow each other. *AI search and chat* (optional): the model can only choose among fixed tools over the published records, so it can only return records that exist. Nothing decides for the student: a condition only the provider can judge is shown as *to confirm*, not as a yes or a no.

## 2. Data and how it supports the result

**The data** is [`data/awards.jsonl`](data/awards.jsonl): 529 published records ([schema](docs/schemas/opportunity-record-1.0.schema.json)) from public web pages, in every province and territory. Each has its provider, official URL, deadline rule, amount, eligibility rules and the quotes that support them. 486 are federal-directory entries (dated, no deadline or application steps, machine-read and checked against the stored page, not reviewed by a person); 43 were read on the providers' own pages. A region count is the number of records that state that region, not a measure of need or of the money available.

**Permission.** Information from Indigenous Services Canada is reproduced under the Government of Canada's non-commercial reproduction terms, with the statement they require shown in the app. For other providers we use public facts and short quotations with a link back and the date checked; their terms of use have not been read by a person yet (`access_status: unreviewed` in [sources.yaml](sources.yaml)), and the About page offers a contact for corrections or removal. The app collects no personal data.

**How it supports the result.** [`tests/test_export_path.py`](tests/test_export_path.py) loads the dataset into a fresh database and checks that the API serves exactly its titles, amounts and links, and that **every amount and date shown appears in the quote that supports it**. [`tests/test_filter_parity.py`](tests/test_filter_parity.py) checks that the site and the API filter, sort and count about 600 cases the same way.

## 3. Run it locally

Python 3.12 and Git are required; Node.js 20+ and Chrome are optional (for the checks).

```powershell
git clone https://github.com/YuzhengShi/Datathon-Season-2026.git
cd Datathon-Season-2026
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install --no-deps -e .
.\scripts\start_app.ps1        # builds the database from data/awards.jsonl, then opens http://127.0.0.1:8000/
```

If Windows refuses port 8000, add `-Port 8080`; if PowerShell refuses to run scripts, use `powershell -ExecutionPolicy Bypass -File .\scripts\start_app.ps1`. On macOS or Linux use `source .venv/bin/activate` and `scripts/start_app.sh` (only the Windows script has been run). AI search stays off until `.env` has `LLM_ENABLED=true` and a key ([docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)); everything else works without it.

**Data preparation** is not needed: the prepared dataset is in the repository. To rebuild it from the sources (network, about ten minutes): copy `.env.example` to `.env`, set `USER_AGENT` to your contact address, then run `python -m navigator.cli pipeline --mode live --limit 1000 --max-pages 700 --resume` and `python -m navigator.cli app publish` ([docs/RUNBOOK.md](docs/RUNBOOK.md)).

**Checks.**

```powershell
.\.venv\Scripts\python -m pytest -q                       # 332 tests (includes the JavaScript tests when Node is installed)
npm install --no-save --package-lock=false jsdom@30.1.2   # once, for the next line
node scripts/qa-ui.cjs                                    # 63 checks of the site in a simulated DOM (no browser)
node tests/e2e/site.mjs --base=http://127.0.0.1:8000      # 51 checks in a real Chrome, with the app running (54 with --ai)
```
