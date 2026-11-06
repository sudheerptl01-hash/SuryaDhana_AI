"""Daily market wrap (scripts/daily_wrap.py): formatting helpers and section assembly on canned endpoint data."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_wrap as dw  # noqa: E402


def test_formatters():
    assert dw.inr(501042) == "₹5,01,042" and dw.inr(999) == "₹999" and dw.inr(12345678) == "₹1,23,45,678"
    assert dw.pct(-0.004) == "0.00%" and dw.pct(1.234, 1) == "+1.2%" and dw.pct(None) == "—"
    assert dw.crore(-3568.9) == "−₹3,569 cr" and dw.crore(4743.26) == "+₹4,743 cr"
    assert dw.next_weekday(date(2026, 10, 9)) == date(2026, 10, 12)      # Friday → Monday


class FakeApi(dw.Api):
    """Canned endpoint data; a value may be a callable of the query params (as_of, symbol …)."""

    def __init__(self, data):
        self.data, self.missing = data, []
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path not in self.data:
            self.missing.append(path)
            return None
        v = self.data[path]
        return v(**params) if callable(v) else v


N50 = {"rows": [{"date": d, "close": c} for d, c in (("2026-10-29", 22936.75), ("2026-10-30", 23053.10), ("2026-11-02", 23440.80),
                                                      ("2026-11-03", 23810.85), ("2026-11-04", 23960.60))]}
MON_30OCT = {"as_of": "2026-10-30", "index_name": "Nifty 500", "breadth": {"universe": 1394, "adv": 239, "dec": 1148, "pct_above50": 17},
             "regime": {"score": 0, "exposure": "0–20%", "days_at_score": 20}, "sectors": [{"industry": "Healthcare", "ret_1d_pct": -0.2}],
             "movers": {"gainers": [{"symbol": "JISLJALEQS", "chg_pct": 19.9}]},
             "history": [{"date": "2026-10-30", "score": 0, "pct_above50": 17.0, "pct_above200": 38.0, "ad_line": -100, "nh_nl": -73}]}


def stale_api(**extra):
    """The 04 Nov 2026 evening: the controller came back after a dark spell, data-service had 30 Oct's EOD only."""
    return FakeApi({
        "/api/market/monitor": MON_30OCT,
        "/api/market/index-daily": lambda **p: N50 if p.get("symbol") == "NIFTY50" else {"rows": []},
        "/api/market/crash-filter": {"date": "2026-10-30", "nifty": 23053.1, "sma200": 24041, "risk_on": False, "move_needed_pct": 4.3},
        "/api/market/fii-dii-cash": {"rows": [{"date": "2026-11-04", "category": "FII", "net_cr": 7284.0},
                                              {"date": "2026-11-04", "category": "DII", "net_cr": -3712.0}], "summary": {}},
        "/api/market/option-chain/NIFTY": {"found": True, "date": "2026-10-30", "expiry": "2026-11-09", "expiries": ["2026-11-09"],
                                           "max_pain": 23000, "resistance": [23700], "support": [22000], "expected_move_pct": 2.29},
        "/api/desk/status": {"latest": {"date": "2026-11-04", "nav": 502666.0, "positions": 0, "drawdown": 0.0},
                             "nav": [{"date": "2026-11-04", "nav": 502666.0, "positions": 0, "drawdown": 0.0}],
                             "meta": {"start_capital": 500000.0}},
        **extra})


def test_build_never_prints_another_days_data():
    """Review M10: a 04 Nov wrap built from 30 Oct EOD says 'not stored' for every 30 Oct section."""
    api = stale_api()
    md, summary, st = dw.build_report(api, date(2026, 11, 4), refresh=False)
    assert "239 up" not in md and "Healthcare" not in md and "JISLJALEQS" not in md      # 30 Oct breadth / sectors / movers
    assert "23,053 vs 200-day" not in md and "call wall 23,700" not in md                 # 30 Oct crash line and chain
    assert "- Breadth: data for 04 Nov not stored (latest stored 30 Oct)" in md
    assert "- Sector returns: data for 04 Nov not stored (latest stored 30 Oct)" in md
    assert "- NIFTY option chain: data for 04 Nov not stored (latest stored 30 Oct)" in md
    assert st["breadth"] == st["sectors"] == st["movers"] == st["regime"] == dw.NOT_STORED
    assert "> ⚠ Data for 04 Nov not stored for: breadth, regime, crash filter, sectors, movers" in md
    # what IS dated 04 Nov is shown: the index close from stored closes, the crash filter recomputed, the cash, the Desk
    assert "NIFTY 50 23,960.60 (+0.63%)" in md and st["session"] == "ok"
    assert "Desk crash filter: NIFTY 23,961 vs 200-day" not in md or st["crash_filter"] == dw.NOT_STORED   # < 180 closes
    assert "FII +₹7,284 cr · DII −₹3,712 cr" in md and st["cash_flows"] == "ok"
    assert "NAV ₹5,02,666" in md and st["desk"] == "ok"
    assert "incomplete:" in summary and "breadth" not in summary.split("incomplete:")[0]
    assert dw.read_marker(md)["breadth"] == dw.NOT_STORED


def test_build_uses_the_days_own_snapshot():
    """Negative control: the same day's snapshot (as_of read) fills every section and marks them ok."""
    mon = {**MON_30OCT, "as_of": "2026-11-04", "breadth": {**MON_30OCT["breadth"], "adv": 950, "dec": 440},
           "history": MON_30OCT["history"] + [{"date": "2026-11-04", "score": 0}]}
    api = stale_api(**{"/api/market/monitor": lambda **p: mon if p.get("as_of") == "2026-11-04" else MON_30OCT})
    md, _, st = dw.build_report(api, date(2026, 11, 4), refresh=False)
    assert "950 up / 440 down" in md and "Breadth (liquid NSE universe, 1,394 stocks)" in md and "Nifty 500" not in md
    assert st["breadth"] == st["sectors"] == st["movers"] == st["regime"] == "ok"
    assert ("/api/market/monitor", {"as_of": "2026-11-04"}) in api.calls


def test_breadth_history_fallback_is_labelled():
    """Without the dated snapshot, the stored breadth history gives the day's shape and says what it lacks."""
    hist = {**MON_30OCT, "history": MON_30OCT["history"] + [{"date": "2026-11-04", "score": 1, "pct_above50": 30.0,
                                                               "pct_above200": 45.0, "ad_line": 400, "nh_nl": 20}]}
    md, _, st = dw.build_report(stale_api(**{"/api/market/monitor": hist}), date(2026, 11, 4), refresh=False)
    assert "net advances 500" in md and "advances / declines and VIX for that day are not stored" in md
    assert st["breadth"] == "ok" and st["regime"] == "ok" and st["sectors"] == dw.NOT_STORED


def test_cash_mtd_counts_sessions():
    rows = [{"date": d, "category": c, "net_cr": v} for d in ("2026-11-04", "2026-11-05") for c, v in (("FII", 10.0), ("DII", -5.0))]
    m = dw.mtd_flows(rows, ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"], "2026-11-05")
    assert m["present"] == 2 and m["expected"] == 4 and m["missing"] == ["2026-11-02", "2026-11-03"] and m["sums"]["FII"] == 20.0
    full = dw.mtd_flows(rows, ["2026-11-04", "2026-11-05"], "2026-11-05")
    assert full["present"] == full["expected"] == 2 and full["missing"] == []


def test_cash_line_prints_n_of_m():
    api = stale_api(**{"/api/market/fii-dii-cash": {"rows": [{"date": "2026-11-04", "category": "FII", "net_cr": 7284.0},
                                                             {"date": "2026-11-04", "category": "DII", "net_cr": -3712.0}]}})
    md, _, _ = dw.build_report(api, date(2026, 11, 4), refresh=False)
    assert "(1 of 3 sessions; no figures for 02 Nov, 03 Nov)" in md


def test_wrap_needs_rebuild():
    legacy = "# Market wrap · Wed 04 Nov 2026\n\nWritten 21:30 IST from the terminal's data (NSE end of day 2026-10-30)."
    assert dw.wrap_needs_rebuild(legacy, "2026-11-04") == "legacy wrap written from 2026-10-30 data"
    assert dw.wrap_needs_rebuild(legacy.replace("2026-10-30", "2026-11-04"), "2026-11-04") is None     # negative control
    ok = "x\n" + dw.sections_marker({k: "ok" for k in dw.REQUIRED})
    assert dw.wrap_needs_rebuild(ok, "2026-11-04") is None
    part = "x\n" + dw.sections_marker({**{k: "ok" for k in dw.REQUIRED}, "sectors": dw.NOT_STORED})
    assert dw.wrap_needs_rebuild(part, "2026-11-04") == "incomplete: sectors"


def test_backfill_writes_only_complete_wraps(tmp_path):
    """--backfill-missing: a session whose sections are not all stored is skipped (strict), written with --allow-partial,
    and a complete wrap is never touched."""
    (tmp_path / "2026-10-29.md").write_text("done\n" + dw.sections_marker({k: "ok" for k in dw.REQUIRED}))
    api = stale_api()
    rep = dw.backfill(api, tmp_path, date(2026, 10, 29), date(2026, 11, 4), dry_run=False)
    assert rep["complete_already"] == 1 and rep["written"] == []
    assert set(rep["skipped"]) == {"2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"}
    assert not (tmp_path / "2026-11-04.md").exists()
    rep = dw.backfill(stale_api(), tmp_path, date(2026, 11, 4), date(2026, 11, 4), allow_partial=True)
    assert [w["date"] for w in rep["written"]] == ["2026-11-04"] and "breadth" in rep["written"][0]["not_stored"]
    assert "data for 04 Nov not stored" in (tmp_path / "2026-11-04.md").read_text()
    assert (tmp_path / "2026-10-29.md").read_text().startswith("done")


def test_next_session_skips_nse_holidays():
    assert dw.next_session(date(2026, 11, 9), {"2026-11-10"}) == date(2026, 11, 11)
    assert dw.next_session(date(2026, 11, 6), set()) == date(2026, 11, 9)


def test_crash_filter_recomputed_for_a_past_session():
    from datetime import timedelta
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(200)]
    closes = {d: 100.0 for d in days}
    closes[days[-1]] = 90.0
    got = dw.crash_filter_on(closes, days[-1])
    assert got["risk_on"] is False and round(got["sma200"], 2) == 99.95 and round(got["move_needed_pct"], 1) == 11.1
    assert dw.crash_filter_on(closes, days[50]) is None          # < 180 sessions: not computed (negative control)


def test_internals_lines_flag_a_narrow_rally():
    from daily_wrap import internals_lines
    sm = {"samples": 180, "first": "13-Oct-2026 09:16", "last": "13-Oct-2026 15:30", "net_worst": -120, "net_best": 95,
          "net_now": -82, "small_minus_n50": -1.31, "divergence": "narrow: NIFTY up, most stocks down"}
    out = internals_lines(sm)
    assert "09:16–15:30" in out[0] and "-120 to 95, ended -82" in out[0] and "small caps" in out[0]
    assert "Narrow: NIFTY up" in out[1]
    assert internals_lines({}) == []


def test_numbers_note_only_for_that_days_filing():
    from daily_wrap import numbers_note
    f = {"filed_at": "2026-10-13T17:05:00", "revenue_yoy": 11.46, "pat_yoy": 21.2}
    assert numbers_note(f, "2026-10-13") == ", revenue +11% / profit +21% y/y"
    assert numbers_note(f, "2026-10-14") == ""
    assert numbers_note({**f, "pat_yoy": None, "pat_yoy_turn": "to loss"}, "2026-10-13") == ", revenue +11% / profit to loss y/y"
    assert numbers_note(None, "2026-10-13") == ""


def test_concentration_line():
    from daily_wrap import concentration_line
    book = [{"symbol": "CUPID", "quantity": 200}, {"symbol": "AEROFLEX", "quantity": 100}]
    q = {"CUPID.NS": {"available": True, "price": 353.1}, "AEROFLEX.NS": {"available": True, "price": 557.6}}
    line = concentration_line(book, q)
    assert line == "- Book ₹1,26,380: CUPID 56% · AEROFLEX 44% (behaves like 2.0 equal positions)"
    assert concentration_line(book[:1], q) == ""


def test_movers_line():
    from daily_wrap import movers_line
    c = {"change": 358.6, "explained_points": 357.3, "members": [{"symbol": s, "points": p} for s, p in
         (("TCS", 30.7), ("INFY", 30.6), ("ICICIBANK", 30.2), ("HDFCBANK", 29.1), ("MARUTI", -1.9), ("KOTAKBANK", -6.7))]}
    assert movers_line(c) == ("- Who moved NIFTY (points): TCS +31 · INFY +31 · ICICIBANK +30 · drag KOTAKBANK -7 · MARUTI -2"
                              " (weights rebuilt from filings explain +357 of +359)")
    assert movers_line({}) == ""


def test_next_expiry_rolls_on_expiry_day():
    from daily_wrap import next_expiry
    opt = {"found": True, "expiry": "2026-10-13", "expiries": ["2026-10-13", "2026-10-20", "2026-10-27"]}
    assert next_expiry(opt, "2026-10-13") == "2026-10-20"
    assert next_expiry({**opt, "expiry": "2026-10-20"}, "2026-10-13") is None
    assert next_expiry({"found": False}, "2026-10-13") is None


def test_valuation_line():
    from daily_wrap import valuation_line
    ix = {"NIFTY 50": {"pe": 19.41, "pb": 2.79, "dy": 1.51}, "NIFTY MIDCAP 150": {"pe": 28.34}, "NIFTY SMALLCAP 250": {"pe": 34.39}}
    assert valuation_line(ix) == "- Valuation (NSE): NIFTY P/E 19.4× · P/B 2.79 · dividend yield 1.51% · Midcap 150 28.3× · Smallcap 250 34.4×"
    assert valuation_line({}) == ""
    from daily_wrap import ordinal
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 100, 101, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "100th", "101st", "111th"]
    vs = {"NIFTY 50": {"pctl": 12, "median": 22.1, "since": "2021-03-31"}}
    assert valuation_line(ix, vs).startswith("- Valuation (NSE): NIFTY P/E 19.4× (12th percentile since Mar 2021, median 22.1×) · P/B 2.79")


def test_short_line_keeps_persistent_meaningful_shorts():
    from daily_wrap import short_line
    rows = [{"symbol": "HEROMOTOCO", "short_pct_of_volume": 4.21, "days": 4},
            {"symbol": "ONEOFF", "short_pct_of_volume": 9.0, "days": 1},        # a single day: left out
            {"symbol": "TINY", "short_pct_of_volume": 0.3, "days": 5}]          # too small a share: left out
    assert short_line(rows) == "- Institutional short selling, last 5 sessions: HEROMOTOCO 4.2% of volume (4 days)"
    assert short_line([]) == ""


def test_valuation_line_flags_a_stretched_small_cap_premium():
    from daily_wrap import valuation_line
    ix = {"NIFTY 50": {"pe": 19.41, "pb": 2.79, "dy": 1.51}, "NIFTY MIDCAP 150": {"pe": 28.3}, "NIFTY SMALLCAP 250": {"pe": 34.4}}
    rel = {"NIFTY MIDCAP 150": {"ratio": 1.46, "pctl": 63}, "NIFTY SMALLCAP 250": {"ratio": 1.77, "pctl": 99}}
    line = valuation_line(ix, None, rel)
    assert line.endswith("Midcap 150 28.3× · Smallcap 250 34.4× (1.77× NIFTY, 99th percentile)")    # mid is ordinary: no note


# ── checker 6 Nov: a backfilled wrap names its write date; a wrap run spawned from a test never reads the live stack ──
def test_a_backfilled_wrap_names_its_write_date():
    from datetime import datetime
    md, _, _ = dw.build_report(stale_api(), date(2026, 11, 4), refresh=False, now=datetime(2026, 11, 6, 8, 55))  # noqa: DTZ001 — the wrap runs on the IST clock
    head = md.splitlines()[2]
    assert head.startswith("Backfilled 06 Nov 2026 08:55 IST from the terminal's stored data for 04 Nov 2026"), head
    # negative control: the evening's own wrap keeps the short form
    md, _, _ = dw.build_report(stale_api(), date(2026, 11, 4), refresh=False, now=datetime(2026, 11, 4, 21, 0))  # noqa: DTZ001
    assert md.splitlines()[2].startswith("Written 21:00 IST from the terminal's stored data for 04 Nov 2026")


def test_a_run_spawned_under_pytest_neither_reads_the_stack_nor_writes_the_archive(monkeypatch, capsys, tmp_path):
    """p03 (nse_evening_pass) and the outage catch-up spawn daily_wrap.py --backfill-missing with the controller's
    UI_API, which the controller fixtures point at the live :8010. The child inherits PYTEST_CURRENT_TEST: refused
    before any GET unless the test passed its own --out."""
    import json

    calls: list = []
    monkeypatch.setattr(dw.Api, "get", lambda self, path, **p: calls.append(path))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "scripts/tests/test_terminal_v2_controller.py::test_x (call)")
    dw.main(["--backfill-missing", "--since", "2026-10-29", "--until", "2026-11-04", "--base", "http://127.0.0.1:8010"])
    rep = json.loads(capsys.readouterr().out.strip().splitlines()[-1][7:])
    assert rep["refused"].startswith("refused") and rep["written"] == [] and calls == []
    dw.main(["--date", "2026-11-04"])                                   # the 21:00 single-day mode too
    assert "refused" in capsys.readouterr().out and calls == []
    # negative control: a test's own --out runs normally (and reads the API it was given)
    dw.main(["--backfill-missing", "--since", "2026-11-04", "--until", "2026-11-04", "--out", str(tmp_path), "--dry-run"])
    assert "refused" not in capsys.readouterr().out and calls
    # and outside pytest the default archive is allowed
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    assert dw.refuse_under_pytest(dw.ROOT / "reports" / "daily_wrap") is None


def test_the_child_process_inherits_the_guard(tmp_path):
    """The real subprocess, as p03 spawns it (env = the parent's + PYTHONPATH): it exits at once with 'refused', with a
    --base nothing listens on, so a GET attempt would show as an error instead."""
    import os
    import subprocess

    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "daily_wrap.py"), "--base", "http://127.0.0.1:9",
                          "--backfill-missing", "--since", "2026-11-04", "--until", "2026-11-04"],
                         capture_output=True, text=True, timeout=60, cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert res.returncode == 0 and res.stdout.strip().splitlines()[-1].startswith("RESULT ") and "refused" in res.stdout, res.stderr
