# Build Session 2: how this repository meets the checklist

Each line says **what was checked**, **where the evidence is**, and **how to check it yourself**. Three lines are statements only the project owner can make: they are marked *owner*, and nothing in the code can make them for the owner.

## 1. Own the idea

| Check | Status | Evidence |
| --- | --- | --- |
| Brief written in my own words before asking an LLM | Met | [build-session-1.md](build-session-1.md), committed on 2026-10-05 (`git log --format='%h %ad %s' --date=short -- docs/build-session-1.md`, before any Build Session 2 work). It states the problem, the alternatives, the evidence and the intended result. |
| I can explain why the idea matters to me as the N of 1 user | *Owner* | The README does not write this for you. Be ready to say, in your own words, when you met the problem and one real example. |
| What existing alternatives leave unresolved | Met | README section 1 and [build-session-1.md](build-session-1.md) section 1: the federal directory asks students to confirm everything and, in our data, states no deadline for any of the 25 detail pages we read; Indspire covers only its own awards. |
| Key choices connected to evidence | Met | The table in README section 1 links each choice to a number in the data (directory entries last updated 2012 to 2025; a $500 award that is $1,000 on the provider's page; a bursary its provider paused). |
| I evaluated the LLM's suggestions instead of accepting the first answer | *Owner* | Visible in the repository: the Session 1 plan to extract criteria with an LLM was replaced by verifiable rules and quotes; directory entries are labelled instead of presented as confirmed; blocked sites are not bypassed; the first User-Agent was changed to say what the crawler is for. Decisions and findings: [HANDOFF.md](HANDOFF.md) sections 4 to 9. |

## 2. The demo is an easy proof of value

| Check | Status | Evidence |
| --- | --- | --- |
| One real situation where I would use the app | Met (the situation is a described persona; see the note below) | README section 4: a First Nations undergraduate at SFU who wants to know what she can apply for and by when. |
| The interface makes the purpose and result understandable | Met | The welcome page states the promise; every card shows amount, deadline, source and "what you meet / what to confirm". Screens are exercised by [tests/e2e/smoke.mjs](../tests/e2e/smoke.mjs). |
| The demo shows an action and a result it actually produces | Met | README section 4 lists the exact answers and the results (30 of 58 shown, 28 hidden, the open award, the clarification case, the shared application). Every number is produced by the code and asserted in [tests/test_export_path.py](../tests/test_export_path.py) or the browser test. |
| I can explain how the result helps solve the problem | *Owner* | Before and after is written down in README section 4. |
| Claims are supported by visible behaviour and the data used | Met | `tests/test_export_path.py` checks that every amount and date the app shows appears in the quote that supports it. |
| The value is clear without hypothetical features | Met | Nothing in the demo path needs a future feature, more data, or more users. |

*Note.* The checklist asks for a real situation of the first user. The persona in the README is the situation the app was built for and the one the data supports; replace or extend it with the owner's own example if it differs.

## 3. Data + idea to a working app

The app is a small Python service plus a static frontend served by it, not a purely static site. That is allowed ("a working local app is enough"); a static export is listed as an option for Build Session 3.

| Check | Status | Evidence |
| --- | --- | --- |
| Real, permitted data relevant to the problem | Met, with one open item | 58 records from public pages ([README section 2](../README.md)). Government of Canada content is used under its non-commercial reproduction terms, with the statement those terms require shown in the app. For other providers: facts and short quotes with a link, robots.txt honoured, not copied wholesale. **Open:** their terms of use have not been read by a person (`access_status: unreviewed`); the About page gives a contact for removal. UBC refuses automated access, so nothing is taken from it. |
| Displayed results are supported by the data | Met | `tests/test_export_path.py` (API equals dataset; amounts and dates appear in their quotes). |
| The browser interactions needed for the demo work | Met | `node tests/e2e/smoke.mjs`: 30 checks in a real browser (questionnaire, search, filters, sort, save, list, detail, a skipped question, a shared application, a 390 px phone). |
| Output is clear and useful to the first user | *Owner* | Screens in `docs/DEMO.md`; judge them as the first user. |
| One complete path checked from data through the app to a result | Met | Dataset, then a database built without the saved pages, then the API, then the browser: the last two commands above. Also reproduced from a fresh clone (see below). |
| The repository has the files and instructions to reproduce locally | Met | [README section 3](../README.md); `requirements.lock` pins exact versions; `data/awards.jsonl` is the prepared data; `scripts/start_app.ps1` builds the database and starts the app. Only Windows has been run; the bash script is untested. |

## Submission

README sections: idea and choices; data and how it supports the result; how to run (including data preparation); the demo path; what works and what remains before Build Session 3. Same repository as Build Session 1. The Session 1 text is preserved in [build-session-1.md](build-session-1.md).

## Exit condition

> I own the idea and can explain my choices. I have a working local app that uses real data, and I can demonstrate a useful result for myself as the first user without relying on hypothetical future features.

The second sentence is evidenced above. The first is the owner's to say.
