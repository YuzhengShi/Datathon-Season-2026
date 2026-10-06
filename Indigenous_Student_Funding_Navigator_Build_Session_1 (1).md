# Indigenous Student Funding Navigator

**A funding board for First Nations, Inuit and Métis students in Canada**

*Build Session 1 submission*

Indigenous Student Funding Navigator helps First Nations, Inuit and Métis high-school and post-secondary students find scholarships, bursaries and education funding channels. A short conversation produces a list of relevant opportunities, with eligibility evidence, application dates and official links.

Each recommendation explains which published conditions the student appears to meet, what remains unresolved and where to apply or ask for clarification. The prototype will use structured matching rules and an LLM to extract and explain criteria from source text. Funding decisions remain with the funder.

## 1. Problem evidence

### Funding is available through different systems

Indigenous student funding is distinctions-based: First Nations, Inuit and Métis programs have different eligibility requirements and delivery organizations. Students may also qualify for institutional, corporate and foundation awards.

| Students or opportunity type | Main channel | Where to confirm eligibility and deadlines |
|---|---|---|
| First Nations students registered under the Indian Act | Post-Secondary Student Support Program (PSSSP) | First Nations or designated organizations administer selection and allocations and may publish local application rules. Students should contact their First Nation, designated organization or ISC regional office. [ISC program page](https://www.sac-isc.gc.ca/eng/1100100033682/1531933580211) |
| Inuit students | Inuit Post-Secondary Education Strategy | The strategy supports land-claim beneficiaries and is delivered regionally. ISC directs applicants to ITK or their respective land-claim organization for application information and deadlines. [ISC program page](https://www.sac-isc.gc.ca/eng/1578850688146/1578850715764) |
| Métis Nation students | Métis Nation Post-Secondary Education Strategy | Participating Métis governments determine how funding is distributed. Students must confirm local criteria and application dates with the appropriate delivery organization. [ISC program page](https://www.sac-isc.gc.ca/eng/1578855031863/1578855057804) |
| Scholarships and bursaries | Indspire and institutional, corporate and foundation programs | Indspire uses one application for most of its awards; other providers have their own application processes. [Indspire application page](https://indspire.ca/apply-now/) |

Students must determine which conditions apply to their home Nation, beneficiary or citizenship status, residence, institution, program and study level. Location labels alone are insufficient: IRC's Inuit education funding page, for example, covers Inuvialuit beneficiaries living throughout Canada and sets its own application requirements. [IRC program page](https://irc.inuvialuit.com/IPSES/)

### A directory or a search result does not complete that task

The [ISC Indigenous Bursaries Search Tool](https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328?wbdisable=true) provides a useful national starting point. It also carries an update notice asking students to confirm information with each funding organization. This establishes a concrete verification gap: finding a directory entry does not establish that its deadline or criteria are current.

Search and LLMs with browsing can help students discover opportunities. The navigator adds maintained application-cycle information, source evidence, verification dates and unresolved conditions. Its value will be tested against simpler filtering approaches.

The initial research establishes fragmentation and data-quality issues. The hypothesis to validate is that resolving them helps students find relevant opportunities faster and avoid unsuitable applications. Planned student or advisor walkthroughs will examine where applicants get stuck and whether the explanations help; user benefits have not yet been measured.

### Existing alternatives and the proposed contribution

| Alternative | Existing role | What this project will add or test |
|---|---|---|
| ISC Indigenous Bursaries Search Tool | National discovery through structured filters and award detail pages | Verification against provider pages, criteria beyond directory labels, explicit uncertainty and links between related records |
| [Indspire Building Brighter Futures](https://indspire.ca/apply-now/) | One application for most Indspire awards, with a few exceptions | Navigation across other funding providers while preserving Indspire's shared application process |
| Institutional award pages and portals | Information and applications for the institution's own awards | A consistent view across institutions and other funding channels |
| General scholarship aggregators | Additional discovery sources and potential comparison baselines | Their coverage and matching have not yet been benchmarked; the project does not claim superiority over them |

### Scope and the first useful version

The intended scope covers all provinces and territories and First Nations, Inuit and Métis students from high school through post-secondary education. The prototype will report the regions, groups and study levels covered by its verified records.

High-school students will see awards for their current level and funding routes for their transition into further study. Post-secondary students will see opportunities for their institution, program and enrolment circumstances. Results will distinguish current eligibility from future entry conditions.

The first version will accept a short description, ask necessary follow-up questions and show **individual awards** separately from **funding channels or shared application programs**. Each result will include:

- The opportunity, provider and official application or contact link.
- A plain-language explanation with short source excerpts supporting the match.
- Unresolved conditions and the next action needed to clarify them.
- The published amount or range, deadline and required documents, where available.
- The application year or cycle and the date the source was last checked.

Results will distinguish supported conditions, unmet conditions, missing student information and rules requiring provider clarification. Unresolved requirements prevent a “meets published criteria” label. Eligibility does not guarantee funding.

Within each result type, supported matches will precede unresolved possibilities, with current deadlines helping prioritize action. Awards sharing an application will be grouped. Application completion or submission, user accounts and identity-document storage are out of scope.

## 2. Data evidence

### Sources and access

| ID | Source | Coverage and access | Role in the prototype |
|---|---|---|---|
| S1 | ISC Indigenous Bursaries Search Tool | National directory; public list and award detail pages | Discover providers and candidate opportunities; directory entries are not treated as verified applications |
| S2 | [Indspire](https://indspire.ca/apply-now/) and its linked [award listing](https://indspirefunding.ca/) | Public program, award and criteria pages | Verify Indspire rules and represent awards linked to a shared application |
| S3 | PSSSP and First Nation education offices | Public national guidance and local pages; formats and availability vary | Identify the responsible organization and verify its local funding process |
| S4 | Inuit strategy, ITK and land-claim organizations | Public guidance, regional pages and application packages | Represent regional eligibility, deadlines and application routes |
| S5 | Métis Nation strategy and delivery governments | Public national and local pages | Verify the relevant government's criteria and funding process |
| S6 | Institutional award pages and portals | Public pages and accessible award records | Verify institutional awards; follow the institution pointers found in S1 |
| S7 | Corporate and foundation providers | Official public award pages | Verify opportunities discovered through S1 or other indexes |

S3–S5 require records for individual delivery organizations. Where local rules are unavailable, eligibility will remain unresolved.

### Initial audit of the seed directory

The preliminary manual audit recorded the following observations on October 5, 2026. These are counts of directory records, not a count of unique, current application opportunities.

| Observation | Initial finding | Implication |
|---|---|---|
| Directory rows counted | 538 | Useful discovery scale; the count must be reproduced from a recorded query and complete retrieval |
| Institution pointer entries | 11 entries beginning “All -” and pointing to institutional award collections | A pointer needs further discovery; it is not an individual award |
| Métis Student Bursary Program records | 41 related rows: 40 institution-specific rows and one program-level row | Preserve institution-specific conditions and identify shared program or application relationships |
| Explicit Inuit tags | 10 rows tagged for Inuit, alone or with other groups | Limited explicit tagging; this does not count all opportunities open to Inuit students |
| Historical deadline example | A 2020 deadline for the Aboriginal Full Circle Summer Internship Program | Verify the current cycle with the provider; do not assume the program is still open or has ended |
| Institution naming | Both Ryerson University and Toronto Metropolitan University appear | Normalize institution identity; inspect related records before calling them duplicates |

Build Session 2 will reproduce the audit with retrieval dates, query parameters and an entry manifest, retaining permitted source evidence. Reporting will distinguish directory rows, distinct programs and verified current opportunities; these counts do not establish complete national coverage.

### Matching signal and data model

Provider text adds conditions beyond S1's location, institution, field-of-study and Indigenous-group labels: registration or beneficiary status, Métis citizenship, home Nation, study level, financial need and enrolment status. Extraction must preserve qualifiers and distinguish alternative conditions from cumulative requirements.

The schema will include record type, provider, official URL, related program or application ID, application cycle, value, dates, required documents, normalized conditions, supporting text and verification status. Missing values remain unknown. Recurring dates retain their original wording and require current-cycle confirmation.

Structured rules will match verified fields. The LLM will propose criteria, interpret student answers and explain results from retained evidence. Extracted rules will be checked before driving a supported match. Missing or conflicting requirements require clarification; the system will not infer Indigenous identity.

### Source use and student privacy

Source use requires checking applicable terms. The [Canada.ca terms](https://www.canada.ca/en/transparency/terms.html) describe conditions for non-commercial reproduction; [ISED guidance](https://ised-isde.canada.ca/site/ised/en/copyright-written-permission) distinguishes unchanged reproduction from adaptation and commercial distribution. Educational use alone does not settle every proposed use.

`docs/data-terms.md` will record each publisher's terms, access method and permitted use of facts and excerpts. Records will retain source titles, providers and official links. The prototype will identify itself as independent of government and funders and avoid bulk republication of descriptions. Sources unsuitable for ingestion or quotation will remain discovery links. Use beyond the datathon requires fresh review.

The prototype will request only matching-relevant answers, allow skipped questions and keep profiles within the session. It will not request identity numbers or documents. Before using real profiles, logs, analytics and LLM-provider retention settings must be checked; provider retention must be disclosed. Evaluation will use synthetic profiles, and feedback will exclude identity details.

## 3. Build plan and evaluation

### Milestones

| Session | Work | Deliverable |
|---|---|---|
| Build Session 2 — Wednesday, October 7 | Reproduce the S1 audit; ingest an initial set of provider records from S2–S7; normalize identities and application relationships; check current dates and source terms | `data/awards.jsonl`, source register and audit/freshness report |
| Build Session 2 — Wednesday, October 7 | Implement structured matching, evidence retrieval and explicit handling of missing or ambiguous conditions | Matching endpoint with traceable reasons |
| Build Session 3 — Friday, October 9 | Build chat intake and results; evaluate matching and explanations; carry out student or advisor walkthroughs if participants are available | Working prototype, evaluation table and any available feedback |
| Demo Day — Tuesday, October 13 | Demonstrate a supported match, a clarification case and a shared application; state measured coverage and remaining gaps | Live demo with evidence and evaluation results |

### How the prototype will be evaluated

The initial target is 20 verified award or funding-channel records and 12 synthetic profiles: 240 labelled pairs covering all three Indigenous groups and both study levels. Cases will include matches, exclusions, unknown requirements and application-cycle issues. Labels will be derived manually from retained source text, with ambiguities recorded.

| Question | Measure |
|---|---|
| Are supported matches correct? | Precision of “meets published criteria” results; separately count cases where an unmet or unresolved required condition was overlooked |
| Are relevant opportunities found? | Recall within the labelled candidate set, reported separately from national coverage |
| Do explanations follow the evidence? | Manual check that each eligibility statement is supported by its cited text and preserves qualifiers |
| Is uncertainty handled correctly? | Correct separation of missing student information from missing or ambiguous provider rules |
| Is application information current? | Proportion of records with a provider check and identified cycle; unresolved or historical deadlines remain visible in the report |
| Does free-text extraction add value? | Compare the full matcher with structured-field filtering alone on the same candidate set |

Results will include counts and breakdowns by Indigenous group and study level. This small test set provides an initial diagnostic. Walkthroughs will separately examine whether students understand recommendations and can identify their next action.

## Team

Yuzheng Shi
