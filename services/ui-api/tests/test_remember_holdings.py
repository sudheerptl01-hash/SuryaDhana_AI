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
