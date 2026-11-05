"""Saved holdings survive a session that answers 'success' with no rows (14 Oct 2026, 00:11)."""
import json
from datetime import datetime

import routers.positions as pos

BOOK = [{"symbol": "CUPID", "quantity": 200, "buy_price": 355.5, "invested": 71100.0}]


def _saved():
    return json.loads(pos._last_holdings_path().read_text())


def test_overnight_empty_read_is_ignored():
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 13, 18, 30))
    pos._remember_holdings([], now=datetime(2026, 10, 14, 0, 11))
    assert _saved()["positions"] == BOOK and "empty_since" not in _saved()


def test_one_empty_read_waits_two_confirm_a_sell_out():
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 14, 9, 0))
    pos._remember_holdings([], now=datetime(2026, 10, 14, 10, 0))
    assert _saved()["positions"] == BOOK and _saved()["empty_since"] == "2026-10-14T10:00:00"
    pos._remember_holdings([], now=datetime(2026, 10, 14, 10, 10))          # too soon to confirm
    assert _saved()["positions"] == BOOK
    pos._remember_holdings([], now=datetime(2026, 10, 14, 10, 45))
    assert _saved()["positions"] == [] and "empty_since" not in _saved()


def test_a_real_read_clears_the_pending_empty_mark():
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 14, 9, 0))
    pos._remember_holdings([], now=datetime(2026, 10, 14, 10, 0))
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 14, 10, 5))
    assert _saved()["positions"] == BOOK and "empty_since" not in _saved()


def test_an_unchanged_book_is_re_stamped_checked_at_not_as_of():
    """5 Nov: RSK read the empty book as 22 days stale; the book had not changed, ICICI confirmed it that day."""
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 14, 15, 13))
    first = _saved()
    assert first["as_of"] == first["checked_at"] == "2026-10-14T15:13:00"
    pos._remember_holdings(BOOK, now=datetime(2026, 10, 14, 15, 20))            # within 15 min: no rewrite
    assert _saved()["checked_at"] == "2026-10-14T15:13:00"
    pos._remember_holdings(BOOK, now=datetime(2026, 11, 5, 13, 0))
    later = _saved()
    assert later["as_of"] == "2026-10-14T15:13:00" and later["checked_at"] == "2026-11-05T13:00:00" and later["positions"] == BOOK
    # negative controls: a pending empty read never confirms the book; a changed book moves both stamps
    pos._remember_holdings([], now=datetime(2026, 11, 5, 14, 0))
    assert _saved()["checked_at"] == "2026-11-05T13:00:00" and _saved()["empty_since"] == "2026-11-05T14:00:00"
    pos._remember_holdings(BOOK[:0] + [{**BOOK[0], "quantity": 300}], now=datetime(2026, 11, 5, 14, 5))
    assert _saved()["as_of"] == _saved()["checked_at"] == "2026-11-05T14:05:00"


def test_risk_dashboard_dates_the_broker_book_by_its_last_confirmation():
    import routers.riskdash as rd

    pos._last_holdings_path().write_text(json.dumps({"as_of": "2026-10-14T15:13:04", "checked_at": "2026-11-05T13:00:00", "positions": []}))
    assert rd._broker_book([]) == ([], "2026-11-05T13:00:00")
    pos._last_holdings_path().write_text(json.dumps({"as_of": "2026-10-14T15:13:04", "positions": []}))    # an older file: as_of
    assert rd._broker_book([]) == ([], "2026-10-14T15:13:04")
