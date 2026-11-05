"""Build the markdown verification table (sources.md) from the verification JSON files."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = []
for f in ("verification.json", "verification_extra.json"):
    rows += json.loads((HERE / f).read_text())
yd = json.loads((HERE / "verification_yahoo_daily.json").read_text()) if (HERE / "verification_yahoo_daily.json").exists() else []
p3 = json.loads((HERE / "verification_pass3.json").read_text()) + json.loads((HERE / "verification_pass3b.json").read_text())

lines = ["| Source | HTTP | ms | first | latest | note |", "|---|---|---|---|---|---|"]
for r in rows:
    if r["name"].startswith("Yahoo ") and "(retry" not in r["name"]:
        continue                       # the first Yahoo pass was all 429 (browser UA): summarised in the text
    note = str(r.get("note", "")).replace("|", "/").replace("\n", " ")[:140]
    lines.append(f"| {r['name']} | {r.get('status')} | {r.get('latency_ms', '')} | {r.get('first_date', '') or ''} | {r.get('latest_date', '') or ''} | {note} |")
for r in yd:
    lines.append(f"| Yahoo {r['symbol']} daily (period1/period2) | {r.get('status')} | {r.get('latency_ms', '')} | {r.get('first_date', '')} | {r.get('latest_date', '')} | rows {r.get('n_rows', '')}, median gap {r.get('median_gap_days', '')} d, last {r.get('latest_value', '')} |")
for r in p3:
    lines.append(f"| {r['name']} | {r.get('status')} | {r.get('latency_ms', '')} | | | {str(r.get('hits') or r.get('rows') or r.get('names') or r.get('note') or '')[:140].replace('|', '/')} |")
(HERE / "sources_verified.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(lines) - 2, "rows ->", HERE / "sources_verified.md")
