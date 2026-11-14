"""Every live Breeze SDK call in ui-api goes through the ONE budget ledger (F6-01, 14 Nov 2026).

PLAN §0.11 and ``positions._breeze_call``'s own docstring both say "every caller passes through it", but four
sites reached the SDK straight off ``_get_breeze_client()`` — ``routers/mcx.py`` (get_quotes, get_historical_data_v2)
and ``routers/gold_preopen.py`` (the same pair). The ledger had therefore recorded ZERO ``get_quotes`` in its
whole life (``/api/positions/breeze-budget`` by_method held only generate_session and get_customer_details),
while the CMDT silver/crude desks and the MCXG gold desk poll those paths every 30 s. On a live MCX session that
is ~6 unmetered calls a minute, which outruns ICICI's documented daily ceiling while the ledger still promises
the IV tape and the chain poller a budget that no longer exists. It failed SILENTLY, which is the one failure
mode the rest of this product does not have.

This is the gate, not the fix: it fails on a NEW bare call, so the hole cannot quietly return. Two metering
styles are accepted because both reach the same ledger — ``_breeze_call(...)`` (which wraps ``ledger().guard``
and retries once) and an explicit ``with ledger().guard(caller, method):`` block.
"""
from __future__ import annotations

import re
from pathlib import Path

UI_API = Path(__file__).resolve().parents[1]

#: the SDK methods that cost a call against ICICI's quota (reads and the margin calculator; order methods are
#: refused outright elsewhere — see test_http_security.py — so they are deliberately not listed as "allowed")
METERED_METHODS = ("get_quotes", "get_historical_data_v2", "get_historical_data", "get_option_chain_quotes",
                   "margin_calculator", "get_margin", "get_portfolio_holdings", "get_portfolio_positions",
                   "get_funds", "get_customer_details", "get_trade_list", "get_order_detail")
_CALL = re.compile(r"\bbreeze\.(" + "|".join(METERED_METHODS) + r")\s*\(")
#: how many lines above a call the metering may appear (a guard block plus the call's own argument lines)
_WINDOW = 8


def _bare_sdk_calls() -> list[str]:
    """Every `breeze.<metered>(` call site with no visible metering above it, as 'file:line method'."""
    bare: list[str] = []
    for path in sorted(UI_API.rglob("*.py")):
        if "/tests/" in str(path):
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        for n, line in enumerate(lines):
            m = _CALL.search(line)
            if not m:
                continue
            stripped = line.strip()
            if stripped.startswith(("#", "*", '"', "'")) or "`" in line:
                continue                                   # prose in a docstring or comment, not a call
            window = "\n".join(lines[max(0, n - _WINDOW):n + 1])
            if "_breeze_call(" in window or "ledger().guard(" in window:
                continue
            bare.append(f"{path.relative_to(UI_API)}:{n + 1} {m.group(1)}")
    return bare


def test_no_breeze_sdk_call_bypasses_the_budget_ledger() -> None:
    bare = _bare_sdk_calls()
    assert not bare, (
        "Breeze SDK call(s) that do not pass through the ledger — wrap them in positions._breeze_call(fn, "
        "caller='ui-api.<area>', ...) or `with ledger().guard(caller, method):`. An unmetered call drains the "
        "real broker quota while every budgeted caller is told it still has room:\n  " + "\n  ".join(bare))


def test_the_four_f6_sites_are_metered_with_their_own_caller_labels() -> None:
    """The specific sites F6-01 found, pinned by caller label so a refactor cannot drop the metering quietly."""
    mcx = (UI_API / "routers" / "mcx.py").read_text(encoding="utf-8")
    gold = (UI_API / "routers" / "gold_preopen.py").read_text(encoding="utf-8")
    assert mcx.count('_breeze_call(breeze.get_quotes, caller="ui-api.mcx"') == 1
    assert mcx.count('_breeze_call(breeze.get_historical_data_v2, caller="ui-api.mcx"') == 1
    assert gold.count('_breeze_call(breeze.get_quotes, caller="ui-api.gold-preopen"') == 1
    assert gold.count('_breeze_call(breeze.get_historical_data_v2, caller="ui-api.gold-preopen"') == 1


def test_the_detector_would_catch_a_bare_call(tmp_path: Path) -> None:
    """Negative control: the regex and the window really do flag an unmetered call, and really do allow a
    metered one — otherwise this gate could pass by being blind."""
    bare = "def f(breeze):\n    q = breeze.get_quotes(stock_code='GOLD')\n"
    metered = ("def f(breeze):\n    with ledger().guard('x', 'get_quotes'):\n"
               "        q = breeze.get_quotes(stock_code='GOLD')\n")
    assert _CALL.search(bare) and _CALL.search(metered)                     # both are call sites
    assert "ledger().guard(" not in bare and "ledger().guard(" in metered   # only one is metered


def test_the_quote_cache_outlasts_the_desk_poll() -> None:
    """F6-01's other half: commodity_desk cached quotes for 15 s while the UI polls every 30 s, so EVERY poll
    was a deliberate cache miss and the comment "concurrent viewers share one broker call" was false."""
    desk = (UI_API / "routers" / "commodity_desk.py").read_text(encoding="utf-8")
    ttl = int(re.search(r"^QUOTE_TTL_S\s*=\s*(\d+)", desk, re.M).group(1))
    ui = (UI_API.parents[1] / "ui" / "components" / "commodity" / "CommodityDesk.tsx").read_text(encoding="utf-8")
    poll_ms = int(re.search(r"QUOTE_MS\s*=\s*([\d_]+)", ui).group(1).replace("_", ""))
    assert ttl >= poll_ms / 1000, f"cache {ttl}s must span the {poll_ms / 1000:g}s poll or every poll costs a call"
