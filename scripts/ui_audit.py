"""
UI audit: open every tab of the SuryaDhana terminal in a real browser, capture a screenshot, per-tab load
timing, browser console errors, uncaught page errors and failed requests (HTTP >= 400 / network errors).

Used page-by-page during the terminal restyle to prove each page still works, and for the desktop-app
43-page Chromium + WebKit gate (reports/desktop_app/PLAN.md AC-3; how-to: reports/desktop_app/qa_harness.md;
43 since the gold program's GOLD page, reports/gold_program/PLAN.md §h T10).

Usage (the original CLI still works unchanged):
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py [--out reports/ui_audit/after] \
        [--tabs "desk,stocks" | --tabs all] [--base http://127.0.0.1:8010] [--wait 6] \
        [--browser chromium|webkit|both] [--strict] [--screenshots full|viewport|none]
    Terminal v2 (G10): `--tabs v2` audits the ten pages wave 1 changed; `--tabs all --browser both` is the 43/43 gate.

Failure classes per tab (the policy lives in scripts/desktop_qa/netpolicy.py):
    navigation (goto failed) · not_ready (content/title never rendered) · app_error (error overlay text)
    · crash · page_error (uncaught) · console_error · failed_request (first-party HTTP >= 400 or network
    failure; EventSource/fetch streams on the 6 known stream paths aborted *by navigation* are allowlisted)
    · websocket_error · repetition (gold program T9: the words "fair open" in the titles of more than one
    panel or heading of a page — the pre-open desk must render on one page only).  --strict adds console
    warnings, third-party failures and visible ErrorBoxes.

Outputs: <out>/audit.json (per-tab, original shape + new fields; with --browser both: <out>/<engine>/audit.json),
<out>/audit_report.json and <out>/audit_report.md (all engines, timing, summary).
Exit code: 0 = every tab passed, 1 = at least one tab failed, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop_qa.netpolicy import endpoint_key
from desktop_qa.pages import PageSourceError, load_page_source
from desktop_qa.probe import ENGINES, PREFS_MODES, TabProbe, failure_lines, launch_browser, new_qa_context, non_seam_failures

ROOT = Path(__file__).resolve().parents[1]
# Default tab set: the 15 of the restyle plus `gold` since the gold program (docs/RUNBOOK_RESTORE.md expects
# "16/16 ok"). Use --tabs all for the 43 pages of ui/app/page.tsx TAB_IDS (parsed at run time, so the count follows
# page.tsx without an edit here).
TABS = {"desk": "Decision Desk", "overview": "Overview", "stocks": "Stocks", "backtest": "Backtest",
        "positions": "Portfolio", "broker": "Broker Account", "pipeline": "Pipeline", "scanner": "LW Scanner",
        "discovery": "Alpha Discovery", "commodity": "Commodity", "gold": "Gold terminal", "glassbox": "Glass-Box",
        "mlengine": "ML Engine", "explorer": "Data Explorer", "warehouse": "Warehouse", "system": "System"}

# Terminal v2 (reports/terminal_v2/PLAN.md G10): `--tabs v2` = the pages wave 1 changed (OMON chain-first + IV history,
# DERV › VOL, MEMB drivers, EVTS crush ledger, SYS › DATA, DESK attribution, MOV live panel, OSTR margin, BRF, MKT). The
# sub-views (VOL / DATA) are reached in-page, so they ride on their pages here.
TAB_SETS: dict[str, list[str]] = {
    "v2": ["options", "derivatives", "memb", "events", "system", "desk", "movers", "ostrategy", "brief", "markets"],
}

# Gold program T9 (reports/gold_program/PLAN.md §h): the pre-open desk's "fair open" may be the subject of at most one
# panel or heading per page (it lives on GOLD; CMDT and BRF keep a line or a chip, never a second panel). Matched
# against the normalised fingerprint titles (numbers masked), never against body text.
REPETITION = re.compile(r"fair open", re.IGNORECASE)
REPETITION_MAX = 1

# Terminal v2 G9/G10 placement ("the same number once per page" across pages): the live today panel renders on MOV (BRF
# keeps a one-line summary), the drivers' horizon views on MEMB only. Matched against the start of a panel header's
# normalised text (title first, then subtitle and chips), never body text; a page outside the allowed set fails.
PLACEMENT: tuple[tuple[str, re.Pattern[str], frozenset[str]], ...] = (
    ("who moved the index", re.compile(r"^who moved the index", re.IGNORECASE), frozenset({"movers", "brief"})),
    ("drivers: sector contribution", re.compile(r"^sector contribution", re.IGNORECASE), frozenset({"memb"})),
    ("drivers: monthly leaderboard", re.compile(r"^monthly leaderboard", re.IGNORECASE), frozenset({"memb"})),
    ("drivers: concentration & breadth", re.compile(r"^concentration & breadth", re.IGNORECASE), frozenset({"memb"})),
)


def resolve_tabs(spec: str, tab_ids: list[str]) -> list[str]:
    """``all`` → every TAB_ID in page order; a TAB_SETS name (``v2``) → that set (only ids page.tsx still lists, when it
    could be read); otherwise a comma list (unknown ids are kept: the page ignores them)."""
    key = spec.strip().lower()
    if key == "all":
        return list(tab_ids)
    if key in TAB_SETS:
        return [t for t in TAB_SETS[key] if not tab_ids or t in tab_ids]
    return [t.strip() for t in spec.split(",") if t.strip()]


def repetition_hits(fingerprint: dict[str, Any] | None) -> list[str]:
    """Panel titles and headings of a fingerprint that name the pre-open desk's "fair open" (T9)."""
    if not fingerprint:
        return []
    titles = list(fingerprint.get("panels") or []) + list(fingerprint.get("headings") or [])
    return [t for t in titles if REPETITION.search(t or "")]


def placement_failures(tab: str | None, fingerprint: dict[str, Any] | None) -> list[str]:
    """v2 placement rule: a panel that belongs on other pages (PLACEMENT) found on ``tab``. Unknown tab → nothing."""
    if not tab or not fingerprint:
        return []
    out: list[str] = []
    for name, pattern, allowed in PLACEMENT:
        hits = [p for p in (fingerprint.get("panels") or []) if pattern.search((p or "").strip())]
        if hits and tab not in allowed:
            out.append(f"placement: '{name}' panel on {tab} (belongs on {'/'.join(sorted(allowed))} only): {hits[:2]}")
    return out


def tab_failures(visit: dict[str, Any], events: dict[str, Any], *, strict: bool) -> list[str]:
    """The audit's failure lines for one tab: the shared policy (probe.failure_lines), the T9 repetition rule and the
    Terminal v2 placement rule."""
    lines = failure_lines(visit, events, strict=strict)
    hits = repetition_hits(visit.get("fingerprint"))
    if len(hits) > REPETITION_MAX:
        lines.append(f"repetition: 'fair open' named by {len(hits)} panels/headings (T9 allows {REPETITION_MAX}): {hits}")
    lines.extend(placement_failures(visit.get("tab"), visit.get("fingerprint")))
    return lines


def audit_engine(pw: Any, engine: str, tabs: list[str], args: argparse.Namespace, out_dir: Path,
                 names: dict[str, str], codes: dict[str, str]) -> dict[str, Any]:
    """Audit ``tabs`` in one engine; returns {tab: result}."""
    browser = launch_browser(pw, engine, chromium_channel=args.chromium_channel or None)
    version = browser.version
    ctx = new_qa_context(browser, prefs_mode=args.prefs_mode,
                         viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
    page = ctx.new_page()
    probe = TabProbe(page, args.base)
    shots = None if args.screenshots == "none" else out_dir
    visits: list[dict[str, Any]] = []
    try:
        for tab in tabs:
            v = probe.visit(tab, code=codes.get(tab), nav_timeout_s=args.nav_timeout, ready_timeout_s=args.ready_timeout,
                            idle_timeout_s=args.idle_timeout if args.idle_timeout is not None else args.wait + 15,
                            dwell_s=args.wait, drain_timeout_s=args.drain_timeout, fingerprint=True, screenshot_dir=shots,
                            full_page=args.screenshots == "full")
            visits.append(v)
            ev = probe.summarize(v["epoch"])
            fails = tab_failures(v, ev, strict=args.strict)
            t = v["timing"]
            print(f"[{engine}] {names.get(tab, tab):22} ok={v['error'] is None} {'PASS' if not fails else 'FAIL'} "
                  f"ready={t['ready_ms']}ms total={t['total_ms']}ms console={len(ev['console_errors'])} "
                  f"pageerr={len(ev['page_errors'])} failed={len(ev['failed_requests'])} "
                  f"allowed={len(ev['allowed_aborts'])}{' ' + fails[0][:140] if fails else ''}", flush=True)
    finally:
        probe.leave()
        browser.close()
    results: dict[str, Any] = {}
    for v in visits:   # final summaries: late (post-navigation) events are attributed to their tab by now
        ev = probe.summarize(v["epoch"])
        fails = tab_failures(v, ev, strict=args.strict)
        tab = v["tab"]
        api_failed = [f"{f['status']} {f['method']} {f['url']}" if f["status"] else f"FAILED {f['method']} {f['url']} {f['failure']}"
                      for f in ev["failed_requests"] if "/api/" in f["url"]]
        results[tab] = {
            # original fields (kept for compatibility)
            "name": names.get(tab, tab), "ok": v["error"] is None, "screenshot": v.get("screenshot"),
            "load_s": round((v["timing"]["total_ms"] or 0) / 1000, 1),
            "console": (ev["console_errors"] + ev["console_warnings"])[:30], "failed_api": api_failed[:30],
            "error_text": bool(v.get("app_error")), **({"error": v["error"]} if v["error"] else {}),
            # new fields
            "engine": engine, "browser_version": version, "code": codes.get(tab), "url": v["url"],
            "pass": not fails, "failures": fails, "timing": v["timing"], "nav_timing": v.get("nav_timing"),
            "console_errors": ev["console_errors"], "console_warnings": ev["console_warnings"],
            "console_detail": ev["console_detail"],
            "failures_non_seam": non_seam_failures(fails, ev["failed_requests"], ev["console_detail"]),
            "page_errors": ev["page_errors"], "failed_requests": ev["failed_requests"],
            "allowed_aborts": ev["allowed_aborts"], "third_party_failures": ev["third_party_failures"],
            "websockets": ev["websockets"], "api_endpoints": len(ev["api"]), "non_get_api": ev["non_get_api"],
            "fingerprint": v.get("fingerprint"), "pending_at_leave": v.get("pending_at_leave"),
            "repetition_hits": repetition_hits(v.get("fingerprint")),
        }
    return results


def _pct(vals: list[int], q: float) -> int | None:
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    return vals[min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))]


def failed_endpoints(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Failed requests aggregated across tabs: templated endpoint + reason → the tabs it failed on."""
    agg: dict[str, dict[str, Any]] = {}
    for tab, r in results.items():
        for f in r["failed_requests"]:
            key = f"{endpoint_key(f['method'], f['url'])} → {f['reason']}"
            slot = agg.setdefault(key, {"endpoint": key, "platform_seam": bool(f.get("seam")), "tab_ids": []})
            if tab not in slot["tab_ids"]:
                slot["tab_ids"].append(tab)
    rows = sorted(agg.values(), key=lambda x: (-len(x["tab_ids"]), x["endpoint"]))
    return [{**x, "tabs": len(x["tab_ids"])} for x in rows]


def summarize(results: dict[str, Any]) -> dict[str, Any]:
    ready = [r["timing"]["ready_ms"] for r in results.values()]
    return {"tabs": len(results), "passed": sum(r["pass"] for r in results.values()),
            "failed": [t for t, r in results.items() if not r["pass"]],
            "console_errors": sum(len(r["console_errors"]) for r in results.values()),
            "page_errors": sum(len(r["page_errors"]) for r in results.values()),
            "failed_requests": sum(len(r["failed_requests"]) for r in results.values()),
            "allowed_aborts": sum(len(r["allowed_aborts"]) for r in results.values()),
            "third_party_failures": sum(len(r["third_party_failures"]) for r in results.values()),
            "ready_ms_p50": _pct(ready, .5), "ready_ms_p95": _pct(ready, .95), "ready_ms_max": _pct(ready, 1),
            # diagnostics only (pass/fail is unchanged): which failures are platform-seam probes
            "failed_non_seam": [t for t, r in results.items() if r.get("failures_non_seam")],
            "failed_endpoints": failed_endpoints(results)}


def render_markdown(report: dict[str, Any]) -> str:
    m = report["meta"]
    lines = [f"# UI audit — {m['base']}", "",
             f"- started {m['started_at']} · finished {m['finished_at']} · strict={m['strict']} · wait={m['wait_s']}s",
             f"- label: {m.get('label') or '—'}", ""]
    for engine, block in report["engines"].items():
        s = block["summary"]
        lines += [f"## {engine} ({block['browser_version']}): {s['passed']}/{s['tabs']} PASS", "",
                  (f"console errors {s['console_errors']} · page errors {s['page_errors']} · failed requests "
                  f"{s['failed_requests']} · allowlisted stream aborts {s['allowed_aborts']} · third-party "
                  f"{s['third_party_failures']} · ready p50 {s['ready_ms_p50']} ms / p95 {s['ready_ms_p95']} ms / "
                  f"max {s['ready_ms_max']} ms"), "",
                  "| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
        for tab, r in block["tabs"].items():
            t, nt = r["timing"], r.get("nav_timing") or {}
            first = (r["failures"][0] if r["failures"] else "").replace("|", "\\|")[:160]
            lines.append(f"| {tab} | {r['code'] or ''} | {'PASS' if r['pass'] else '**FAIL**'} | {t['ready_ms']} | "
                         f"{t['idle_ms'] if t['idle_ms'] is not None else '—'} | {t['total_ms']} | {nt.get('fcp_ms')} | "
                         f"{len(r['console_errors'])} | {len(r['page_errors'])} | {len(r['failed_requests'])} | {first} |")
        lines.append("")
        fe = s.get("failed_endpoints") or []
        if fe:
            lines += [f"### {engine}: failed requests by endpoint", "",
                      (f"Tabs failing for anything other than a platform-seam probe: "
                       f"{', '.join(s.get('failed_non_seam') or []) or 'none'}"), "",
                      "| endpoint → reason | platform seam | tabs | tab ids |", "|---|---|---:|---|"]
            for x in fe:
                ids = ", ".join(x["tab_ids"][:12]) + (" …" if len(x["tab_ids"]) > 12 else "")
                lines.append(f"| {x['endpoint'].replace('|', chr(92) + '|')} | {'yes' if x['platform_seam'] else 'no'} | "
                             f"{x['tabs']} | {ids} |")
            lines.append("")
    lines.append(f"**Overall: {'PASS' if report['ok'] else 'FAIL'}**")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "reports" / "ui_audit" / "after"))
    ap.add_argument("--tabs", default=",".join(TABS),
                    help="tab ids, e.g. desk,stocks — or 'all' (page.tsx TAB_IDS) or a set name: " + ", ".join(TAB_SETS))
    ap.add_argument("--base", default="http://127.0.0.1:8010",
                    help="terminal origin (default: the live terminal served by ui-api; the old Next server was "
                         "http://localhost:3000, still usable with --base)")
    ap.add_argument("--wait", type=float, default=6.0, help="dwell seconds after load (errors surface, polls run)")
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=1050)
    ap.add_argument("--browser", choices=["chromium", "webkit", "both"], default="chromium")
    ap.add_argument("--strict", action="store_true", help="also fail on console warnings, third-party failures, ErrorBoxes")
    ap.add_argument("--screenshots", choices=["full", "viewport", "none"], default="full",
                    help="full = viewport + full-page PNG (the original behaviour)")
    ap.add_argument("--idle-timeout", type=float, default=None, help="cap on the network-idle wait (default wait+15 s)")
    ap.add_argument("--ready-timeout", type=float, default=30.0, help="max wait for the page's content/title")
    ap.add_argument("--nav-timeout", type=float, default=180.0)
    ap.add_argument("--drain-timeout", type=float, default=15.0,
                    help="max wait for in-flight API calls before leaving a tab (so the harness does not abort them)")
    ap.add_argument("--chromium-channel", default="chrome", help="'chrome' = system Chrome (original); '' = bundled")
    ap.add_argument("--json", default=None, help="report JSON path (default <out>/audit_report.json)")
    ap.add_argument("--md", default=None, help="report Markdown path (default <out>/audit_report.md)")
    ap.add_argument("--label", default="", help="free text recorded in the report (e.g. 'baseline live :3000')")
    ap.add_argument("--prefs-mode", choices=PREFS_MODES, default="readonly",
                    help="the UI's settings-sync mode in the audit browser (default readonly: never writes the "
                         "owner's live /api/prefs); 'sync' only against a scratch server")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        src = load_page_source()
        tab_ids, codes = src.tab_ids, {p.id: p.code for p in src.command_pages}
        names = {**{p.id: p.label for p in src.command_pages}, **TABS}
    except (OSError, PageSourceError) as exc:   # page.tsx unreadable or reshaped: the explicit-list mode still works
        if args.tabs.strip().lower() == "all":
            print(f"cannot resolve --tabs all: {exc}", file=sys.stderr)
            return 2
        tab_ids, codes, names = [], {}, dict(TABS)
    tabs = resolve_tabs(args.tabs, tab_ids)
    engines = list(ENGINES) if args.browser == "both" else [args.browser]
    report: dict[str, Any] = {"meta": {"base": args.base, "tabs": tabs, "engines": engines, "strict": args.strict,
                                       "wait_s": args.wait, "label": args.label,
                                       "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
                              "engines": {}}
    t0 = time.time()
    with sync_playwright() as pw:
        for engine in engines:
            eng_dir = out if len(engines) == 1 else out / engine
            eng_dir.mkdir(parents=True, exist_ok=True)
            results = audit_engine(pw, engine, tabs, args, eng_dir, names, codes)
            (eng_dir / "audit.json").write_text(json.dumps(results, indent=2))
            version = next((r["browser_version"] for r in results.values()), None)
            report["engines"][engine] = {"browser_version": version, "summary": summarize(results), "tabs": results}
    report["meta"]["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report["meta"]["elapsed_s"] = round(time.time() - t0, 1)
    report["ok"] = all(not b["summary"]["failed"] for b in report["engines"].values())
    json_path = Path(args.json) if args.json else out / "audit_report.json"
    md_path = Path(args.md) if args.md else out / "audit_report.md"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(render_markdown(report))
    for engine, b in report["engines"].items():
        s = b["summary"]
        print(f"[{engine}] {s['passed']}/{s['tabs']} PASS · failed tabs: {', '.join(s['failed']) or 'none'}")
    print(f"report: {md_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
