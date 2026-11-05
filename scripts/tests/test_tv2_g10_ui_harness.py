"""G10 (Terminal v2 PLAN 1.7) as code: the UI harnesses carry the wave-1 budgets and rules. The PM runs the harnesses
against the live terminal (`ui_audit.py --tabs all --browser both` 43/43, `ui_perf.py --enforce-budgets`); these tests
pin what they enforce — OMON chain ready ≤ 400 ms (p95, measured to the chain rows on screen), first-load JS ≤ 300 kB
gz, the `v2` audit set and the placement rule — each with a negative control. No browser is started."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ui_audit  # noqa: E402
import ui_perf  # noqa: E402
from desktop_qa.pages import load_page_source  # noqa: E402

OMON_TSX = ROOT / "ui" / "components" / "OptionChain.tsx"


def _tab(code: str, ms: float | None, browser: str = "chromium", run: int = 1) -> dict:
    return {"browser": browser, "run": run, "tab": code.lower(), "code": code, "switch_ms": ms}


def test_ui_perf_budgets_are_the_plan_numbers():
    assert ui_perf.BUDGETS["first_load_js_gz_kb"] == 300.0 and ui_perf.BUDGETS["tab_switch_p95_ms"] == 400.0
    assert ui_perf.PAGE_BUDGETS_MS == {"OMON": 400.0}
    codes = {p.code for p in ui_perf.load_pages()}
    assert set(ui_perf.PAGE_BUDGETS_MS) <= codes and set(ui_perf.READY_SELECTORS) <= codes
    # the chain-ready selector names an element OptionChain.tsx really renders (an attribute on every strike row)
    sel = ui_perf.READY_SELECTORS["OMON"]
    attr = re.fullmatch(r"\[([a-z-]+)\]", sel)
    assert attr and f"{attr.group(1)}=" in OMON_TSX.read_text(encoding="utf-8")
    # the switch script takes the selector and requires it before "ready"
    assert "([tab, code, skel, evt, sel])" in ui_perf.SWITCH_JS and "(!sel || !!document.querySelector(sel))" in ui_perf.SWITCH_JS
    assert ui_perf.build_parser().parse_args(["--enforce-budgets"]).enforce_budgets is True
    assert ui_perf.build_parser().parse_args([]).enforce_budgets is False


def test_budget_breaches_flag_omon_and_first_load_with_negative_controls():
    ok = {"cold": [{"js_gz_kb": 250.0}], "tabs": [_tab("OMON", 300.0), _tab("OMON", 390.0), _tab("BRF", 120.0)], "bundle": None}
    assert ui_perf.budget_breaches(ok) == []
    slow = {**ok, "tabs": ok["tabs"] + [_tab("OMON", 650.0)]}
    found = ui_perf.budget_breaches(slow)
    assert [b["budget"] for b in found] == ["tab_switch_p95_ms", "page_OMON_p95_ms"] and found[1]["value"] == 650.0
    never = {**ok, "tabs": [_tab("OMON", None), _tab("BRF", 100.0)]}
    assert [b["where"] for b in ui_perf.budget_breaches(never)] == ["chromium: never ready"]
    fat = {**ok, "bundle": {"first_load_js_gz_kb": 301.2}}
    assert [b["budget"] for b in ui_perf.budget_breaches(fat)] == ["first_load_js_gz_kb"]
    # the bundle analysis wins over the cold-load estimate; without it, the cold-load median is used
    assert ui_perf.budget_breaches({**fat, "bundle": {"first_load_js_gz_kb": 299.0}, "cold": [{"js_gz_kb": 999.0}]}) == []
    heavy_cold = {**ok, "cold": [{"js_gz_kb": 310.0}, {"js_gz_kb": 320.0}]}
    assert ui_perf.budget_breaches(heavy_cold)[0]["budget"] == "first_load_js_gz_kb"
    # per engine: a slow WebKit OMON is reported for WebKit only
    two = {**ok, "tabs": ok["tabs"] + [_tab("OMON", 380.0, "webkit"), _tab("OMON", 900.0, "webkit")]}
    got = [(b["budget"], b["where"]) for b in ui_perf.budget_breaches(two)]
    assert got == [("tab_switch_p95_ms", "webkit"), ("page_OMON_p95_ms", "webkit")]
    meta = {"label": "t", "base": "b", "runs": 1, "started": "s"}
    bundle = {"first_load_js_gz_kb": 301.2, "first_load_js_raw_kb": 900.0, "first_load": [{"file": "a.js"}],
              "total_js_gz_kb": 1100.0, "js_files": 97}
    md = ui_perf.summarize([{"meta": meta, "cold": [], "tabs": [], "bundle": bundle}])
    has_breach = "Budgets (" in md and "**first_load_js_gz_kb** 301.2 > 300" in md
    assert has_breach, md[-400:]
    lean = {**bundle, "first_load_js_gz_kb": 280.0}
    met = "all met" in ui_perf.summarize([{"meta": meta, "cold": [], "tabs": [], "bundle": lean}])
    assert met, "negative control: a bundle inside the budget reads 'all met'"


def test_ui_audit_v2_set_and_repetition_rules():
    src = load_page_source()
    v2 = ui_audit.resolve_tabs("v2", src.tab_ids)
    assert v2 == ui_audit.TAB_SETS["v2"] and len(v2) == 10 and set(v2) <= set(src.tab_ids)
    assert {"options", "derivatives", "memb", "system"} <= set(v2)
    assert ui_audit.resolve_tabs("v2", src.tab_ids + ["x"]) == v2
    assert ui_audit.resolve_tabs("v2", [t for t in src.tab_ids if t != "memb"]) == [t for t in v2 if t != "memb"], \
        "negative control: a page dropped from page.tsx drops out of the set"
    assert ui_audit.resolve_tabs("all", src.tab_ids) == src.tab_ids and len(src.tab_ids) == 43
    # placement: the live "who moved the index" panel and the MEMB horizon views
    fp = {"panels": ["Who moved the index", "Breadth"], "headings": []}
    assert ui_audit.placement_failures("movers", fp) == [] and ui_audit.placement_failures("brief", fp) == []
    bad = ui_audit.placement_failures("markets", fp)
    assert len(bad) == 1 and bad[0].startswith("placement: 'who moved the index' panel on markets")
    memb = {"panels": ["Sector contribution", "Monthly leaderboard · 12 months", "Concentration & breadth"], "headings": []}
    assert ui_audit.placement_failures("memb", memb) == [] and len(ui_audit.placement_failures("desk", memb)) == 3
    assert ui_audit.placement_failures(None, memb) == [] and ui_audit.placement_failures("desk", None) == []
    # the gold T9 rule is unchanged (one 'fair open' panel per page)
    assert ui_audit.repetition_hits({"panels": ["Fair open (model)"], "headings": []}) == ["Fair open (model)"]
    assert ui_audit.REPETITION_MAX == 1
