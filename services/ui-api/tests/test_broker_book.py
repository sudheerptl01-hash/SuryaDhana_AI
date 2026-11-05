"""Broker Account: holdings + today's buys + funds, read with ICICI's real field names (SDK docs)."""
import routers.positions as pos


class FakeBreeze:
    def __init__(self, holdings=None, positions=None, funds=None, error=None):
        self.h, self.p, self.f, self.error = holdings or [], positions or [], funds, error

    def _resp(self, success):
        if self.error:
            return {"Success": None, "Status": 500, "Error": self.error}
        return {"Success": success, "Status": 200, "Error": None}

    def get_portfolio_holdings(self, **kw):
        return self._resp(self.h)

    def get_portfolio_positions(self):
        return self._resp(self.p)

    def get_funds(self):
        return self._resp(self.f)


HOLDING = {"stock_code": "RELIND", "exchange_code": "NSE", "quantity": "10", "average_price": "1200.00",
           "current_market_price": "1300.00", "product_type": None}
TODAY = {"segment": "equity", "product_type": "Cash", "exchange_code": "NSE", "stock_code": "INFTEC",
         "action": "Buy", "quantity": "5", "average_price": "1500.00", "ltp": "1490.00"}
INTRADAY_SOLD = {"segment": "equity", "product_type": "Cash", "stock_code": "TCS", "action": "NA", "quantity": "0",
                 "average_price": "0", "ltp": "3000"}
FUNDS = {"bank_account": "x", "total_bank_balance": 100000.0, "allocated_equity": 60000.0, "allocated_fno": 0.0,
         "block_by_trade_equity": 20000.0, "unallocated_balance": "40000"}


def test_settled_holdings_and_todays_buys_both_show(monkeypatch):
    monkeypatch.setattr(pos, "isec_to_nse", lambda: {"RELIND": "RELIANCE", "INFTEC": "INFY"})
    book = pos.read_book(FakeBreeze([HOLDING], [TODAY, INTRADAY_SOLD], FUNDS))
    rows = {r["symbol"]: r for r in book["rows"]}
    assert set(rows) == {"RELIANCE", "INFY"}
    assert rows["RELIANCE"]["buy_price"] == 1200.0 and rows["RELIANCE"]["current_price"] == 1300.0
    assert rows["RELIANCE"]["pnl"] == 1000.0 and rows["RELIANCE"]["status"] == "settled"
    assert rows["INFY"]["quantity"] == 5 and rows["INFY"]["status"].startswith("today")
    assert book["funds"]["cash_available"] == 60000 - 20000 - 5 * 1500 + 40000   # today's buy spent the allocation


def test_summary_adds_up(monkeypatch):
    monkeypatch.setattr(pos, "isec_to_nse", lambda: {})
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (FakeBreeze([HOLDING], [TODAY], FUNDS), None))
    s = pos.get_position_summary()
    assert s["connected"] and s["num_open_positions"] == 2
    assert s["invested_value_inr"] == 10 * 1200 + 5 * 1500
    assert s["total_pnl_inr"] == 10 * 100 + 5 * -10 and s["cash_available_inr"] == 72500


def test_dead_session_is_reported_not_shown_as_empty(monkeypatch):
    cleared = []
    monkeypatch.setattr(pos, "_invalidate_breeze_state", lambda: cleared.append(1))
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (FakeBreeze(error="Session key is expired."), None))
    s = pos.get_open_positions()
    assert s["connected"] is False and s["needs_session_refresh"] and "session has ended" in s["error"]
    assert cleared                                     # status chip turns red on the next poll


def test_no_holdings_message_means_empty_account(monkeypatch):
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (FakeBreeze(error="No Data Found"), None))
    s = pos.get_open_positions()
    assert s == {"connected": True, "positions": [], "count": 0}


def test_no_portfolio_yet_still_shows_todays_buys(monkeypatch):
    """ICICI answers holdings with Status 500 'Portfolio not defined' before anything has settled."""
    class OnlyToday(FakeBreeze):
        def get_portfolio_holdings(self, **kw):
            return {"Success": None, "Status": 500, "Error": "Portfolio not defined:You have not created a portfolio"}
    monkeypatch.setattr(pos, "isec_to_nse", lambda: {"AERIND": "AEROFLEX"})
    book = pos.read_book(OnlyToday([], [dict(TODAY, stock_code="AERIND")], FUNDS))
    assert [r["symbol"] for r in book["rows"]] == ["AEROFLEX"] and book["rows"][0]["quantity"] == 5
