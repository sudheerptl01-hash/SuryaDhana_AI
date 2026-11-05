from routers.markets import numbers_status, reacting_rows, reaction_phase, results_filed_since_close


def test_only_results_after_previous_close_or_today():
    prev = [{"symbol": "AAA", "category": "results", "time": "2026-10-12 14:10:00"},   # before close: already priced
            {"symbol": "BBB", "category": "results", "time": "2026-10-12 16:48:00"},
            {"symbol": "CCC", "category": "orders", "time": "2026-10-12 17:00:00"}]
    today = [{"symbol": "BBB", "category": "results", "time": "2026-10-13 09:01:00"},  # duplicate keeps the first
             {"symbol": "DDD", "category": "results", "time": "2026-10-13 08:15:00"}]
    assert results_filed_since_close(prev, today) == {"BBB": "2026-10-12 16:48", "DDD": "2026-10-13 08:15"}


def test_rows_ranked_by_size_vs_normal():
    filed = {"HCL": "t", "RBL": "t", "NEW": "t", "NOQ": "t"}
    typical = {"HCL": {"typical_move_pct": 3.5}, "RBL": {"typical_move_pct": 2.5}}
    rows = reacting_rows(filed, typical, {"HCL": 5.06, "RBL": -5.666, "NEW": 4.5})
    assert [r["symbol"] for r in rows] == ["RBL", "NEW", "HCL", "NOQ"]
    assert rows[0]["change_pct"] == -5.67 and rows[0]["vs_typical"] == 2.27
    assert rows[1]["vs_typical"] is None and rows[-1]["change_pct"] is None


def test_vs_nifty_when_index_known():
    rows = reacting_rows({"HCL": "t"}, {}, {"HCL": 5.0}, nifty_pct=0.87)
    assert rows[0]["vs_nifty_pct"] == 4.13
    assert reacting_rows({"HCL": "t"}, {}, {"HCL": 5.0})[0]["vs_nifty_pct"] is None


def test_reaction_phase_ignores_yesterdays_quotes_before_the_open():
    from datetime import datetime
    assert reaction_phase(datetime(2026, 10, 14, 8, 30)) == "closed"
    assert reaction_phase(datetime(2026, 10, 14, 9, 5)) == "preopen"
    assert reaction_phase(datetime(2026, 10, 14, 9, 15)) == "session"
    assert reaction_phase(datetime(2026, 10, 17, 11, 0)) == "closed"      # Saturday


def test_numbers_status():
    assert numbers_status("A", {"A": {}}, {"A": {}}) == "ok"
    assert numbers_status("B", {}, {"B": {}}) == "not_on_feed"
    assert numbers_status("C", {}, {}) == "pending"
