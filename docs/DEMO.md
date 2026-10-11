# Demo guide

Everything runs on one laptop: `.\scripts\start_app.ps1` (or `python -m navigator.cli serve --mode live`), then open <http://127.0.0.1:8000/>. If the screen is small,
zoom the browser to 110-125%. `-Port 8080` if Windows refuses the port. Everything works offline except AI search, which needs `.env` with
`LLM_ENABLED=true`, a key and internet access to the model provider (see [LLM_PROVIDERS.md](LLM_PROVIDERS.md)); without it the page says so and the rest is unaffected.

## Sixty seconds (video)

1. **Why (15 s).** Funding for Indigenous students is spread over dozens of sites with different rules and dates, and some of what is listed is years old.
   Nothing shows where support is, or how much of it has been checked.
2. **What (30 s).** Open *Statistics*: 529 records, 13 of 13 provinces and territories covered. The map has north at the top and every region carries its count.
   Click Manitoba and every chart narrows to it. Switch to *Tiles* to read the small provinces. Then *Ask about the data* or the AI search:
   "I'm a Métis student in BC looking for training support" returns source-linked records.
3. **How (15 s).** Open one record read on a provider's own page and one federal-directory entry: each fact has the quote it came from and the date it was checked;
   rules are deterministic; the model only chooses among fixed tools and can only return records that exist.

## Three minutes

1. **The problem (20 s).** As above.
2. **The map (50 s).** *Statistics*. Read the first row: 529 records, 13 / 13 regions, 38 across Canada, 484 for one region. On the map, point out the colour
   classes (cut from the data, so one big province does not hide the rest), hover Manitoba for its card, then show the ranking of all 13 regions: the green part of
   a bar is read on a provider's own page, the tan part comes only from the federal directory. Say it plainly: the count is what the directory and the providers
   list, not what exists.
3. **One region in depth (40 s).** Click Ontario (88 records; one Métis bursary the directory lists about forty times is counted once). The card shows its
   communities, how many records have a listed figure, its main providers and how old the sources are. *Explore these records* opens them as cards.
4. **One record in depth (30 s).** Open a federal-directory entry: "As listed in the federal directory", the Government of Canada statement, the source sentences,
   no deadline. Then open a Vancouver Island University or SFU record: read on the provider's page, with the quotes behind each amount and date.
5. **Ask in your own words (20 s).** AI search, as above. Point out that each result is a record that exists in the dataset.
6. **Honesty (20 s).** The *First Citizens Fund* bursary is in our data as archived (its provider paused it, so students never see it). The site does not predict who
   wins; a person has not reviewed the records yet, and the site says so.

The Session 2 questionnaire app is still at `/app/` (answer a few questions, then browse). For an SFU student it lists 501 of the 529 records, most with
eligibility the directory does not state, so it is not the demo path.

## Questions you will get

* **Why is Manitoba bigger than British Columbia?** The federal directory lists 130 Manitoba entries. British Columbia has 95 records: 36 read on provider pages (Vancouver Island University, SFU
  and others) and 59 from the directory. The map shows what is listed, not what exists.
* **Why are most records without a deadline?** 486 of the 529 are federal-directory entries, and the directory states no deadline or application steps. The site
  says so on each card and sends the student to the provider.
* **How old is the data?** Of all records, the source page was last changed in 2015 or earlier for 235, in 2016–2019 for 3, in 2020–2022 for 207 and in 2023 or
  later for 44; 40 state no date. The *Statistics* page shows this chart.
* **Is the data right?** Every quote on a detail page is checked automatically against the stored page. A person has *not* reviewed the records yet.
* **How does the community filter work?** Community comes from the directory's own "Indigenous group" column (155 of 540 entries name one or two
  groups). It filters and counts; it never decides eligibility.
* **What about UBC?** Its pages refuse automated access (HTTP 403). We did not work around that; we are asking UBC for permission, and the system can import a page
  that a person saves in a browser.
* **Privacy?** No name, no status number, no documents; no cookies or tracking. With AI search on, the typed question and the records the tools return go to the model
  provider you configure.
* **Who pays / who runs it?** Free and non-commercial; no ads.

## Numbers you can quote (from the dataset, 11 October 2026)

529 published records: 43 read on a provider's own page (25 Vancouver Island University awards, 8 SFU, 3 official program pages, 1 MNBC, 6 others) and 486 from the
federal directory. Every region has records: Manitoba 130, British Columbia 95, Ontario 88, Alberta 62, Saskatchewan 50, Northwest Territories 21, Nova Scotia 15,
New Brunswick 7, Yukon 6, Nunavut 3, Quebec 3, Newfoundland and Labrador 2, Prince Edward Island 2; 38 apply across Canada and 7 state no region. 257 show one
amount (8 more a range), 28 show a deadline or a yearly rule, 1,781 quotes support the records.
