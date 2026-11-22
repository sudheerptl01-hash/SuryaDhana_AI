"""Item 9 (ui-api half): one failed hub refresh keeps a quiet / NSE-confirmed row DELAYED, not STALE."""
import sys
from pathlib import Path
R = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(R / "services/ui-api"), str(R)]
from routers import live as m  # noqa: E402

CONF = {"price": 55.0, "volume": 1250, "source": "breeze_ws", "age_s": 1320.0, "state": "live", "ltt": "2026-11-05T10:00:30+05:30",
        "reason": "quiet: no tick for 1320 s on a healthy feed; NSE's copy (95 s old) shows the same price and volume",
        "age_basis": "tick_received", "date": "2026-11-05", "last_trade_age_s": 1320.0, "kind": "equity", "subscribed": True,
        "confirmed_by": "nse_quote", "confirmed_age_s": 95.0, "vouched_age_s": 0.1, "hint": "possible corporate action"}


def test_restate_keeps_a_confirmed_row_delayed_on_one_failed_refresh():
    row = m.coerce_row(CONF)
    assert {"confirmed_by", "confirmed_age_s", "vouched_age_s"} <= set(row)          # within MAX_EXTRA_KEYS
    one = m.restate(row, 2.5, upstream_failed=True)
    # review D7: the row reads DELAYED by when its price was last verified, not "DELAYED · 22m" from its trade age
    assert one["state"] == "delayed" and one["age_s"] == 2.6 and one["vouched_age_s"] == 2.6 and one["trade_age_s"] == 1322.5
    assert one["reason"].startswith("data-service did not answer")
    assert m.restate(row, 95.0, upstream_failed=True)["state"] == "stale"              # still bounded by DELAYED_MAX_S
    assert m.restate(row, 1.0, upstream_failed=False)["state"] == "live"


def test_negative_control_a_row_without_vouched_age_keeps_todays_rule():
    row = m.coerce_row({k: v for k, v in CONF.items() if k != "vouched_age_s"})
    assert m.restate(row, 2.5, upstream_failed=True)["state"] == "stale"


def test_restate_ages_the_nse_confirmation_with_the_cache():
    row = m.coerce_row(CONF)
    assert m.restate(row, 1.5, upstream_failed=False)["confirmed_age_s"] == 96.5


def test_a_confirmed_row_keeps_its_new_keys_through_coerce_row():
    """review D5: the three confirmation keys come last in a real row; a cut of MAX_EXTRA_KEYS would drop them first."""
    got = m.coerce_row(dict(CONF))
    assert got is not None and {"confirmed_by", "confirmed_age_s", "vouched_age_s"} <= set(got), got
