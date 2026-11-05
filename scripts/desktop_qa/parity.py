"""Per-tab parity: the same tab loaded from base A and base B in the same engine must behave identically.

For each tab (default: all 43 of ui/app/page.tsx TAB_IDS), interleaved A then B so both see the same market
state, it compares:

1. the set of API requests (method + templated path + query KEYS; tickers/numbers/dates/job ids in the path
   are templated, query values are ignored)
2. the response status classes per endpoint (2xx/4xx/5xx/ERR/ABORT/PENDING)
3. console errors and page errors (normalised: numbers, local origins and hashed asset names masked)
4. a structural fingerprint of the rendered page: PageHeader code+title, panel titles, headings, number of
   tables and their column headers, presence of canvas / recharts charts, iframe hosts, visible ErrorBoxes,
   the loading skeleton, error overlays, content-ready — live numbers excluded.

Platform seams (netpolicy.PLATFORM_SEAM_PATHS: /health, /api/health, /version, /build-info.json, /api/prefs)
are set aside from 1-3 and reported per tab under ``platform_seams``: the same UI code probes them differently
per front server by design (PLAN §5). ``--no-seam-exclusion`` compares them like any other endpoint. The
per-side audit scoring below still counts their failures.

Expected program deltas (netpolicy.EXPECTED_DELTAS: the header's NSE holiday lookup
``GET /api/market/eco-calendar?back=0&ahead=7``, the gold program's page-exact reads) are matched by exact query
values; an endpoint called on ONE side only, every call of which was such a request, is set aside from 1 and
reported under ``expected_deltas`` (a pre-program baseline never sends it; every current build does) — but a
PAGE-SCOPED delta (``ExpectedDelta.tabs``) only on its own pages: ``GET /api/gold/health?window=W`` is set aside
on BRF and WEI and stays a DIFF on DESK or ALRT (netpolicy.expected_delta_applies). ``--no-expected-deltas``
compares every such request.

Gold program deltas (netpolicy, 26 Oct 2026): a page declared in ``netpolicy.EXPECTED_NEW_PAGES`` (the 43rd
page ``gold``) has NO A side against a pre-program baseline, so it is visited on B only, scored with the audit
policy and reported as ``NEW`` (neither PARITY nor DIFF); the run's verdict needs every NEW page to pass its B
audit. Fingerprint entries that ``netpolicy.EXPECTED_STRUCTURE_DELTAS`` declares for a tab (CMDT without the
pre-open desk, BRF's gold panel become a line, MCXG's one-line overlay and shared selector, BRKR's auto-login
panel) are set aside and reported under ``expected_structure``; undeclared ones are still a DIFF.
``--no-expected-deltas`` switches all of this off and compares every tab and request like any other.

Verdict per tab: PARITY (no difference), DIFF (with reasons) or NEW (no A side). A DIFF is re-probed
``--retries`` times (default 1) and only a difference that persists is reported; a difference that disappeared
on retry is recorded as a note on a PARITY verdict. Each side is also scored with the audit's failure policy
(``a_pass`` / ``b_pass``), because AC-3 needs B clean, not just equal to A.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/parity.py \
        --a http://localhost:3000 --b http://127.0.0.1:8092 --browser both --out <dir> [--tabs all]
Exit code: 0 = every compared tab PARITY and every NEW page clean on B, in every engine; 1 = at least one DIFF
or a NEW page failing its B audit; 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_qa.netpolicy import (
    RESOURCE_LOAD_CONSOLE,
    expected_delta_applies,
    expected_new_page,
    is_platform_seam,
    normalize_text,
    partition_structure,
    structure_delta,
)
from desktop_qa.pages import load_page_source
from desktop_qa.probe import (
    ENGINES,
    PREFS_MODES,
    TabProbe,
    failure_lines,
    launch_browser,
    new_qa_context,
    non_seam_failures,
)

FP_LIST_FIELDS = ("page_headers", "panels", "headings", "table_headers", "iframes")


def _multiset_diff(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    ca, cb = Counter(a), Counter(b)
    return sorted((ca - cb).elements()), sorted((cb - ca).elements())


def _console_errors(e: dict[str, Any], seams: bool) -> list[str]:
    """Console errors for the comparison; with ``seams`` a resource-load error OF a seam URL is set aside."""
    detail = e.get("console_detail")
    if not seams or detail is None:
        return list(e["console_errors"])
    return list(dict.fromkeys(x["text"] for x in detail
                              if not (x.get("seam") and RESOURCE_LOAD_CONSOLE.search(x["text"] or ""))))


def seam_traffic(e: dict[str, Any]) -> dict[str, Any]:
    """Platform-seam calls of one side: /api seam endpoints with status classes + failed root-level seams."""
    api = {k: v["statuses"] for k, v in e["api"].items() if is_platform_seam(k)}
    failed = sorted({f"{f['method']} {f['url'].split('://', 1)[-1].split('/', 1)[-1]} → {f['reason']}"
                     for f in e.get("failed_requests", []) if f.get("seam")})
    return {"api": api, "failed": failed}


def compare(va: dict[str, Any], ea: dict[str, Any], vb: dict[str, Any], eb: dict[str, Any], *,
            seams: bool = True, expected: bool = True, tab: str | None = None) -> dict[str, Any]:
    """Structured differences between side A and side B of one tab (empty ``reasons`` = PARITY).

    ``seams`` (default) sets platform-seam endpoints aside, ``expected`` (default) sets one-sided expected
    program deltas aside — requests whose delta is declared for ``tab`` (or page-free), and the fingerprint
    entries ``netpolicy.EXPECTED_STRUCTURE_DELTAS`` declares for ``tab`` (defaults to the visits' ``tab``);
    ``notes`` carries what was set aside."""
    reasons: list[str] = []
    notes: list[str] = []
    d: dict[str, Any] = {}
    tab = tab or va.get("tab") or vb.get("tab")
    declared = structure_delta(tab) if expected else None
    # 1. API request set
    ka, kb = set(ea["api"]), set(eb["api"])
    if seams:
        sa, sb = seam_traffic(ea), seam_traffic(eb)
        if sa != sb:
            d["platform_seams"] = {"a": sa, "b": sb}
            notes.append(f"platform seams differ (set aside): A {sa['api'] or '{}'} {sa['failed']} · "
                         f"B {sb['api'] or '{}'} {sb['failed']}")
        ka, kb = {k for k in ka if not is_platform_seam(k)}, {k for k in kb if not is_platform_seam(k)}
    if expected:   # a tag alone never excuses a request: the delta must be declared for THIS tab (or page-free)
        xa = {k: t for k in sorted(ka - kb) if expected_delta_applies(t := ea["api"][k].get("expected_delta"), tab)}
        xb = {k: t for k in sorted(kb - ka) if expected_delta_applies(t := eb["api"][k].get("expected_delta"), tab)}
        if xa or xb:
            d["expected_deltas"] = {"a_only": xa, "b_only": xb}
            notes.append(f"expected program deltas set aside: only A {xa or '{}'} · only B {xb or '{}'}")
            ka, kb = ka - set(xa), kb - set(xb)
    if ka != kb:
        d["api_only_a"], d["api_only_b"] = sorted(ka - kb), sorted(kb - ka)
        reasons.append(f"API request set differs: only A {d['api_only_a'][:4]}, only B {d['api_only_b'][:4]}")
    # 2. status classes on common endpoints
    sd = {k: {"a": ea["api"][k]["statuses"], "b": eb["api"][k]["statuses"]}
          for k in sorted(ka & kb) if ea["api"][k]["statuses"] != eb["api"][k]["statuses"]}
    if sd:
        d["status_diff"] = sd
        reasons.append("status classes differ: " + "; ".join(f"{k} A{v['a']} B{v['b']}" for k, v in list(sd.items())[:4]))
    # 3. console / page errors
    for field, label in (("console_errors", "console errors"), ("page_errors", "page errors")):
        raw_a = _console_errors(ea, seams) if field == "console_errors" else ea[field]
        raw_b = _console_errors(eb, seams) if field == "console_errors" else eb[field]
        na = [normalize_text(x) for x in raw_a]
        nb = [normalize_text(x) for x in raw_b]
        oa, ob = sorted(set(na) - set(nb)), sorted(set(nb) - set(na))
        if oa or ob:
            d[f"{field}_only_a"], d[f"{field}_only_b"] = oa, ob
            reasons.append(f"{label} differ: only A {oa[:2]}, only B {ob[:2]}")
    # 4. structural fingerprint
    fa, fb = va.get("fingerprint") or {}, vb.get("fingerprint") or {}
    if not fa or not fb:
        if va.get("error") or vb.get("error"):
            reasons.append(f"navigation: A={va.get('error')} B={vb.get('error')}")
        else:
            reasons.append("fingerprint missing on one side")
    else:
        structure: dict[str, Any] = {}
        for f in FP_LIST_FIELDS:
            oa, ob = _multiset_diff(fa.get(f) or [], fb.get(f) or [])
            if declared is not None and (oa or ob):
                da, oa = partition_structure(tab, f, "a", oa)
                db, ob = partition_structure(tab, f, "b", ob)
                if da or db:
                    structure[f] = {"a_only": da, "b_only": db}
            if oa or ob:
                d[f"{f}_only_a"], d[f"{f}_only_b"] = oa, ob
                reasons.append(f"{f} differ: only A {oa[:3]}, only B {ob[:3]}")
        for f in ("tables",):
            if fa.get(f) != fb.get(f):
                if declared is not None and f in declared.counts:
                    structure[f] = {"a": fa.get(f), "b": fb.get(f)}
                else:
                    d[f] = {"a": fa.get(f), "b": fb.get(f)}
                    reasons.append(f"{f}: A {fa.get(f)} vs B {fb.get(f)}")
        for f in ("canvas", "recharts"):
            if bool(fa.get(f)) != bool(fb.get(f)):
                if declared is not None and f in declared.counts:
                    structure[f] = {"a": fa.get(f), "b": fb.get(f)}
                else:
                    d[f] = {"a": fa.get(f), "b": fb.get(f)}
                    reasons.append(f"{f} presence: A {fa.get(f)} vs B {fb.get(f)}")
        if structure:
            d["expected_structure"] = structure
            notes.append(f"expected structure deltas set aside ({declared.note if declared else ''}): "
                         + "; ".join(f"{k} {v}" for k, v in structure.items())[:400])
        if len(fa.get("error_boxes") or []) != len(fb.get("error_boxes") or []):
            d["error_boxes"] = {"a": fa.get("error_boxes"), "b": fb.get("error_boxes")}
            reasons.append(f"error boxes: A {fa.get('error_boxes')} vs B {fb.get('error_boxes')}")
        if bool(fa.get("skeleton")) != bool(fb.get("skeleton")):
            reasons.append(f"loading skeleton: A {fa.get('skeleton')} vs B {fb.get('skeleton')}")
    for f in ("app_error",):
        if bool(va.get(f)) != bool(vb.get(f)):
            reasons.append(f"{f}: A {va.get(f)} vs B {vb.get(f)}")
    if bool(va["timing"].get("ready")) != bool(vb["timing"].get("ready")):
        reasons.append(f"content-ready: A {va['timing'].get('ready')} vs B {vb['timing'].get('ready')}")
    return {"reasons": reasons, "diff": d, "notes": notes}


def _side(v: dict[str, Any], e: dict[str, Any], strict: bool) -> dict[str, Any]:
    fails = failure_lines(v, e, strict=strict)
    return {"url": v["url"], "pass": not fails, "failures": fails, "timing": v["timing"],
            "nav_timing": v.get("nav_timing"), "fingerprint": v.get("fingerprint"), "api": e["api"],
            "console_errors": e["console_errors"], "console_detail": e.get("console_detail"),
            "page_errors": e["page_errors"],
            "failed_requests": e["failed_requests"], "allowed_aborts": e["allowed_aborts"],
            "third_party_failures": e["third_party_failures"], "websockets": e["websockets"],
            "non_get_api": e["non_get_api"], "error": v.get("error")}


def new_page_result(tab: str, code: str | None, vb: dict[str, Any], eb: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    """The result row of a declared NEW page (netpolicy.EXPECTED_NEW_PAGES): B audited alone, no A side, verdict NEW."""
    page = expected_new_page(tab)
    b = _side(vb, eb, strict)
    note = f"no A side ({page.since}): {page.note}" if page else "no A side"
    return {"code": code, "verdict": "NEW", "reasons": [], "diff": {}, "notes": [note], "attempts": 1,
            "a": None, "b": b, "a_pass": None, "b_pass": b["pass"]}


def summarize_results(results: dict[str, Any]) -> dict[str, Any]:
    """The per-engine summary: PARITY/DIFF over the compared tabs, NEW pages (B audit only) listed on their own."""
    compared = {t: r for t, r in results.items() if r["verdict"] != "NEW"}
    new = {t: r for t, r in results.items() if r["verdict"] == "NEW"}
    return {"tabs": len(results), "compared": len(compared),
            "parity": sum(r["verdict"] == "PARITY" for r in compared.values()),
            "diff": [t for t, r in compared.items() if r["verdict"] == "DIFF"],
            "new": list(new),
            "new_failed": [t for t, r in new.items() if not r["b_pass"]],
            "a_failed": [t for t, r in compared.items() if not r["a_pass"]],
            "b_failed": [t for t, r in results.items() if not r["b_pass"]],
            "resolved_on_retry": [t for t, r in compared.items() if r["verdict"] == "PARITY" and r["attempts"] > 1],
            "seam_differences": [t for t, r in compared.items() if "platform_seams" in r["diff"]],
            "expected_delta_tabs": [t for t, r in compared.items() if "expected_deltas" in r["diff"]],
            "expected_structure_tabs": [t for t, r in compared.items() if "expected_structure" in r["diff"]],
            "a_failures_non_seam": [t for t, r in compared.items() if _non_seam_failures(r["a"])],
            "b_failures_non_seam": [t for t, r in results.items() if _non_seam_failures(r["b"])]}


def engine_ok(summary: dict[str, Any]) -> bool:
    """One engine passes when no compared tab is a DIFF and every NEW page passed its B audit."""
    return not summary["diff"] and not summary.get("new_failed")


def run_engine(pw: Any, engine: str, tabs: list[str], codes: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    browser = launch_browser(pw, engine, chromium_channel=args.chromium_channel or None)
    version = browser.version
    view = {"viewport": {"width": args.width, "height": args.height}, "device_scale_factor": 1}
    ctx_a = new_qa_context(browser, prefs_mode=args.prefs_mode, live_websockets=args.live_websockets, **view)
    ctx_b = new_qa_context(browser, prefs_mode=args.prefs_mode, live_websockets=args.live_websockets, **view)
    pa, pb = TabProbe(ctx_a.new_page(), args.a), TabProbe(ctx_b.new_page(), args.b)
    kw: dict[str, Any] = {"nav_timeout_s": args.nav_timeout, "ready_timeout_s": args.ready_timeout,
                          "idle_timeout_s": args.idle_timeout, "dwell_s": args.wait, "drain_timeout_s": args.drain_timeout,
                          "fingerprint": True, "screenshot_dir": None, "min_total_s": args.observe}
    attempts: dict[str, list[tuple[dict[str, Any] | None, dict[str, Any], list[str]]]] = {}
    try:
        for tab in tabs:
            new_page = expected_new_page(tab) if args.expected else None
            if new_page is not None:   # no A side by design: B alone, audited, never compared
                vb = pb.visit(tab, code=codes.get(tab), **kw)
                attempts[tab] = [(None, vb, [])]
                print(f"[{engine}] {tab:12} NEW    attempts=1 readyA=— readyB={vb['timing']['ready_ms']} "
                      f"(no A side: {new_page.since})", flush=True)
                continue
            tries: list[tuple[dict[str, Any] | None, dict[str, Any], list[str]]] = []
            for attempt in range(args.retries + 1):
                va = pa.visit(tab, code=codes.get(tab), **kw)
                vb = pb.visit(tab, code=codes.get(tab), **kw)
                cmp = compare(va, pa.summarize(va["epoch"]), vb, pb.summarize(vb["epoch"]), seams=args.seams,
                              expected=args.expected, tab=tab)
                tries.append((va, vb, cmp["reasons"]))
                if not cmp["reasons"]:
                    break
            attempts[tab] = tries
            last = tries[-1][2]
            va_last = tries[-1][0]
            print(f"[{engine}] {tab:12} {'PARITY' if not last else 'DIFF  '} attempts={len(tries)} "
                  f"readyA={va_last['timing']['ready_ms'] if va_last else '—'} readyB={tries[-1][1]['timing']['ready_ms']}"
                  f"{' ' + last[0][:150] if last else ''}", flush=True)
    finally:
        pa.leave()
        pb.leave()
        browser.close()
    results: dict[str, Any] = {}
    for tab, tries in attempts.items():   # final classification from final (late-event-complete) summaries
        va, vb, _ = tries[-1]
        if va is None:
            results[tab] = new_page_result(tab, codes.get(tab), vb, pb.summarize(vb["epoch"]), strict=args.strict)
            continue
        ea, eb = pa.summarize(va["epoch"]), pb.summarize(vb["epoch"])
        cmp = compare(va, ea, vb, eb, seams=args.seams, expected=args.expected, tab=tab)
        notes = [f"attempt {i + 1} differed: {r[:3]}" for i, (_, _, r) in enumerate(tries[:-1]) if r] + cmp["notes"]
        results[tab] = {"code": codes.get(tab), "verdict": "PARITY" if not cmp["reasons"] else "DIFF",
                        "reasons": cmp["reasons"], "diff": cmp["diff"], "notes": notes, "attempts": len(tries),
                        "a": _side(va, ea, args.strict), "b": _side(vb, eb, args.strict)}
        results[tab]["a_pass"], results[tab]["b_pass"] = results[tab]["a"]["pass"], results[tab]["b"]["pass"]
    return {"browser_version": version, "tabs": results, "summary": summarize_results(results)}


def _non_seam_failures(side: dict[str, Any] | None) -> list[str]:
    if side is None:
        return []
    return non_seam_failures(side["failures"], side["failed_requests"], side.get("console_detail"))


def render_markdown(report: dict[str, Any]) -> str:
    m = report["meta"]
    out = [f"# Parity — A `{m['a']}` vs B `{m['b']}`", "",
           f"- started {m['started_at']} · finished {m.get('finished_at')} · wait {m['wait_s']} s · retries {m['retries']}",
           f"- A: {m.get('label_a') or '—'}", f"- B: {m.get('label_b') or '—'}", ""]
    for engine, blk in report["engines"].items():
        s = blk["summary"]
        compared = s.get("compared", s["tabs"])
        new = s.get("new", [])
        head = f"## {engine} ({blk['browser_version']}): {s['parity']}/{compared} PARITY"
        if new:
            head += f" + {len(new)} NEW (no A side: {', '.join(new)})"
        out += [head, "",
                f"- DIFF: {', '.join(s['diff']) or 'none'}",
                f"- NEW pages failing their B audit: {', '.join(s.get('new_failed', [])) or 'none'}",
                f"- audit failures — A: {', '.join(s['a_failed']) or 'none'}; B: {', '.join(s['b_failed']) or 'none'}",
                f"- differences that disappeared on retry: {', '.join(s['resolved_on_retry']) or 'none'}",
                f"- platform-seam traffic differed (set aside): {', '.join(s.get('seam_differences', [])) or 'none'}",
                f"- expected program deltas on one side only (set aside): {', '.join(s.get('expected_delta_tabs', [])) or 'none'}",
                f"- intended structure deltas (set aside): {', '.join(s.get('expected_structure_tabs', [])) or 'none'}",
                (f"- audit failures other than platform seams — A: {', '.join(s.get('a_failures_non_seam', [])) or 'none'}; "
                 f"B: {', '.join(s.get('b_failures_non_seam', [])) or 'none'}"), "",
                "| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |",
                "|---|---|---|---|---|---:|---:|---|---|"]
        for tab, r in blk["tabs"].items():
            reason = "; ".join(r["reasons"])[:220].replace("|", "\\|")
            verdict = {"PARITY": "PARITY", "NEW": "NEW"}.get(r["verdict"], "**DIFF**")
            a = r.get("a")
            a_pass = "—" if a is None else ("yes" if r["a_pass"] else "**no**")
            a_ready = "—" if a is None else a["timing"]["ready_ms"]
            a_api = "—" if a is None else len(a["api"])
            out.append(f"| {tab} | {r['code'] or ''} | {verdict} | {a_pass} | {'yes' if r['b_pass'] else '**no**'} | "
                       f"{a_ready} | {r['b']['timing']['ready_ms']} | {a_api}/{len(r['b']['api'])} | {reason} |")
        details = [(t, r) for t, r in blk["tabs"].items()
                   if r["verdict"] == "DIFF" or (r.get("a") is not None and not r["a_pass"]) or not r["b_pass"]]
        if details:
            out += ["", f"### {engine}: details", ""]
            for tab, r in details:
                out.append(f"- **{tab}** ({r['verdict']})")
                out += [f"  - reason: {x}" for x in r["reasons"]]
                out += [f"  - A failure: {x[:240]}" for x in (r["a"]["failures"] if r.get("a") else [])]
                out += [f"  - B failure: {x[:240]}" for x in r["b"]["failures"]]
                out += [f"  - note: {x[:300]}" for x in r["notes"]]
        out.append("")
    out.append(f"**Overall: {'PARITY' if report['ok'] else 'DIFF'}**")
    return "\n".join(out) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="per-tab A/B parity (same engine)")
    ap.add_argument("--a", default="http://localhost:3000",
                    help="reference base (default: the old Next server on :3000, which no longer runs by default: "
                         "start it with ./start-local.sh start frontend, or point --a at a scratch_server.py export "
                         "of a baseline build)")
    ap.add_argument("--b", required=True, help="candidate base (static UI, e.g. http://127.0.0.1:8010)")
    ap.add_argument("--browser", choices=["chromium", "webkit", "both"], default="both")
    ap.add_argument("--tabs", default="all", help="'all' or a comma list of tab ids")
    ap.add_argument("--out", required=True)
    ap.add_argument("--wait", type=float, default=3.0, help="dwell seconds after load")
    ap.add_argument("--idle-timeout", type=float, default=8.0)
    ap.add_argument("--ready-timeout", type=float, default=30.0)
    ap.add_argument("--nav-timeout", type=float, default=120.0)
    ap.add_argument("--drain-timeout", type=float, default=15.0)
    ap.add_argument("--observe", type=float, default=12.0,
                    help="observe each side for at least this many seconds from navigation (same window on A and "
                         "B, so interval polls fire on both or neither; 12 s sits between the UI's 10 s and 15 s "
                         "pollers). 0 = old behaviour (idle + dwell only)")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--strict", action="store_true", help="score a_pass/b_pass with the strict audit policy")
    ap.add_argument("--width", type=int, default=1680)
    ap.add_argument("--height", type=int, default=1050)
    ap.add_argument("--chromium-channel", default="chrome")
    ap.add_argument("--no-seam-exclusion", dest="seams", action="store_false",
                    help="compare platform-seam endpoints (/health, /api/health, /version, /build-info.json, "
                         "/api/prefs) like any other endpoint")
    ap.add_argument("--no-expected-deltas", dest="expected", action="store_false",
                    help="compare the expected program deltas (netpolicy.EXPECTED_DELTAS, e.g. the header's "
                         "/api/market/eco-calendar?back=0&ahead=10) like any other endpoint; also visits A for the "
                         "declared NEW pages (netpolicy.EXPECTED_NEW_PAGES, e.g. gold) and compares the declared "
                         "structure deltas (EXPECTED_STRUCTURE_DELTAS) like any other fingerprint difference")
    ap.add_argument("--label-a", default="")
    ap.add_argument("--label-b", default="")
    ap.add_argument("--prefs-mode", choices=PREFS_MODES, default="readonly",
                    help="the UI's settings-sync mode in both contexts (default readonly: never writes the owner's "
                         "live /api/prefs)")
    ap.add_argument("--live-websockets", action="store_true",
                    help="let the pages' WebSockets reach the servers (default: every WebSocket is mocked, so a run "
                         "opens 0 live monitor sockets; use only against scratch backends)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.retries < 0:
        print("--retries must be >= 0", file=sys.stderr)
        return 2
    from playwright.sync_api import sync_playwright

    src = load_page_source()
    codes = {p.id: p.code for p in src.command_pages}
    tabs = list(src.tab_ids) if args.tabs.strip().lower() == "all" else [t.strip() for t in args.tabs.split(",") if t.strip()]
    engines = list(ENGINES) if args.browser == "both" else [args.browser]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"meta": {"a": args.a, "b": args.b, "tabs": tabs, "engines": engines, "wait_s": args.wait,
                                       "retries": args.retries, "label_a": args.label_a, "label_b": args.label_b,
                                       "seam_exclusion": args.seams, "expected_deltas": args.expected,
                                       "observe_s": args.observe,
                                       "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")},
                              "engines": {}}
    t0 = time.time()
    with sync_playwright() as pw:
        for engine in engines:
            report["engines"][engine] = run_engine(pw, engine, tabs, codes, args)
            (out / "parity.json").write_text(json.dumps(report, indent=2))   # checkpoint per engine
    report["meta"]["finished_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    report["meta"]["elapsed_s"] = round(time.time() - t0, 1)
    report["ok"] = all(engine_ok(b["summary"]) for b in report["engines"].values())
    (out / "parity.json").write_text(json.dumps(report, indent=2))
    (out / "parity.md").write_text(render_markdown(report))
    for engine, b in report["engines"].items():
        s = b["summary"]
        new = f" · NEW (B only): {', '.join(s['new'])}" if s.get("new") else ""
        print(f"[{engine}] {s['parity']}/{s['compared']} PARITY{new} · DIFF: {', '.join(s['diff']) or 'none'} · "
              f"B audit failures: {', '.join(s['b_failed']) or 'none'}")
    print(f"report: {out / 'parity.md'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
