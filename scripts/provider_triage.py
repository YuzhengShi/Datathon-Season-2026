"""Triage of fetched provider pages: does the page really mention the award, and what does it say about dates and money?

Output is ASCII-escaped on purpose (quotes written from it must match the stored text exactly).
"""

import json
import pathlib
import re

root = pathlib.Path(".")
links = json.loads((root / "data/discovery/provider_links.json").read_text(encoding="utf-8"))
index = json.loads((root / "data/discovery/fetch_index.json").read_text(encoding="utf-8"))
by_source = {}
for url, entry in index["entries"].items():
    by_source.setdefault(entry["source_id"], []).append((url, entry))
failures = {}
for url, info in index.get("failures", {}).items():
    failures[url] = info.get("reason")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


DATE = re.compile(
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{4}-\d{2}-\d{2}",
    re.I,
)
KEY = re.compile(r"deadline|due |closes?\b|apply by|applications? (?:are|is|must|will)|submit", re.I)


def esc(text, limit=170):
    return text[:limit].encode("ascii", "backslashreplace").decode("ascii")


ok = 0
for source_id, info in sorted(links.items()):
    entries = by_source.get(source_id, [])
    print(f"=== {source_id}  {esc(info['url'], 90)}")
    if not entries:
        print(
            f"    NOT FETCHED: {esc(str(failures.get(info['url'], failures.get(info['url'].rstrip('/'), 'no entry'))), 80)}"
        )
        continue
    url, entry = entries[0]
    text = pathlib.Path("data", entry["text_path"]).read_text(encoding="utf-8")
    flat = norm(text)
    ok += 1
    print(f"    http={entry['http_status']} final={esc(entry['final_url'], 80)} text={len(text)} chars")
    for record in info["records"]:
        print(f"    award on page: {norm(record['title']) in flat!s:<5} {esc(record['title'], 70)}")
    hits = [p.replace("\n", " ") for p in text.split("\n\n") if KEY.search(p) and DATE.search(p)]
    for p in hits[:2]:
        print("    date-sentence: " + esc(p, 230))
    money = sorted(set(re.findall(r"\$\s?\d[\d,]*", text)))[:6]
    print("    amounts on page:", money)
print(f"fetched provider pages: {ok}/{len(links)}")
