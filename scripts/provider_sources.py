"""Add one start-page-only source per distinct provider link found in the ISC directory records.

The provider pages are fetched ONLY to check and upgrade those records (robots.txt honoured, one page each).
students.ubc.ca is skipped: it answered HTTP 403 to the automated client and is not retried.
"""

import json
import pathlib
import urllib.parse

from navigator.core.ids import slugify

root = pathlib.Path(".")
records = [
    json.loads(line)
    for line in (root / "data/candidates/awards.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
isc = [
    r
    for r in records
    if any("sac-isc.gc.ca" in (s.get("url") or "") for s in r["source_refs"]) and r["opportunity_type"] == "award"
]
provider_override = {"www.unbc.ca": ("unbc", "University of Northern British Columbia")}
skip_hosts = {"students.ubc.ca"}
groups: dict[str, dict] = {}
for record in isc:
    link = record["application"].get("url") or ""
    if not link:
        continue
    parts = urllib.parse.urlsplit(link)
    host = parts.netloc.lower()
    if host in skip_hosts:
        continue
    url = urllib.parse.urlunsplit(
        ("https", parts.netloc, parts.path or "/", parts.query, "")
    )  # these sites are https; fragments are dropped
    group = groups.setdefault(
        url,
        {
            "records": [],
            "host": host,
            "path": parts.path or "/",
            "provider": (record["provider"]["id"], record["provider"]["name"]),
        },
    )
    group["records"].append({"id": record["id"], "title": record["title"]})
providers_path = root / "sources.providers.yaml"
text = providers_path.read_text(encoding="utf-8") if providers_path.exists() else "sources:\n"
links, blocks = {}, []
for url, group in groups.items():
    source_id = "prov_" + slugify(group["host"].replace("www.", "") + group["path"], 52)
    if f"source_id: {source_id}\n" in text:
        continue
    pid, pname = provider_override.get(group["host"], group["provider"])
    prefix = group["path"] if group["host"] == "indspirefunding.ca" else "/"
    blocks.append(
        f'  - source_id: {source_id}\n    name: "Provider page for {len(group["records"])} ISC directory record(s)"\n    url: "{url}"\n'
        f'    provider: {{id: {pid}, name: "{pname}"}}\n    role: award_listing\n    parser: curated_awards\n    language: en\n'
        f'    allowed_domains: ["{group["host"]}"]\n    allowed_paths: ["{prefix}"]\n    access_status: unreviewed\n    max_pages: 1\n'
        f'    notes: "Fetched only to verify/upgrade ISC directory record(s): {"; ".join(r["title"] for r in group["records"])[:200].replace(chr(34), chr(39))}"\n'
    )
    links[source_id] = {"url": url, "records": group["records"]}
if blocks:
    if not text.endswith("\n"):
        text += "\n"
    text += "".join(blocks)
    providers_path.write_text(text, encoding="utf-8", newline="\n")
existing = {}
links_path = root / "data/discovery/provider_links.json"
if links_path.exists():
    existing = json.loads(links_path.read_text(encoding="utf-8"))
existing.update(links)
links_path.write_text(
    json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
)
print(
    f"provider sources added: {len(links)} (covering {sum(len(v['records']) for v in links.values())} records); skipped hosts: {sorted(skip_hosts)}"
)
print("records without a link:", [r["title"] for r in isc if not r["application"].get("url")])
