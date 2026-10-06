# Indigenous Student Funding Navigator

**A funding board for First Nations, Inuit and Métis students in Canada**

*Build Session 1 submission*

Indigenous Student Funding Navigator helps students move from “I need funding” to “these are the opportunities worth pursuing, and this is how I apply.” A short conversation will connect them with scholarships, bursaries and education funding channels, explain the fit and link to official sources.

The project is designed for First Nations, Inuit and Métis students across all provinces and territories, from high school through post-secondary education.

## 1. Problem evidence

A student searching for funding faces several different systems. [PSSSP funding](https://www.sac-isc.gc.ca/eng/1100100033682/1531933580211) is administered through First Nations or designated organizations. [Inuit funding](https://www.sac-isc.gc.ca/eng/1578850688146/1578850715764) is delivered regionally through land-claim organizations, while [Métis Nation funding](https://www.sac-isc.gc.ca/eng/1578855031863/1578855057804) follows participating Métis governments' processes. Institutional and private awards add further application routes.

Students must work out which rules apply to their registration or beneficiary status, home community, location, institution and program, then track the dates and documents for each application.

Existing tools help with parts of this journey. The [ISC Indigenous Bursaries Search Tool](https://www.sac-isc.gc.ca/eng/1351185180120/1351685455328?wbdisable=true) provides national discovery, but asks students to confirm information with each funding organization. [Indspire](https://indspire.ca/apply-now/) simplifies applications across most of its own awards. Students looking across these channels still have to connect and verify the information.

The navigator will bring that work into one experience. Each result will explain why it may fit, what needs checking and what to do next, alongside the deadline, published value, required documents and source verification date. Awards sharing one application will be grouped. Where a rule is unclear, the navigator will ask a follow-up question or direct the student to the provider.

## 2. Data evidence

The initial October 5 audit counted 538 ISC directory entries. It found a 2020 deadline, institutional award collections listed alongside individual awards, and both Ryerson University and Toronto Metropolitan University used as institution names. These observations make the directory a useful discovery index, while showing why its entries need further checking.

The prototype will verify opportunities against public Indspire, First Nation, Inuit organization, Métis government, institutional and private-provider pages. Regional sources are important because national directory labels do not capture every local eligibility rule.

Each record will store the provider, official URL, application cycle, deadline, value, eligibility conditions and short supporting excerpts. Records will distinguish individual awards from funding channels and connect opportunities sharing an application.

Structured rules will handle clear conditions. The LLM will help extract criteria from free text and explain matches using the retained evidence. Source terms will be checked before ingestion. The prototype will request no identity numbers or documents and will be designed to keep profiles within the session.

## 3. What we are taking into Build Session 2

We are bringing an initial directory audit, identified official data sources and a matching workflow. On October 7, the goal is to turn them into:

- **An initial dataset:** reproduce the ISC snapshot and ingest a first set of official provider pages into a common schema. Output: `data/awards.jsonl`.
- **A matching endpoint:** apply structured eligibility rules, return supporting evidence and flag missing information.
- **A freshness report:** check application cycles and deadlines, identify unresolved records and record the sources used.

Build Session 3 will add the chat and results view and test matching on manually labelled opportunity–profile pairs. The October 13 demo will show a supported match, a clarification case and a shared application. Student or advisor feedback, where available, will help assess whether the results make the next action clear.

**Team:** Yuzheng Shi
