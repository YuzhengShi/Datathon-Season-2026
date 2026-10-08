# Curated mappings (evidence-checked)

For sources whose pages are free text (SFU, MNBC, the ISC funding-channel pages) a person - or an agent -
records the structured facts here and, for every fact, the **exact quote** that supports it. The pipeline
then verifies each quote against the stored snapshot with the same validator used for everything else.
A bad quote never becomes a record: it is reported as `pending` with the reason.

* One file per source: `data/curated/<source_id>.yaml` (JSON also works). `source_id` must match `sources.yaml`.
* `quotes: [...]` replaces `evidence_ids` wherever evidence is needed. An item may be a string or
  `{quote, url, pdf_page}`; `url` picks which fetched page the quote comes from (default: the source start page).
* Curated records are `extraction_method: curated` and at most `machine_checked`. They become `human_reviewed`
  only if a real `review: {reviewer, reviewed_at}` block is present. Never invent one.
* Conditions on the organisation that *receives* the funds go in `eligibility.funder_conditions: [{text, quotes}]`, never in
  `mandatory`: they are shown to students but do not decide their result.
* If two official statements contradict each other, record both: `conflicts: [{field_path, summary, quotes: [first, second]}]`
  (`url` can select the page each quote comes from). The record is forced to `pending` + `draft` until a person resolves it.
* Unknown stays unknown: use `{type: unknown, reason: ..., quotes: [...]}` for a condition the source leaves to a
  local administrator, and `kind: unspecified` amounts. Do not guess a cycle: use `cycle_key: unspecified`.

Format (this example is INVENTED to show the shape; it is not a real program):

```yaml
source_id: example_source            # must exist in sources.yaml
records:
  - key: example-channel             # stable native key -> id "<provider>:example_channel"
    title: Example Education Funding Channel
    opportunity_type: funding_channel
    summary: Funding is administered by the local education office.
    official_url: https://example.org/channel
    application:
      route_type: contact_administrator
      contact_url: https://example.org/contact
      quotes: ["Contact your local education office to apply."]
    cycles:
      - cycle_key: unspecified
        label_raw: not stated
        deadlines:
          - {kind: local_administrator, raw_text: set locally, quotes: ["Deadlines are set locally."]}
        amount: {kind: unspecified, raw_text: not stated}
        eligibility:
          mandatory:
            - {type: unknown, reason: Eligibility is decided by the local office, quotes: ["Eligibility is decided locally."]}
```
