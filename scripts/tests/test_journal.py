"""Weekly decision journal (scripts/journal_composer.py): calendar, sections, honest degradation."""
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import journal_composer as jc  # noqa: E402

FRI = date(2026, 10, 16)       # a Friday; ISO week 2026-W42 (Mon 12 → Fri 16 Oct)


class FakeApi(jc.Api):
    def __init__(self, data):
        self.data, self.missing = data, []

    def get(self, path, **params):
        if path not in self.data:
            self.missing.append(path)
            return None
        return self.data[path]


def shadow_fixture(root: Path) -> Path:
    d = root / "alpha_lab" / "reports"
    d.mkdir(parents=True)
    (d / "shadow_nav.csv").write_text(
        "date,S1,S1H,NIFTY\n2026-10-14,100.0,100.0,100.0\n2026-10-15,101.0,100.5,99.0\n"
        "2026-10-16,102.0,101.0,98.0\n")
    (d / "shadow_status.md").write_text(
        "# S1 paper shadow\nAs of 2026-10-16 · regime now: RISK-OFF (NIFTY 22,623 vs 200-DMA 24,218)\n"
        "Rebalances so far: 2 · S1 costs paid ₹3,100\n")
    (d / "today_book.md").write_text(
        "# S1 book as of 2026-10-16 (research/paper only)\n"
        "- Universe: top 300 by liquidity (raw close ≥ ₹20) · blocked today: 191\n"
        "- LIQUID1 (rank 1): near_52w_low\n- M&M (rank 4): below_200dma, vol60_top_decile\n")
    return root


def test_calendar_helpers():
    assert jc.week_key(FRI) == "2026-W42"
    assert jc.week_window(FRI) == (date(2026, 10, 12), date(2026, 10, 16))
    assert jc.last_weekday_of_month(FRI) == date(2026, 10, 30)            # 31 Oct is a Saturday
    assert jc.last_weekday_of_month(date(2026, 11, 3)) == date(2026, 11, 30)
    assert jc.weekdays_until(FRI, date(2026, 10, 30)) == 10               # two full weeks
    assert jc.weekdays_until(FRI, FRI) == 0


def test_next_decision_handles_signal_day_and_past_month_end():
    assert "TODAY was the month-end momentum signal" in jc.next_decision_lines(date(2026, 10, 30))[0]
    # Saturday after the signal → the NEXT month's signal, never a stale date
    assert "30 Nov" in jc.next_decision_lines(date(2026, 10, 31))[0]
    assert "30 Oct" in jc.next_decision_lines(FRI)[0]


def test_compose_full_week_is_deterministic_and_one_screenful(tmp_path):
    root = shadow_fixture(tmp_path)
    api_data = {
        "/api/desk/status": {
            "meta": {"start_capital": 500000.0, "stopped": 0},
            "latest": {"date": "2026-10-16", "nav": 505000.0, "positions": 3, "drawdown": -1.2},
            "nav": [{"date": "2026-10-12", "nav": 500000.0}, {"date": "2026-10-16", "nav": 505000.0}],
            "plans": [{"plan_id": "2026-10-14-x", "created_at": "2026-10-14T19:30:00",
                       "summary": {"est_costs": 1200.0},
                       "orders": [{"side": "BUY"}, {"side": "BUY"}, {"side": "SELL"}]}],
            "events": [{"ts": "2026-10-14T19:30:00", "kind": "rebalance"}]},
        "/api/market/monitor": {"regime": {"score": 0, "exposure": "0–20%", "days_at_score": 3}},
        "/api/telemetry/status": {"scheduler": {"jobs": [
            {"id": "daily_wrap", "last_status": "ok"}, {"id": "eod_data_pipeline", "last_status": "error"}]}},
        "/api/telemetry/logs": [
            json.dumps({"ts": "2026-10-15T19:00:00 IST", "level": "ERROR", "job": "eod_data_pipeline", "msg": "x"}),
            json.dumps({"ts": "2026-10-09T19:00:00 IST", "level": "ERROR", "job": "old_job", "msg": "last week"}),
            json.dumps({"ts": "2026-10-15T20:00:00 IST", "level": "INFO", "job": "desk_daily", "msg": "ok"})],
    }
    md1, tg1 = jc.compose_weekly(FakeApi(api_data), FRI, root)
    md2, tg2 = jc.compose_weekly(FakeApi(api_data), FRI, root)
    assert md1 == md2 and tg1 == tg2                                       # deterministic template
    assert "# Weekly decision journal — 2026-W42 (12 Oct → 16 Oct 2026)" in md1
    assert "NAV ₹5,05,000" in md1 and "+1.00% this week" in md1 and "+1.00% since start" in md1
    assert "Rebalance plan 2026-10-14-x: 2 buys / 1 sells · est costs ₹1,200" in md1
    assert "S1 +2.00% · S1H +1.00% · NIFTY -2.00%" in md1                  # since-start row
    assert "This week: S1 +2.00%" in md1 and "(3 sessions)" in md1
    assert "191 of 300 universe names blocked" in md1
    assert "LIQUID1 r1 [near_52w_low]" in md1 and "M&M r4" in md1
    assert "0/4 RISK-OFF" in md1 and "(changed this week)" in md1
    assert "S1 crash filter: RISK-OFF (NIFTY 22,623 vs 200-DMA 24,218)" in md1
    assert "30 Oct" in md1 and "10 weekday(s) away" in md1
    assert "LAST run errored: eod_data_pipeline" in md1
    assert "ERROR lines this week: eod_data_pipeline ×1" in md1 and "old_job" not in md1
    assert "PAPER ONLY" in md1 and len(md1.splitlines()) < 45              # one screenful
    assert tg1.startswith("🗒 Weekly journal 2026-W42") and len(tg1) <= 3500
    assert "reports/journal/2026-W42.md" in tg1


def test_every_section_degrades_honestly_when_sources_are_down(tmp_path):
    api = FakeApi({})
    md, tg = jc.compose_weekly(api, FRI, tmp_path)                          # no shadow files either
    assert "Desk status unavailable" in md
    assert "Shadow artifacts missing" in md
    assert "today_book.md missing" in md
    assert "Market monitor regime unavailable" in md
    assert "Controller telemetry unavailable" in md
    assert "Sources that did not answer" in md and "/api/desk/status" in md
    assert "no live order" in md.lower() or "PAPER ONLY" in md
    assert len(api.missing) == 4                                            # all four endpoints listed
    assert "🗒 Weekly journal" in tg                                        # digest still composes


def test_failure_lines_log_window_honesty_note():
    logs = [json.dumps({"ts": "2026-10-14T09:00:00 IST", "level": "INFO", "job": "a", "msg": "m"})]
    out = jc.failure_lines({"scheduler": {"jobs": []}}, logs, date(2026, 10, 12))
    assert out[0] == "- No ERROR lines in the controller log window."
    assert any("only reaches back to Wed 14 Oct 09:00" in ln for ln in out)  # ring < full week
    # ring covering the whole week → no note
    logs2 = [json.dumps({"ts": "2026-10-12T00:10:00 IST", "level": "INFO", "job": "a", "msg": "m"})]
    assert not any("only reaches back" in ln for ln in jc.failure_lines(None, logs2, date(2026, 10, 12)))


def test_desk_stop_flag_and_missing_nav():
    out = jc.desk_lines({"meta": {"stopped": 1}, "latest": {}, "nav": [], "plans": [], "events": []},
                        date(2026, 10, 12), date(2026, 10, 16))
    assert out[0] == "- Desk has no NAV marks yet."
    assert any("EMERGENCY-STOPPED" in ln for ln in out)


def test_shadow_week_needs_two_sessions(tmp_path):
    d = tmp_path / "alpha_lab" / "reports"
    d.mkdir(parents=True)
    (d / "shadow_nav.csv").write_text("date,S1,S1H,NIFTY\n2026-10-14,100.0,100.0,100.0\n")
    out = jc.shadow_lines(date(2026, 10, 12), date(2026, 10, 16), d)
    assert "Since 15 Oct start: S1 0.00%" in out[0]
    assert any("Week change n/a (1 session(s)" in ln for ln in out)


def test_done_jobs_are_not_failures():
    """PM regression (15 Oct): the controller's success word is `done` — a healthy job must never
    appear in the failures section (the first dry-run misreported db_backup_daily as errored)."""
    from journal_composer import failure_lines
    from datetime import date
    tele = {"scheduler": {"jobs": [
        {"id": "db_backup_daily", "last_status": "done"},
        {"id": "eod_data_pipeline", "last_status": "ok"},
        {"id": "never_ran_yet", "last_status": None},
        {"id": "really_broken", "last_status": "error"},
    ]}}
    lines = failure_lines(tele, [], date(2026, 10, 12))
    joined = "\n".join(lines)
    assert "db_backup_daily" not in joined and "eod_data_pipeline" not in joined
    assert "really_broken" in joined
