# Data sources

`sources.yaml` lists the official entry points. They are **starting points for discovery**; nothing in the file is a
verified award. Each source has a stable `source_id`, the administering organisation, a role, a parser (adapter), a
language, and the **allowed domains and path prefixes**. Those bound every request *and every redirect hop*: a redirect
that leaves the allowlist, uses another scheme, points at a private/loopback/link-local address, or carries credentials
is refused. The API never accepts a user-supplied URL to fetch.

| source_id | start URL | administrator | role | parser |
| --- | --- | --- | --- | --- |
| `isc_bursaries_index` | sac-isc.gc.ca/eng/1351185180120/1351685455328?wbdisable=true | Indigenous Services Canada | discovery_index | `isc_index` |
| `indspire_apply_now` | indspire.ca/apply-now/ | Indspire | application_policy | `indspire_policy` |
| `indspire_funding` | indspirefunding.ca/ | Indspire | award_listing | `indspire_funding` |
| `isc_psssp` | sac-isc.gc.ca/eng/1100100033682/1531933580211 | Indigenous Services Canada | funding_channel | `curated_channel` |
| `isc_inuit_strategy` | sac-isc.gc.ca/eng/1578850688146/1578850715764 | Indigenous Services Canada | funding_channel | `curated_channel` |
| `isc_metis_strategy` | sac-isc.gc.ca/eng/1578855031863/1578855057804 | Indigenous Services Canada | funding_channel | `curated_channel` |
| `ubc_award_descriptions` | students.ubc.ca/.../descriptions-awards-indigenous/ | The University of British Columbia | award_listing | `ubc_sections` |
| `ubc_award_context` | students.ubc.ca/.../awards-indigenous/ | The University of British Columbia | application_context | `context_only` |
| `sfu_indigenous_awards` | sfu.ca/students/financial-aid/indigenous/scholarship-and-awards.html | Simon Fraser University | award_listing | `curated_awards` |
| `mnbc_steps` | mnbc.ca/STEPS | Métis Nation British Columbia | funding_channel | `curated_channel` |

**Status in this build: none of these pages has been fetched.** The environment this was written in had no network, so there
are no real snapshots, no real records, and the adapters have only met synthetic structural fixtures.

## Terms of use and robots.txt

`robots.txt` is read per host and recorded in the run manifest (4xx = no rules; 5xx/unreachable = treated as disallowed,
as RFC 9309 advises). **robots allowing a path does not mean the site's terms allow reuse.** Every source is marked
`access_status: unreviewed`, and every live run writes that warning into its manifest. A person must read each site's terms
and then set `reviewed_ok` or `restricted` (restricted sources are not fetched). Never bypass a login, captcha or access
restriction. The fetcher identifies itself with `USER_AGENT` (set a contact address in `.env`), spaces requests per host,
honours a *bounded* `Retry-After` on HTTP 429, retries only a few times, and caps the response size.

## What each adapter does - and refuses to do

| adapter | produces | never does |
| --- | --- | --- |
| `isc_index` | **discovery entries** (`data/discovery/isc_bursaries_index.jsonl`) with name, province, institution, field, group, detail link, plus `declared_count`, observed rows, `coverage`, `pagination_complete` | create opportunities; mark an entry verified; merge entries by title; treat the declared count (538 was seen) as a target |
| `ubc_sections` | one candidate per award section (heading level chosen by repetition), title, short summary, explicit `Month D, YYYY` deadlines (timezone unknown), eligibility paragraphs as *unstructured* conditions with verified quotes | structure eligibility, guess an amount, invent a cycle, or publish a section that has nothing verifiable (those stay `pending` + `draft`) |
| `indspire_funding` | listing page -> follows links one level; each detail page becomes a candidate; a `Donor:`/`Sponsored by:` line becomes `donor_name` | count a donor as a separate administrator; infer anything from the listing alone |
| `indspire_policy` | policy-looking sentences with locators (`data/discovery/...`), no records | decide which awards share a form or which cycle applies (that needs a curated mapping with evidence) |
| `curated_awards` / `curated_channel` | records from `data/curated/<source_id>.yaml`, each fact tied to an exact quote that is re-verified against the snapshot | accept a quote that is not on the page (it becomes a `pending` item with the reason) or claim human review without a review record |
| `context_only` | nothing | extract opportunities |

All adapters write a `pending` item, with the reason, whenever the structure is not what they expect. Nothing is guessed to
fill a gap.

## ISC bursaries index: what was observed and its limits

Observed on 2026-10-07 (page *text* obtained through a web fetch of a mirror domain, not a raw HTML snapshot): a table with
columns `Name | Province/Territory | Institution | Field of Study | Indigenous Group`; the sentence "There are 538 bursaries
found."; an "Update in progress" notice; some rows with empty cells; and repeated award names for different institutions.
The adapter reads the **raw HTML table** because empty cells would otherwise shift columns in plain text. The earlier audit
that recorded 538 entries on 2026-10-05 is a historical observation, **not** the number to crawl and **not** 538 verified
scholarships. Each run recounts and records the declared count, the rows actually read, the coverage and whether
pagination is complete (`data/discovery/isc_bursaries_index.summary.json`, freshness report -> *discovery*).
Whether the detail-page links, pagination and column layout match the adapter on the real page is **unverified**.

## Conflicts between pages, policies and yearly guides

When a current page, an official policy and a yearly guide disagree, the record keeps **both** statements as evidence and goes
to review. A record may carry `conflicts: [{field_path, summary, evidence_ids}]` (at least two different quotes); the validator
then requires `review_status: pending` and an unpublished record, and the importer unpublishes an already stored record the moment
a conflict appears, so a public answer is never silently chosen. Curated mappings declare conflicts with `conflicts:` + `quotes:`
(see `data/curated/README.md`). Also implemented: an input older than the stored version never overwrites it (`pending_review`)
and source-record-key changes are held for review.
**Detecting contradictions between different documents automatically is not implemented**: a person (or a curated mapping) has
to notice them.

## Funder-side conditions versus student conditions

National programmes often set conditions for the organisation or government that *receives* the money (an annual plan, a
reporting duty) and different, often local, rules for students. They are recorded apart: `eligibility.funder_conditions` holds
the former (each with evidence); they are shown to students for context (`funder_side_conditions` in `/match`) but never decide a
student's result. Student rules that a local administrator decides stay `unknown` with a contact route
(`needs_provider_confirmation`).

## First things to do on a networked machine

1. Review terms of use per site; update `access_status`.
2. `python -m navigator.cli fetch --mode live --max-pages 50` and read `data/runs/<run>.json` (robots status, failures).
3. Open the stored snapshots and compare them with the adapters' assumptions (ISC table, UBC headings, Indspire detail pages).
4. `python -m navigator.cli extract --mode live`; read `data/discovery/*.summary.json` and the `pending` list.
5. Write curated mappings for SFU, MNBC and the ISC channel pages (`data/curated/README.md`).
6. `python -m navigator.cli pipeline --mode live --limit 30 --max-pages 50 --resume`; read the freshness report.

## What the first real fetch showed

See [HANDOFF.md](HANDOFF.md) section 3: ISC index read 540/540 entries; ISC detail pages live under `/eng/<id>/<id>` (links are `http://`); SFU is a real awards table; the Indspire funding portal lists donors, not awards; UBC answered HTTP 403.
