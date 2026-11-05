#!/usr/bin/env python
"""
Terminal data dictionary generator — renders ``docs/TERMINAL_DATA_DICTIONARY.md`` from data-service's ``dataset_catalog``.

    python scripts/terminal_data_dictionary.py                 # write docs/TERMINAL_DATA_DICTIONARY.md
    python scripts/terminal_data_dictionary.py --check         # exit 1 when the committed doc is out of date
    python scripts/terminal_data_dictionary.py --stdout        # print the rendered markdown
    python scripts/terminal_data_dictionary.py --selftest      # the validator's negative controls (no files written)

Inputs (read-only; the gold ``scripts/gold_data_dictionary.py`` pattern lifted to the whole terminal, PLAN §0.12 / 1.6):
  * ``services/data-service/data_health/catalog.py`` — ``build_rows()``: one row per dataset the terminal shows (publisher,
    publication time IST, ``expected_by``, cadence, lag budget, ingest job, how freshness is read, dictionary anchor,
    verdict, badge). This is the catalog that gates rendering: no row, no panel.
  * ``services/data-service/fo_iv/catalog_seed.py`` and ``services/data-service/index_drivers/catalog_seed.py`` — the
    per-metric registries (series id, table.column, badge, definition, precedent). Rendered as the "metric registries".
  * ``shared/http_client.py`` — the host allowlist (read with ``ast``, never imported), rendered so the dictionary says
    which publishers the stack may contact at all.
  * ``docs/NSE_DATA_DICTIONARY.md`` / ``docs/GOLD_DATA_DICTIONARY.md`` — every ``dictionary_anchor`` that points into them
    must resolve (``<a id="…">`` in the NSE dictionary, ``### <id> ·`` in the gold one); a dangling anchor refuses the build.

Rules enforced on the catalog before anything is rendered (each a one-line REFUSED on stderr, exit 1):
  no ``signal`` badge anywhere (PLAN §0.1: none exists), verdict and badge from the fixed vocabularies, unique ids, no
  forbidden host in a publisher string (PLAN §0.6), every anchor resolvable. The output is a pure function of the input
  bytes: no wall-clock time, no environment, sorted wherever a set is walked. ``scripts/tests`` runs ``--check``.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_SERVICE = ROOT / "services" / "data-service"
OUT_PATH = ROOT / "docs" / "TERMINAL_DATA_DICTIONARY.md"
NSE_DICT = ROOT / "docs" / "NSE_DATA_DICTIONARY.md"
GOLD_DICT = ROOT / "docs" / "GOLD_DATA_DICTIONARY.md"
HTTP_CLIENT = ROOT / "shared" / "http_client.py"

VERDICTS: tuple[str, ...] = ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
BADGES: tuple[str, ...] = ("context", "arithmetic", "heuristic")          # `signal` is refused: none exists (PLAN §0.1)
STATES = "live | fresh | amber | red | gap"
VERDICT_MEANING: dict[str, str] = {
    "PUBLISH-CORE": "ingested (or computed) and shown on a page's primary panels",
    "PUBLISH-CONTEXT": "ingested and shown inside its section or a details drawer, always with the `context` badge",
    "LINK-ONLY": "a labelled link to the publisher; nothing is fetched or stored by the stack",
    "DO-NOT-PUBLISH": "not fetched, not shown (dead, blocked by terms, or shown to be noise)",
}
BADGE_MEANING: dict[str, str] = {
    "context": "a description or a measured relationship that PASSED as a description, never as a forecast; rendered in the neutral token",
    "arithmetic": "an identity, a model convention or an exchange rule that makes no claim about the future (IV, Greeks, points attribution, SPAN)",
    "heuristic": "a house rule without evidence, shown with its measured error where one exists (the 12 % margin estimate: 4.8× too high)",
}
# Hosts the stack must never fetch (PLAN §0.6; enforced on the code by tests/test_hosts_allowlist_terminal.py and
# tests/arch/test_hosts_allowlist_shared.py). A catalog row whose publisher names one is a dictionary error.
FORBIDDEN_HOSTS: tuple[str, ...] = ("mcxindia.com", "www.cmegroup.com", "kitco.com", "investing.com", "stooq", "goldprice.org", "prices.lbma.org.uk")
REQUIRED_KEYS: tuple[str, ...] = ("id", "label", "pages", "publisher", "cadence", "max_age_sessions", "freshness_kind", "verdict", "badge")

_NSE_ANCHOR_RE = re.compile(r'<a id="([^"]+)"></a>')
_GOLD_ANCHOR_RE = re.compile(r"^### ([A-Z]\d+) · ", re.MULTILINE)


# ─────────────────────────────────────────── loading ───────────────────────────────────────────

def _import_rows(module: str) -> tuple[str, list[dict[str, Any]]]:
    """``build_rows()`` of one data-service package module; a missing or crashing module is a status, never a crash."""
    if str(DATA_SERVICE) not in sys.path:
        sys.path.insert(0, str(DATA_SERVICE))
    try:
        mod = importlib.import_module(module)
        rows = [dict(r) for r in mod.build_rows()]
    except Exception as exc:  # noqa: BLE001 - any failure in another builder's module is reported, never propagated
        return f"absent or not loadable ({type(exc).__name__}: {exc})", []
    return f"present ({len(rows)} rows)", rows


def load_catalog() -> tuple[str, list[dict[str, Any]]]:
    return _import_rows("data_health.catalog")


def load_registries() -> dict[str, tuple[str, list[dict[str, Any]]]]:
    return {"fo_iv": _import_rows("fo_iv.catalog_seed"), "index_drivers": _import_rows("index_drivers.catalog_seed")}


def allowed_hosts(path: Path = HTTP_CLIENT) -> dict[str, list[str]]:
    """The ``*_HOSTS`` frozensets of shared/http_client.py, read with ``ast`` (never imported). ``{}`` when absent."""
    if not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: dict[str, list[str]] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target is None or value is None or not target.endswith("_HOSTS") or target in ("ALLOWED_HOSTS", "INTERNAL_HOSTS"):
            continue
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset" and value.args:
            try:
                literal = ast.literal_eval(value.args[0])
            except (ValueError, SyntaxError):
                continue
            out[target] = sorted(str(h) for h in literal)
    return out


def anchors_in(nse_path: Path = NSE_DICT, gold_path: Path = GOLD_DICT) -> dict[str, set[str]]:
    """The anchor ids each dictionary offers (``<a id>`` in the NSE one, ``### <id> ·`` entries in the gold one)."""
    out: dict[str, set[str]] = {"docs/NSE_DATA_DICTIONARY.md": set(), "docs/GOLD_DATA_DICTIONARY.md": set()}
    if nse_path.exists():
        out["docs/NSE_DATA_DICTIONARY.md"] = set(_NSE_ANCHOR_RE.findall(nse_path.read_text(encoding="utf-8")))
    if gold_path.exists():
        out["docs/GOLD_DATA_DICTIONARY.md"] = set(_GOLD_ANCHOR_RE.findall(gold_path.read_text(encoding="utf-8")))
    return out


# ─────────────────────────────────────────── validation ───────────────────────────────────────────

def validate_rows(rows: list[dict[str, Any]], anchors: dict[str, set[str]]) -> list[str]:
    """Every defect in the catalog rows, one line each (empty = the rows may be rendered). Pure; used by ``--selftest``."""
    defects: list[str] = []
    seen: set[str] = set()
    own = "docs/TERMINAL_DATA_DICTIONARY.md"
    for row in rows:
        rid = str(row.get("id", "?"))
        for key in REQUIRED_KEYS:
            if key not in row or row[key] in (None, ""):
                defects.append(f"{rid}: missing {key}")
        if rid in seen:
            defects.append(f"{rid}: duplicate id")
        seen.add(rid)
        if row.get("badge") == "signal":
            defects.append(f"{rid}: badge `signal` — no pre-registered study has passed as a forecast anywhere in the terminal (PLAN §0.1)")
        elif row.get("badge") not in BADGES:
            defects.append(f"{rid}: unknown badge {row.get('badge')!r}")
        if row.get("verdict") not in VERDICTS:
            defects.append(f"{rid}: unknown verdict {row.get('verdict')!r}")
        publisher = str(row.get("publisher", "")).lower()
        bad = [h for h in FORBIDDEN_HOSTS if h in publisher]
        if bad:
            defects.append(f"{rid}: publisher names a forbidden host {bad} (PLAN §0.6)")
        anchor = str(row.get("dictionary_anchor") or "")
        if anchor:
            doc, _, frag = anchor.partition("#")
            if doc == own:
                if frag != rid:
                    defects.append(f"{rid}: dictionary_anchor {anchor!r} must be its own id in this dictionary")
            elif doc in anchors:
                if frag not in anchors[doc]:
                    defects.append(f"{rid}: dictionary_anchor {anchor!r} does not resolve (no anchor {frag!r} in {doc})")
            else:
                defects.append(f"{rid}: dictionary_anchor {anchor!r} points at an unknown document")
    return defects


def validate_registry(name: str, rows: list[dict[str, Any]]) -> list[str]:
    defects: list[str] = []
    seen: set[str] = set()
    for row in rows:
        sid = str(row.get("series_id", "?"))
        if sid in seen:
            defects.append(f"{name}: duplicate series_id {sid}")
        seen.add(sid)
        if row.get("badge") == "signal":
            defects.append(f"{name}: {sid} carries `signal` (PLAN §0.1: none exists)")
        elif row.get("badge") not in BADGES:
            defects.append(f"{name}: {sid} unknown badge {row.get('badge')!r}")
        if row.get("verdict") not in VERDICTS:
            defects.append(f"{name}: {sid} unknown verdict {row.get('verdict')!r}")
    return defects


# ─────────────────────────────────────────── rendering ───────────────────────────────────────────

def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _anchor_link(anchor: str) -> str:
    doc, _, frag = anchor.partition("#")
    return f"[{doc.split('/')[-1]}#{frag}](../{doc}#{frag})" if doc.startswith("docs/") else f"`{anchor}`"


def _freshness(row: dict[str, Any]) -> str:
    kind = row.get("freshness_kind")
    if kind == "table":
        where = f" where `{row['freshness_where']}`" if row.get("freshness_where") else ""
        return f"`MAX({row.get('freshness_column')})` of `{row.get('table_name')}`{where}"
    if kind == "archive":
        return f"dated files under `data/nse_archive/{row.get('table_name')}/`"
    if kind == "file":
        return f"`{row.get('table_name')}` ({row.get('freshness_column')})"
    return "composed by ui-api from telemetry / its own stores (data-service reports `unknown`)"


def _row_block(row: dict[str, Any]) -> list[str]:
    rid = str(row["id"])
    out = [f'<a id="{rid}"></a>', f"### `{rid}` · {row['label']}", ""]
    out.append(f"- **Pages:** {', '.join(p for p in str(row['pages']).split(',') if p)} · **Publisher:** {row['publisher']}")
    expected = f"{row.get('expected_by')} IST" if row.get("expected_by") else "no deadline"
    offset = int(row.get("expected_offset_days") or 0)
    if offset:
        expected += f" on the trading day {offset} after the session it describes"
    unit = "sessions" if row.get("cadence") in ("daily", "session") else "days"
    out.append(f"- **Published (IST):** {_cell(row.get('publish_time_ist'))} · **Expected stored by:** {expected} · "
               f"**Cadence:** {row['cadence']} · **Amber after:** {row['max_age_sessions']} {unit}, red beyond that"
               + (" · **unrecoverable** (a missed capture is a gap row, never backfilled)" if row.get("unrecoverable") else ""))
    out.append(f"- **Ingest job:** {('`' + str(row['ingest_job']) + '`') if row.get('ingest_job') else 'none (read on request)'} · "
               f"**Freshness read from:** {_freshness(row)}")
    out.append(f"- **Verdict · badge:** {row['verdict']} · `{row['badge']}` · **Dictionary:** {_anchor_link(str(row.get('dictionary_anchor') or ''))}")
    if row.get("note"):
        out.append(f"- **Note:** {row['note']}")
    out.append("")
    return out


def _registry_table(name: str, status: str, rows: list[dict[str, Any]]) -> list[str]:
    title = {"fo_iv": "IV series (`fo_iv/catalog_seed.py`, served as `/db/fo-iv/catalog`)",
             "index_drivers": "Index-driver series (`index_drivers/catalog_seed.py`, served as `/db/index-drivers/catalog`)"}[name]
    out = [f"### {title}", "", f"Registry {status}. A panel renders a metric only if it has a row here with a PUBLISH verdict (no row, no panel)."]
    if not rows:
        return out + [""]
    counts = {b: sum(1 for r in rows if r.get("badge") == b) for b in BADGES}
    out += [" · ".join(f"`{b}` {n}" for b, n in counts.items()) + " · `signal` 0.", "",
            "| series | name | table.column | badge | definition | precedent | unit |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: str(r.get("series_id"))):
        out.append(f"| `{_cell(r.get('series_id'))}` | {_cell(r.get('name'))} | `{_cell(r.get('table'))}.{_cell(r.get('column'))}` | "
                   f"`{_cell(r.get('badge'))}` | {_cell(r.get('definition'))} | {_cell(r.get('precedent'))} | {_cell(r.get('unit'))} |")
    return out + [""]


def render(catalog_status: str, rows: list[dict[str, Any]], registries: dict[str, tuple[str, list[dict[str, Any]]]],
           hosts: dict[str, list[str]], anchors: dict[str, set[str]]) -> str:
    """Render the dictionary. Pure: the same inputs always give the same bytes. Raises ValueError on a catalog defect."""
    defects = validate_rows(rows, anchors)
    for name, (_, reg_rows) in sorted(registries.items()):
        defects += validate_registry(name, reg_rows)
    if defects:
        raise ValueError("; ".join(defects))

    verdict_counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    badge_counts = {b: sum(1 for r in rows if r["badge"] == b) for b in BADGES}
    pages: dict[str, list[str]] = {}
    jobs: dict[str, list[str]] = {}
    for r in rows:
        for p in str(r["pages"]).split(","):
            if p:
                pages.setdefault(p, []).append(str(r["id"]))
        if r.get("ingest_job"):
            jobs.setdefault(str(r["ingest_job"]), []).append(str(r["id"]))
    verified = sorted({str(r.get("verified_by") or "") for r in rows if r.get("verified_by")})

    out: list[str] = [
        "# Terminal data dictionary (`dataset_catalog`)",
        "",
        ("Every dataset the SuryaDhana terminal shows, as data-service's `dataset_catalog` declares it (Terminal v2 PLAN §0.12 / 1.4: "
         "the gold `gold_series_catalog` pattern terminal-wide). One row per dataset: who publishes it, when (IST, measured where "
         "R-DATA measured it), the IST time by which the terminal expects it stored (`expected_by`, trading-day aware), the lag "
         "budget before a row turns red, the job that ingests it, how freshness is read, the dictionary entry that describes the "
         "source, the verdict and the badge. `GET /api/data/health` (ui-api) and the SYS › DATA view evaluate exactly these rows "
         f"(state {STATES}); `scripts/tests` assert every ingest job and every page's data source has a row. "
         "Verified by: " + "; ".join(verified) + "."),
        "",
        ("**Generated** by `scripts/terminal_data_dictionary.py` from `services/data-service/data_health/catalog.py` — do not edit by "
         "hand; change the catalog and re-run. `--check` fails when this file is stale. Source entries (URLs, formats, traps) live in "
         "`docs/NSE_DATA_DICTIONARY.md` and `docs/GOLD_DATA_DICTIONARY.md`; this file is the per-dataset view the terminal itself uses."),
        "",
        f"Catalog seed: {catalog_status}. Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.",
        "",
        "## Verdicts and badges",
        "",
        "| Verdict | Meaning in the terminal | Datasets |",
        "|---|---|---|",
    ]
    for v in VERDICTS:
        out.append(f"| **{v}** | {VERDICT_MEANING[v]} | {verdict_counts[v]} |")
    out += [f"| **total** | | {len(rows)} |", "", "| Badge | Meaning | Datasets |", "|---|---|---|"]
    for b in BADGES:
        out.append(f"| `{b}` | {BADGE_MEANING[b]} | {badge_counts[b]} |")
    out += [
        ("| `signal` | only by a FINDINGS PASS row from a pre-registered study (PLAN before results, PIT data, \\|t\\| ≥ 2 full sample "
         "and both halves, after the cost floor) | **0 — none exists in F&O, gold or index attribution** |"),
        "",
        ("Context metrics render in the neutral token and are never coloured bullish or bearish; every verdict sentence ends "
         "\"describes, does not predict\"; no composite score; the same number appears once per page."),
        "",
        "## Pages → datasets",
        "",
        "| Page | Datasets |",
        "|---|---|",
    ]
    for p in sorted(pages):
        out.append(f"| {p} | " + ", ".join(f"[`{i}`](#{i})" for i in sorted(pages[p])) + " |")
    out += ["", "## Ingest jobs → datasets", "", "| Job | Datasets |", "|---|---|"]
    for j in sorted(jobs):
        out.append(f"| `{j}` | " + ", ".join(f"[`{i}`](#{i})" for i in sorted(jobs[j])) + " |")
    out += ["", "## Publishers the stack may contact (`shared/http_client.py` allowlist)", ""]
    if hosts:
        for name in sorted(hosts):
            out.append(f"- **{name}:** " + ", ".join(f"`{h}`" for h in hosts[name]))
        out.append("")
    out += [
        ("Never fetched: " + ", ".join(f"`{h}`" for h in FORBIDDEN_HOSTS) + " (PLAN §0.6). Every fetcher is paced ≥ 1.2 s per host, "
         "20 s timeout, browser UA for NSE, a 600 s breaker after a 403/429 from an NSE host; no new Yahoo caller anywhere (PLAN §0.7)."),
        "",
        "## The datasets (catalog order)",
        "",
    ]
    for r in rows:
        out += _row_block(r)
    out += ["## Metric registries (per-series catalogs that gate rendering)", ""]
    for name in sorted(registries):
        status, reg_rows = registries[name]
        out += _registry_table(name, status, reg_rows)
    out += ["## Index by id", "", " · ".join(f"[`{r['id']}`](#{r['id']})" for r in sorted(rows, key=lambda r: str(r["id"]))), ""]
    return "\n".join(out).rstrip() + "\n"


def build() -> str:
    status, rows = load_catalog()
    if not rows:
        raise ValueError(f"dataset_catalog seed {status}: nothing to render")
    return render(status, rows, load_registries(), allowed_hosts(), anchors_in())


# ─────────────────────────────────────────── self-test ───────────────────────────────────────────

def _good_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"id": "nse_fo_volt", "label": "FOVOLT", "pages": "DERV,OMON", "publisher": "NSE (nsearchives.nseindia.com)",
                           "publish_time_ist": "17:01", "expected_by": "21:00", "expected_offset_days": 0, "cadence": "daily",
                           "max_age_sessions": 1, "unrecoverable": False, "ingest_job": "iv_eod", "freshness_kind": "table",
                           "table_name": "nse_fo_volt", "freshness_column": "date", "freshness_where": None,
                           "dictionary_anchor": "docs/NSE_DATA_DICTIONARY.md#fovolt", "verdict": "PUBLISH-CORE", "badge": "context",
                           "note": None, "verified_at": None, "verified_by": "selftest"}
    row.update(over)
    return row


def selftest() -> list[str]:
    """Negative controls: each synthetic defect must be reported; the clean rows must pass and render identically twice."""
    anchors = {"docs/NSE_DATA_DICTIONARY.md": {"fovolt"}, "docs/GOLD_DATA_DICTIONARY.md": {"A1"}}
    failures: list[str] = []
    clean = [_good_row(), _good_row(id="vix_daily", dictionary_anchor="docs/TERMINAL_DATA_DICTIONARY.md#vix_daily", badge="arithmetic"),
             _good_row(id="gold_cot", dictionary_anchor="docs/GOLD_DATA_DICTIONARY.md#A1", publisher="CFTC")]
    if validate_rows(clean, anchors):
        failures.append(f"clean rows reported {validate_rows(clean, anchors)}")
    cases: dict[str, list[dict[str, Any]]] = {
        "signal badge": [_good_row(badge="signal")],
        "unknown badge": [_good_row(badge="bullish")],
        "unknown verdict": [_good_row(verdict="MAYBE")],
        "duplicate id": [_good_row(), _good_row()],
        "forbidden host": [_good_row(publisher="MCX (mcxindia.com)")],
        "dangling NSE anchor": [_good_row(dictionary_anchor="docs/NSE_DATA_DICTIONARY.md#nope")],
        "dangling gold anchor": [_good_row(dictionary_anchor="docs/GOLD_DATA_DICTIONARY.md#Z9")],
        "own anchor not own id": [_good_row(dictionary_anchor="docs/TERMINAL_DATA_DICTIONARY.md#other")],
        "unknown document": [_good_row(dictionary_anchor="docs/OTHER.md#x")],
        "missing key": [{k: v for k, v in _good_row().items() if k != "publisher"}],
    }
    for name, bad in cases.items():
        if not validate_rows(bad, anchors):
            failures.append(f"defect {name!r} was not reported")
    reg_ok = [{"series_id": "IV30_CM", "badge": "arithmetic", "verdict": "PUBLISH-CORE"}]
    if validate_registry("fo_iv", reg_ok):
        failures.append("clean registry reported a defect")
    for name, bad_reg in {"registry signal": [{"series_id": "X", "badge": "signal", "verdict": "PUBLISH-CORE"}],
                          "registry duplicate": reg_ok + reg_ok,
                          "registry verdict": [{"series_id": "X", "badge": "context", "verdict": "SHIP"}]}.items():
        if not validate_registry("fo_iv", bad_reg):
            failures.append(f"defect {name!r} was not reported")
    regs = {"fo_iv": ("present (1 rows)", reg_ok), "index_drivers": ("absent", [])}
    hosts = {"NSE_HOSTS": ["nsearchives.nseindia.com"]}
    first = render("selftest", clean, regs, hosts, anchors)
    if first != render("selftest", clean, regs, hosts, anchors):
        failures.append("render is not deterministic")
    for needle in ('<a id="nse_fo_volt"></a>', "| DERV | [`gold_cot`](#gold_cot), [`nse_fo_volt`](#nse_fo_volt), [`vix_daily`](#vix_daily) |",
                   "| `iv_eod` | [`gold_cot`](#gold_cot), [`nse_fo_volt`](#nse_fo_volt), [`vix_daily`](#vix_daily) |", "`IV30_CM`",
                   "describes, does not predict", "`nsearchives.nseindia.com`"):
        if needle not in first:
            failures.append(f"rendered text lacks {needle!r}")
    try:
        render("selftest", [_good_row(badge="signal")], regs, hosts, anchors)
        failures.append("render accepted a `signal` row")
    except ValueError:
        pass
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--check", action="store_true", help="exit 1 if --out differs from the rendered text")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    parser.add_argument("--selftest", action="store_true", help="run the validator's negative controls, then exit")
    args = parser.parse_args(argv)
    if args.selftest:
        failures = selftest()
        for line in failures:
            print("FAIL", line)
        print("selftest ok: every synthetic defect is reported and the clean rows render deterministically" if not failures
              else f"{len(failures)} selftest failure(s)")
        return 1 if failures else 0
    try:
        text = build()
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"STALE: {args.out} differs from the rendered dictionary; run scripts/terminal_data_dictionary.py", file=sys.stderr)
            return 1
        print(f"ok: {args.out} is current")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text.encode('utf-8'))} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
