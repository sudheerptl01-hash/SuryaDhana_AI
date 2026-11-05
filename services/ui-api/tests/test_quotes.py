"""routers/quotes.py (/api/quotes/ticks) since LV-API (5 Nov 2026): the overlay reads the live NSE hub (routers/live.py ->
data-service /live/quotes), never Yahoo. Source order, overlay states, ages, the status-derived feed state and the zero-Yahoo
proof are pinned in test_live_ticks.py; this file keeps the B4 wire-contract pin under its historical name."""
import asyncio

import test_live_support as sup

from routers import quotes


def test_wire_key_is_ticks_not_quotes(monkeypatch):
    """Pin the B4 wire contract: ui/lib/liveTicks.ts parses `data.ticks` -- shipping `quotes`
    left the terminal permanently tickless (bloomberg_verdict defect #1). Never rename."""
    sup.install(monkeypatch)
    out = asyncio.run(quotes.live_quotes(symbols="TCS"))
    assert "ticks" in out and "quotes" not in out


def test_holdings_are_no_longer_unioned_here(monkeypatch):
    """data-service pins the holdings (and the NIFTY 50 / NIFTY BANK members, the watchlist) itself under the live contract,
    so the overlay asks only for what its caller asked."""
    fake = sup.install(monkeypatch)
    asyncio.run(quotes.live_quotes(symbols="TCS.NS"))
    assert fake.quote_calls() == [["TCS"]] and not hasattr(quotes, "_holdings_symbols")
