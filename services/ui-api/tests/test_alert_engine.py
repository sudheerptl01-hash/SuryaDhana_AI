"""The typed alert engine (alert_engine.py, PLAN 2.3 / review M41): rule validation, the evaluator's semantics, the
extractors on the real payload shapes, and the direction-word scan of every template. Each rule has a negative
control (the same check against the defect it guards)."""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import alert_engine as E  # noqa: E402

NOW = datetime.fromisoformat("2026-11-06T10:00:00+05:30")
TODAY = date(2026, 11, 6)
ROOT = Path(__file__).resolve().parents[3]
#: payloads recorded read-only from data-service :8001 on 6 Nov 2026 09:55 IST (drivers for NIFTY 50 / NIFTY BANK / the
#: short id 'NIFTY', and a slice of the NIFTY option chain as the pre-M05 live service serves it: OI in shares + lot)
RECORDED = json.loads((Path(__file__).resolve().parent / "fixtures" / "alerts_recorded_20261106.json").read_text(encoding="utf-8"))


def rule(series: str, op: str, value: Any = None, **kw: Any) -> dict[str, Any]:
    body = E.validate_rule({"series": series, "op": op, "value": value, **kw})
    return {"id": "r-test", "status": "active", "state": {}, **body}


def obs(v: Any, hist: tuple[float, ...] = (), **kw: Any) -> E.Observation:
    return E.Observation(v, kw.pop("as_of", "2026-11-05"), "test", hist, **kw)


def run(r: dict[str, Any], *values: Any, start: datetime = NOW, step: timedelta = timedelta(minutes=1), **kw: Any) -> list[E.Evaluation]:
    """Feed observations one per `step`, carrying state / status like the router does."""
    out = []
    t = start
    for v in values:
        o = v if isinstance(v, E.Observation) else obs(v, **kw)
        ev = E.evaluate(r, o, t)
        r = {**r, "state": ev.state, "status": ev.status, "snooze_until": ev.snooze_until}
        out.append(ev)
        t += step
    return out


def fired(evs: list[E.Evaluation]) -> list[bool]:
    return [ev.fire is not None for ev in evs]


# ── validation ──────────────────────────────────────────────────────────────────────────────────────────────
def test_series_ids_parse_and_normalise() -> None:
    k, p = E.parse_series("oi_strike:nifty:24500:ce")
    assert k.kind == "oi_strike" and p == {"symbol": "NIFTY", "strike": 24500.0, "side": "CE"}
    assert E.series_id("oi_strike", p) == "oi_strike:NIFTY:24500:CE"
    assert E.parse_series("straddle:NIFTY:2026-11-24")[1] == {"symbol": "NIFTY", "expiry": "2026-11-24"}
    assert E.parse_series("fii_net")[1] == {}
    assert E.parse_series("iv30:FINNIFTY")[1] == {"symbol": "FINNIFTY"}           # its options series are fine
    assert E.quote_ticker("price", {"symbol": "NIFTY"}) == "^NSEI" and E.quote_ticker("price", {"symbol": "TCS"}) == "TCS.NS"
    for bad in ("", "nope:TCS", "price", "price:TCS:extra", "oi_strike:NIFTY:x:CE", "oi_strike:NIFTY:24500:XX", "price:^NSEI",
                "nifty_driver:FINNIFTY", "straddle:NIFTY:24-11-2026", "data_stale:Bad Id", "price:FINNIFTY"):
        with pytest.raises(E.RuleError):
            E.parse_series(bad)


def test_validate_rule_defaults_and_limits() -> None:
    r = E.validate_rule({"series": "iv30:NIFTY", "op": "pctile_above", "value": 80})
    assert (r["window"], r["repeat"], r["channel"], r["cooldown_min"], r["symbol"]) == (252, "once", "both", 0, "NIFTY")
    assert E.validate_rule({"series": "iv30:NIFTY", "op": "above", "value": 18, "repeat": "repeat"})["cooldown_min"] == 30
    assert E.validate_rule({"series": "fo_ban:KAYNES", "op": "cross_up"})["value"] == 0.5         # a 0/1 flag
    assert E.validate_rule({"series": "nifty_driver:NIFTY", "op": "changed", "value": 3})["value"] is None
    bad = [
        {"series": "iv30:NIFTY", "op": "sideways", "value": 1},
        {"series": "fo_ban:TCS", "op": "above", "value": 1},                     # not an op of the kind
        {"series": "iv30:NIFTY", "op": "above"},                                 # no value
        {"series": "iv30:NIFTY", "op": "pctile_above", "value": 120},
        {"series": "iv30:NIFTY", "op": "pctile_above", "value": 80, "window": 5},
        {"series": "iv_pctile:NIFTY", "op": "above", "value": 140},
        {"series": "price:TCS", "op": "change_pct", "value": 3, "window": 5},    # a live quote has no daily history here
        {"series": "iv30:NIFTY", "op": "change_pct", "value": 0},
        {"series": "iv30:NIFTY", "op": "above", "value": 18, "channel": "sms"},
        {"series": "iv30:NIFTY", "op": "above", "value": 18, "repeat": "often"},
        {"series": "iv30:NIFTY", "op": "above", "value": 18, "cooldown_min": -1},
        {"series": "iv30:NIFTY", "op": "above", "value": 18, "note": "x" * 201},
    ]
    for b in bad:
        with pytest.raises(E.RuleError):
            E.validate_rule(b)


def test_a_note_with_a_direction_word_is_refused_and_a_plain_note_is_kept() -> None:
    for note in ("buy the dip", "bullish breakout", "IV will rise after this", "go long here", "price target 3300"):
        with pytest.raises(E.RuleError, match="direction"):
            E.validate_rule({"series": "price:TCS", "op": "above", "value": 3200, "note": note})
    # negative control: a descriptive note, and the position names the ALRT analysis recommends, pass
    for note in ("results on 9 Nov", "short strangle breakeven", "short-option breakeven 24,800"):
        assert E.validate_rule({"series": "price:TCS", "op": "above", "value": 3200, "note": note})["note"] == note


def test_position_names_pass_on_both_sides_and_predictive_notes_do_not() -> None:
    """Review 6 Nov: 'short straddle' passed while 'long straddle' was refused, and 'bounce expected' / 'goes higher from
    here' passed. Position names now pass alike; predictive phrasing in a note is refused."""
    for note in ("LONG straddle wing", "long strangle breakeven", "long call 25000 · short put 24000", "under the expected move",
                 "short straddle adjusted", "long-option decay"):
        assert E.validate_rule({"series": "price:TCS", "op": "above", "value": 3200, "note": note})["note"] == note
    for note in ("bounce expected", "goes higher from here", "IV heading lower", "go long straddle", "higher highs", "it could fall"):
        with pytest.raises(E.RuleError, match="direction"):
            E.validate_rule({"series": "price:TCS", "op": "above", "value": 3200, "note": note})
    # negative control: the round-1 scan (no long-side names, no predictive list) refused the one and passed the others
    old_allowed = ("short-option minimum", "short-option", "short option", "short strangle", "short straddle")

    def old_scan(t: str) -> list[str]:
        for ph in old_allowed:
            t = re.sub(re.escape(ph), " ", t, flags=re.IGNORECASE)
        return sorted({m.group(0).lower() for m in E._DIRECTION_RE.finditer(t)})
    assert old_scan("LONG straddle wing") == ["long"] and old_scan("bounce expected") == [] and old_scan("goes higher from here") == []
    assert E.note_words("go long straddle") == ["go long"]                         # "go …" is never a position name


# ── no template carries a direction word ─────────────────────────────────────────────────────────────────────
def test_every_template_is_direction_free() -> None:
    samples = E.template_samples()
    assert len(samples) > 250                               # every kind × op × both values, summaries, labels
    bad = {t: E.note_words(t) for t in samples if E.note_words(t)}  # the stricter note scan: no predictive phrase either
    assert not bad, bad


def test_negative_control_the_scan_sees_direction_words() -> None:
    assert E.direction_words("NIFTY bullish breakout above 25,000") == ["breakout", "bullish"]
    assert E.direction_words("TCS: time to BUY") == ["buy"]
    assert E.direction_words("IV likely to rise") == ["likely to rise"]
    assert E.direction_words("call wall at the resistance") == ["resistance"]
    assert E.direction_words("crossed 25,000 from under it") == []
    # the same scan over a template with an injected word fails
    assert E.direction_words(E.template_samples()[0] + " · buy") == ["buy"]


def test_the_vocabulary_covers_the_learn_validator() -> None:
    """The engine's list is the LEARN validator's (PLAN §0.1) plus 'target' / 'forecast'; never fewer words."""
    src = (Path(__file__).resolve().parents[3] / "reports" / "terminal_v2" / "LEARN" / "validate_learn.py").read_text(encoding="utf-8")
    block = src.split("DIRECTION_PATTERNS: tuple[str, ...] = (", 1)[1].split("\n)", 1)[0]
    import re
    learn = set(re.findall(r'r"([^"]+)"', block))
    assert learn and learn <= set(E.DIRECTION_PATTERNS), learn - set(E.DIRECTION_PATTERNS)


# ── the evaluator ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_level_fires_once_while_it_stays_crossed_and_re_arms() -> None:
    r = rule("iv30:NIFTY", "above", 18, repeat="repeat", cooldown_min=0)
    evs = run(r, 17.0, 18.5, 19.0, 19.5, 17.5, 18.2)
    assert fired(evs) == [False, True, False, False, False, True]
    assert evs[2].reason and "re-arms" in evs[2].reason
    # negative control: without the armed flag every minute above 18 would fire (the level-triggered defect)
    naive = [E.condition(r, v, v, None) for v in (17.0, 18.5, 19.0, 19.5, 17.5, 18.2)]
    assert naive.count(True) == 4


def test_a_first_reading_already_past_the_level_fires() -> None:
    assert fired(run(rule("iv_pctile:NIFTY", "above", 80), 85.0)) == [True]


def test_once_stops_after_the_first_fire_and_repeat_does_not() -> None:
    once = run(rule("iv30:NIFTY", "above", 18), 19.0, 17.0, 19.0)
    assert fired(once) == [True, False, False] and once[-1].status == "fired"
    rep = run(rule("iv30:NIFTY", "above", 18, repeat="repeat", cooldown_min=0), 19.0, 17.0, 19.0)
    assert fired(rep) == [True, False, True] and rep[-1].status == "active"


def test_cross_up_needs_a_previous_reading_and_fires_on_the_crossing_only() -> None:
    r = rule("price:NIFTY", "cross_up", 25000, repeat="repeat", cooldown_min=0)
    evs = run(r, 25100.0, 24900.0, 25000.0, 25200.0, 24950.0, 25010.0)
    assert fired(evs) == [False, False, True, False, False, True]          # first reading = the baseline
    assert evs[0].reason == "baseline recorded"
    assert "from under it (24,900.00 → 25,000.00)" in evs[2].fire["text"]
    down = run(rule("price:NIFTY", "cross_down", 25000, repeat="repeat", cooldown_min=0), 25100.0, 24990.0, 24980.0)
    assert fired(down) == [False, True, False]


def test_an_unavailable_reading_never_fires_and_never_moves_the_baseline() -> None:
    r = rule("oi_wall:NIFTY:CE", "changed", repeat="repeat", cooldown_min=0)
    gap = E.Observation(None, None, "test", note="read failed: 503")
    evs = run(r, 25000.0, gap, gap, 25000.0, 25500.0)
    assert fired(evs) == [False, False, False, False, True]
    assert evs[1].state["last_value"] == 25000.0 and evs[1].state["last_error"] == "read failed: 503"
    # negative control: had the outage been stored as the baseline, the recovery would read as a change
    assert E.condition(r, None, 25000.0, None) is None and E.condition(r, None, 25000.0, 24000.0) is True


def test_change_pct_from_history_or_the_precomputed_day_move() -> None:
    hist = tuple(float(x) for x in (100, 101, 102, 103, 104))
    r5 = rule("iv30:NIFTY", "change_pct", 10, window=5)
    ev = E.evaluate(r5, obs(112.0, hist), NOW)
    assert ev.fire and ev.metric == pytest.approx(12.0)
    assert E.evaluate(r5, obs(108.0, hist), NOW).fire is None                     # +8 % < 10 %
    assert E.evaluate(r5, obs(110.0, hist[-3:]), NOW).reason.startswith("not enough history")
    day = rule("price:TCS", "change_pct", 3)
    assert E.evaluate(day, obs(3000.0, change_pct=-3.4), NOW).fire["text"].startswith("TCS price moved −3.4 % on the day")
    assert E.evaluate(day, obs(3000.0, change_pct=2.9), NOW).fire is None


def test_percentile_ops_need_twenty_sessions_and_match_the_iv_definition() -> None:
    hist = tuple(float(x) for x in range(1, 101))                                  # 1 … 100
    r = rule("iv30:NIFTY", "pctile_above", 90, window=100)
    ev = E.evaluate(r, obs(95.5, hist), NOW)
    assert ev.metric == 95.0 and ev.fire is not None and "percentile 95 of 100 sessions" in ev.fire["text"]
    assert E.evaluate(r, obs(50.0, hist), NOW).fire is None
    assert E.evaluate(r, obs(500.0, hist[:10]), NOW).reason.startswith("not enough history for a percentile")
    lo = rule("fii_net", "pctile_below", 5)
    assert E.evaluate(lo, obs(-9000.0, tuple(float(x) for x in range(-5000, 5000, 100))), NOW).fire is not None
    assert E.percentile_of(5.0, [1.0, 2.0, 5.0, 9.0]) == 50.0                     # strictly below, as derivatives.py


def test_cooldown_suppresses_and_a_level_fires_after_it_if_still_true() -> None:
    r = rule("iv30:NIFTY", "above", 18, repeat="repeat", cooldown_min=30)
    t = NOW
    evs = run(r, 19.0, 17.0, 19.0, 19.0, 19.0, start=t, step=timedelta(minutes=10))
    # 10:00 fire; 10:10 false (re-arm); 10:20 true but inside 30 min → suppressed and still armed; 10:30 fires
    assert fired(evs) == [True, False, False, True, False]
    assert "cooldown until" in (evs[2].reason or "")
    edge = run(rule("oi_wall:NIFTY:PE", "changed", repeat="repeat", cooldown_min=30), 24000.0, 23500.0, 23000.0, 23000.0,
               step=timedelta(minutes=10))
    assert fired(edge) == [False, True, False, False] and edge[2].state["suppressed"] == 1    # an edge in a cooldown is consumed


def test_snooze_is_silent_then_a_level_fires_after_it() -> None:
    r = rule("iv30:NIFTY", "above", 18, repeat="repeat", cooldown_min=0)
    r = {**r, "status": "snoozed", "snooze_until": (NOW + timedelta(minutes=15)).isoformat()}
    evs = run(r, 19.0, 19.0, 19.0, step=timedelta(minutes=10))
    assert fired(evs) == [False, False, True] and evs[0].status == "snoozed" and evs[2].status == "active"
    # negative control: the same readings unsnoozed fire at once
    assert fired(run({**r, "status": "active", "snooze_until": None}, 19.0))[0]


def test_a_paused_rule_is_not_evaluated() -> None:
    r = {**rule("iv30:NIFTY", "above", 18), "status": "paused"}
    ev = E.evaluate(r, obs(30.0), NOW)
    assert ev.fire is None and ev.reason == "rule is paused" and "last_value" not in ev.state


def test_a_fire_carries_badge_source_and_date() -> None:
    ev = E.evaluate(rule("skew25:NIFTY", "above", 3, note="results on 9 Nov"), obs(3.15), NOW)
    f = ev.fire
    assert f and f["badge"] == "context" and f["as_of"] == "2026-11-05" and f["symbol"] == "NIFTY"
    assert f["text"].endswith("· as of 2026-11-05 · test · context · note: results on 9 Nov")
    assert E.KINDS["iv30"].badge == "arithmetic" and {k.badge for k in E.KINDS.values()} == {"arithmetic", "context"}   # no 'signal'


# ── extractors on the real payload shapes (captured read-only from :8001 on 6 Nov 2026) ────────────────────
IV_SUMMARY = {"symbol": "NIFTY", "as_of": "2026-11-05", "rows": [
    {"date": "2026-11-03", "iv30_cm": 13.464, "iv_pctile_252": 65.87, "iv_rank_252": 23.75, "iv_minus_rv20": -2.6953, "skew_25d_30": 3.1524},
    {"date": "2026-11-04", "iv30_cm": 12.8082, "iv_pctile_252": None, "iv_rank_252": None, "iv_minus_rv20": None, "skew_25d_30": 2.2285},
    {"date": "2026-11-05", "iv30_cm": 12.7968, "iv_pctile_252": 59.92, "iv_rank_252": 20.56, "iv_minus_rv20": -4.3991, "skew_25d_30": 1.3493}]}
CHAIN = {"symbol": "NIFTY", "found": True, "date": "2026-11-05", "expiry": "2026-11-09", "atm": 24550.0, "spot": 24536.6, "lot": 50, "rows": [
    {"strike": 24500.0, "ce": {"price": 190.0, "oi": 3000000.0, "oi_chg": 1000000.0}, "pe": {"price": 120.0, "oi": 5000000.0, "oi_chg": 0.0}},
    {"strike": 24550.0, "ce": {"price": 156.15, "oi": 4294095.0, "oi_chg": 2677935.0}, "pe": {"price": 160.4, "oi": 2999295.0, "oi_chg": 2997800.0}},
    {"strike": 25000.0, "ce": {"price": 20.0, "oi": 9000000.0, "oi_chg": 10.0}, "pe": {"price": 470.0, "oi": 10.0, "oi_chg": 0.0}}]}


def got_for(kind: str, params: dict[str, Any], *payloads: Any, live: bool = True) -> dict[E.Need, Any]:
    return dict(zip(E.needs(kind, params, TODAY, live), payloads, strict=True))


def test_iv_series_read_the_latest_session_and_never_fill_a_gap() -> None:
    p = {"symbol": "NIFTY"}
    o = E.extract("iv_pctile", p, got_for("iv_pctile", p, IV_SUMMARY), TODAY)
    assert (o.value, o.as_of, o.history) == (59.92, "2026-11-05", (65.87,))
    gap = {"rows": IV_SUMMARY["rows"][:2]}                                         # the latest session holds a null
    o2 = E.extract("iv_rank", p, got_for("iv_rank", p, gap), TODAY)
    assert o2.value is None and o2.as_of == "2026-11-04" and "no iv_rank_252 stored for 2026-11-04" in o2.note
    o3 = E.extract("iv30", p, got_for("iv30", p, IV_SUMMARY), TODAY)
    assert o3.value == 12.7968 and o3.history == (13.464, 12.8082)
    assert E.extract("iv30", p, got_for("iv30", p, RuntimeError("503 data-service")), TODAY).note.startswith("read failed")


def test_chain_series_straddle_oi_at_a_strike_and_the_wall() -> None:
    p = {"symbol": "NIFTY"}
    s = E.extract("straddle", p, got_for("straddle", p, CHAIN), TODAY)
    assert s.value == pytest.approx(316.55) and "strike 24550" in s.source and "expiry 2026-11-09" in s.source
    k = {"symbol": "NIFTY", "strike": 24500.0, "side": "CE"}
    o = E.extract("oi_strike", k, got_for("oi_strike", k, CHAIN), TODAY)
    assert o.value == 60000.0 and o.change_pct == pytest.approx(50.0)             # 3.0 M shares ÷ lot 50; 2.0 M → 3.0 M
    miss = {"symbol": "NIFTY", "strike": 24600.0, "side": "CE"}
    assert "not in the stored chain" in E.extract("oi_strike", miss, got_for("oi_strike", miss, CHAIN), TODAY).note
    ce, pe = {"symbol": "NIFTY", "side": "CE"}, {"symbol": "NIFTY", "side": "PE"}
    assert E.extract("oi_wall", ce, got_for("oi_wall", ce, CHAIN), TODAY).value == 25000.0
    assert E.extract("oi_wall", pe, got_for("oi_wall", pe, CHAIN), TODAY).value == 24500.0
    assert E.needs("straddle", {"symbol": "NIFTY", "expiry": "2026-11-24"}, TODAY)[0].params == (("expiry", "2026-11-24"),)


def test_ban_results_flows_vix_driver_gold_and_data() -> None:
    sv = {"ban": ["KAYNES"], "dates": {"ban": "2026-11-06"}}
    k = {"symbol": "KAYNES"}
    assert E.extract("fo_ban", k, got_for("fo_ban", k, sv), TODAY).value == 1.0
    assert E.extract("fo_ban", {"symbol": "TCS"}, got_for("fo_ban", {"symbol": "TCS"}, sv), TODAY).value == 0.0
    ev = {"rows": [{"symbol": "HINDALCO", "event_date": "2026-11-06", "kind": "RESULTS"},
                   {"symbol": "TCS", "event_date": "2026-11-09", "kind": "RESULTS", "first_seen": "2026-10-21 19:05:11"},
                   {"symbol": "TCS", "event_date": "2026-11-07", "kind": "DIVIDEND"}, {"symbol": "TCS", "event_date": "2026-11-01", "kind": "RESULTS"}]}
    t = {"symbol": "TCS"}
    o = E.extract("results_days", t, got_for("results_days", t, ev), TODAY)
    assert (o.value, o.extra["event_date"]) == (3.0, "2026-11-09")
    assert E.extract("results_days", {"symbol": "INFY"}, got_for("results_days", {"symbol": "INFY"}, ev), TODAY).value is None
    cash = {"rows": [{"date": "2026-11-04", "category": "FII", "net_cr": 7284.03}, {"date": "2026-11-04", "category": "DII", "net_cr": -3712.23},
                     {"date": "2026-11-05", "category": "FII", "net_cr": 14974.68}, {"date": "2026-11-05", "category": "DII", "net_cr": -10444.54}]}
    f = E.extract("fii_net", {}, got_for("fii_net", {}, cash), TODAY)
    assert (f.value, f.history, f.as_of) == (14974.68, (7284.03,), "2026-11-05")
    assert E.extract("dii_net", {}, got_for("dii_net", {}, cash), TODAY).value == -10444.54
    daily = {"rows": [{"date": "2026-11-04", "close": 15.19, "prev_close": 15.0}, {"date": "2026-11-05", "close": 15.58, "prev_close": 15.19}]}
    live = E.extract("vix", {}, got_for("vix", {}, {"available": True, "price": 16.4, "change_pct": 5.3, "source": "breeze_ws", "state": "live"}, daily), TODAY)
    assert (live.value, live.change_pct, live.history) == (16.4, 5.3, (15.19, 15.58))
    closed = {"available": True, "price": 15.58, "change_pct": 2.57, "source": "eod", "state": "closed", "ltt": None, "market_date": "2026-11-05"}
    assert E.extract("vix", {}, got_for("vix", {}, closed, daily), TODAY).as_of == "2026-11-05"           # dated by its session
    assert E.extract("price", {"symbol": "NIFTY"}, got_for("price", {"symbol": "NIFTY"}, {"available": False, "state": "stale"}), TODAY).note \
        == "no fresh live quote (stale)"
    eod = E.extract("vix", {}, got_for("vix", {}, daily, live=False), TODAY, live=False)
    assert eod.value == 15.58 and eod.change_pct == pytest.approx((15.58 / 15.19 - 1) * 100, abs=1e-3)
    drv = {"as_of": "2026-11-05", "driver": {"20": {"leader": "ICICIBANK", "changed_from": "HDFCBANK", "change_date": "2026-11-04", "tenure": 2}}}
    i = {"index": "NIFTY"}
    assert E.extract("nifty_driver", i, got_for("nifty_driver", i, drv), TODAY).value == "ICICIBANK"
    empty = {"as_of": None, "driver": {}, "note": "no stored attribution yet (run index_drivers_daily)"}
    assert "no stored attribution" in E.extract("nifty_driver", i, got_for("nifty_driver", i, empty), TODAY).note
    gold = {"rows": [{"day": "2026-10-30", "verdict": "India basis +1.4 % vs duty-paid landed · describes, does not predict"},
                     {"day": "2026-11-05", "verdict": "GLD +2.1 t on the day · India basis +0.9 % vs duty-paid landed · describes, does not predict"}]}
    g = E.extract("gold_health", {}, got_for("gold_health", {}, gold), TODAY)
    assert g.value == "GLD # t on the day | India basis # % vs duty-paid landed" and g.as_of == "2026-11-05"
    assert E.gold_clause_key("India basis +1.4 % vs duty-paid landed") == E.gold_clause_key("India basis −0.3 % vs duty-paid landed")
    dh = {"as_of": "2026-11-06T08:30:00+05:30", "rows": [{"id": "nse_bhavcopy", "state": "fresh"}, {"id": "fii_dii", "state": "amber"},
                                                         {"id": "gold_cot", "state": "red"}, {"id": "x", "state": "gap"}]}
    any_ = {"dataset": "any"}
    assert E.extract("data_stale", any_, got_for("data_stale", any_, dh), TODAY).value == 2.0
    one = {"dataset": "nse_bhavcopy"}
    assert E.extract("data_stale", one, got_for("data_stale", one, dh), TODAY).value == 0.0


def test_a_flag_rule_reads_as_its_two_states_not_a_number() -> None:
    assert E.condition_text(rule("fo_ban:KAYNES", "cross_up")) == "enters NSE's F&O ban list"
    assert E.condition_text(rule("fo_ban:KAYNES", "cross_down")) == "leaves NSE's F&O ban list"
    assert E.condition_text(rule("data_stale:nse_bhavcopy", "cross_up")) == "turns amber or red"
    assert E.condition_text(rule("data_stale:any", "above", 1)) == "at or over 1"            # a count stays a number
    assert E.condition_text(rule("iv_pctile:NIFTY", "above", 80)) == "at or over 80"          # never '80.0'


def test_a_flag_series_reads_as_entry_and_exit() -> None:
    r = rule("fo_ban:KAYNES", "cross_up", repeat="repeat", cooldown_min=0)
    evs = run(r, 0.0, 1.0, 1.0, 0.0)
    assert fired(evs) == [False, True, False, False]
    assert evs[1].fire["text"].startswith("KAYNES is now in NSE's F&O ban list")
    out = run(rule("fo_ban:KAYNES", "cross_down"), 1.0, 0.0)
    assert out[1].fire["text"].startswith("KAYNES is no longer in NSE's F&O ban list")


def test_results_within_n_days_fires_once_per_quarter() -> None:
    r = rule("results_days:TCS", "below", 5, repeat="repeat", cooldown_min=0)
    evs = run(r, 9.0, 6.0, 5.0, 4.0, 0.0, 88.0, 5.0, step=timedelta(days=1), extra={"event_date": "2026-11-09"})
    assert fired(evs) == [False, False, True, False, False, False, True]
    assert "TCS results in 5 days (2026-11-09) (alert: at or under 5 days)" in evs[2].fire["text"]


# ── text helpers ────────────────────────────────────────────────────────────────────────────────────────────
def test_indian_grouping_and_units() -> None:
    assert E.fmt_value(2468512.5, "₹") == "₹24,68,512.50"
    assert E.fmt_value(-3712.23, "₹ cr") == "₹−3,712 cr" and E.fmt_value(14974.68, "₹ cr") == "+₹14,975 cr"
    assert E.fmt_value(1.0, "days") == "1 day" and E.fmt_value(89536.0, "contracts") == "89,536 contracts"
    assert E.fmt_value(1234.5, "contracts") == "1,234.5 contracts" and E.fmt_value(-12.34, "pp") == "−12.3 pp" and E.fmt_value(4.0, "pp") == "+4.0 pp"
    assert E.unit_for("price", {"symbol": "NIFTY"}) == "" and E.unit_for("price", {"symbol": "TCS"}) == "₹"


def test_parse_rule_text_for_telegram() -> None:
    b = E.parse_rule_text("iv_pctile:NIFTY above 80 repeat telegram cooldown=60 note=after results")
    assert b == {"series": "iv_pctile:NIFTY", "op": "above", "value": "80", "repeat": "repeat", "channel": "telegram",
                 "cooldown_min": "60", "note": "after results"}
    assert E.validate_rule(b)["cooldown_min"] == 60
    assert E.parse_rule_text("nifty_driver:NIFTY changed")["op"] == "changed"
    assert E.parse_rule_text("vix change_pct 10% window=1")["value"] == "10"
    for bad in ("", "iv30:NIFTY", "iv30:NIFTY above", "iv30:NIFTY above 18 sometimes"):
        with pytest.raises(E.RuleError):
            E.parse_rule_text(bad)


def test_fires_group_by_symbol_newest_group_first() -> None:
    fires = [{"symbol": "NIFTY", "at": "2026-11-06T10:05"}, {"symbol": "TCS", "at": "2026-11-06T10:04"}, {"symbol": "NIFTY", "at": "2026-11-06T09:30"}]
    g = E.group_fires(fires)
    assert [(x["symbol"], x["count"], x["last_at"]) for x in g] == [("NIFTY", 2, "2026-11-06T10:05"), ("TCS", 1, "2026-11-06T10:04")]


def test_the_catalogue_covers_the_brief() -> None:
    kinds = {k["kind"] for k in E.catalog()}
    assert {"price", "iv30", "iv_pctile", "iv_rank", "iv_rv", "skew25", "straddle", "oi_strike", "oi_wall", "basis", "rollover",
            "rollover_pace", "fo_ban", "results_days", "fii_net", "vix", "nifty_driver", "gold_health", "data_stale"} <= kinds
    assert set(E.KIND_NAMES) == set(E.KINDS) and all(c["name"] for c in E.catalog())       # every kind has a picker name
    for k in E.KINDS.values():                               # every example parses into a valid rule
        series, op, *rest = k.example.split()
        E.validate_rule({"series": series, "op": op, "value": rest[0] if rest else None})


# ── review 6 Nov majors ─────────────────────────────────────────────────────────────────────────────────────────
def _fake_ds(need: E.Need) -> Any:
    """A data-service that knows the drivers store's real keys only: anything else answers what :8001 answered for
    index=NIFTY on 6 Nov (no attribution), exactly as the live route does."""
    pay = RECORDED["payloads"]
    return pay.get(dict(need.params).get("index", ""), pay["NIFTY"])


def test_nifty_driver_asks_the_store_by_its_real_index_names() -> None:
    assert E.needs("nifty_driver", {"index": "NIFTY"}, TODAY)[0].params == (("index", "NIFTY 50"),)
    assert E.needs("nifty_driver", {"index": "BANKNIFTY"}, TODAY)[0].params == (("index", "NIFTY BANK"),)
    assert E.parse_series("nifty_driver:nifty")[1] == {"index": "NIFTY"}                  # the series id keeps the short name
    i = {"index": "NIFTY"}
    need = E.needs("nifty_driver", i, TODAY)[0]
    o = E.extract("nifty_driver", i, {need: _fake_ds(need)}, TODAY)                        # the recorded NIFTY 50 payload
    assert (o.value, o.as_of, o.extra["changed_from"], o.extra["change_date"]) == ("HDFCBANK", "2026-11-05", "RELIANCE", "2026-10-27")
    b = {"index": "BANKNIFTY"}
    nb = E.needs("nifty_driver", b, TODAY)[0]
    ob = E.extract("nifty_driver", b, {nb: _fake_ds(nb)}, TODAY)                           # stored since 4 Nov: no 20-session state
    assert ob.value is None and ob.as_of == "2026-11-05" and "no 20-session driver state stored for NIFTY BANK yet (attribution since 2026-11-04)" in ob.note
    # negative control: the round-1 request (index=NIFTY, the short id) against the same data-service reads nothing, ever
    old = E.Need("ds", "/db/index-drivers", (("index", "NIFTY"),), 900.0)
    o_old = E.extract("nifty_driver", i, {need: _fake_ds(old)}, TODAY)
    assert o_old.value is None and o_old.note == "NIFTY: no stored attribution yet (run index_drivers_daily)"


def test_a_driver_change_fires_on_the_recorded_payload() -> None:
    r = rule("nifty_driver:NIFTY", "changed", repeat="repeat", cooldown_min=0)
    i = {"index": "NIFTY"}
    need = E.needs("nifty_driver", i, TODAY)[0]
    before = E.extract("nifty_driver", i, {need: _fake_ds(need)}, TODAY)
    after_payload = json.loads(json.dumps(RECORDED["payloads"]["NIFTY 50"]))
    after_payload["as_of"] = "2026-11-06"
    after_payload["driver"]["20"].update(leader="ICICIBANK", changed_from="HDFCBANK", change_date="2026-11-06", tenure=1)
    after = E.extract("nifty_driver", i, {need: after_payload}, TODAY)
    evs = run(r, before, after)
    assert fired(evs) == [False, True]
    assert evs[1].fire["text"].startswith("NIFTY 20-session driver changed: HDFCBANK → ICICIBANK · as of 2026-11-06")


ESTIMATORS = {"close-to-close": r"close-to-close|\bRV20[ _]?cc\b|RV20_CC|\(cc\)", "Parkinson": r"parkinson", "Yang-Zhang": r"yang[- ]zhang|\bYZ\b"}


def estimators_named(text: str) -> set[str]:
    return {name for name, rx in ESTIMATORS.items() if re.search(rx, text, re.IGNORECASE)}


def _catalog_row(series_id: str) -> dict[str, str]:
    """The fo_iv catalog row (services/data-service/fo_iv/catalog_seed.py ``_s(...)``) as {id, label, table, column, formula}."""
    src = (ROOT / "services" / "data-service" / "fo_iv" / "catalog_seed.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_s" and node.args and \
                isinstance(node.args[0], ast.Constant) and node.args[0].value == series_id:
            vals = [a.value if isinstance(a, ast.Constant) else None for a in node.args[:6]]
            return dict(zip(("id", "label", "table", "column", "badge", "formula"), vals, strict=True))
    raise AssertionError(f"{series_id} not in the fo_iv catalog")


def test_iv_rv_names_the_estimator_its_column_holds() -> None:
    """Review 6 Nov (M01 again): the iv_rv series said Yang-Zhang while iv_summary_daily.iv_minus_rv20 is IV30 − RV20
    close-to-close. The catalog row is the source of truth; every text the alert shows must name the same estimator."""
    row = _catalog_row("IV_MINUS_RV20")
    assert row["column"] == E.IV_FIELDS["iv_rv"] == "iv_minus_rv20"
    truth = estimators_named(f"{row['label']} {row['formula']}")
    assert truth == {"close-to-close"}, truth
    k = E.KINDS["iv_rv"]
    for text in (k.definition, E.label_for("iv_rv", {"symbol": "NIFTY"}), E.KIND_NAMES["iv_rv"]):
        assert estimators_named(text) == truth, text
    assert k.badge == row["badge"] == "context"
    # negative control: the round-1 definition fails the same check
    assert estimators_named("IV30 minus the 20-session Yang-Zhang realised vol (vol points)") != truth


# ── review 6 Nov minors ─────────────────────────────────────────────────────────────────────────────────────────
def test_oi_at_a_strike_is_in_contracts_like_omon() -> None:
    k = {"symbol": "NIFTY", "strike": 24500.0, "side": "PE"}
    rec = RECORDED["option_chain_nifty"]["payload"]                                        # live, pre-M05: shares + lot 65
    o = E.extract("oi_strike", k, got_for("oi_strike", k, rec), TODAY)
    assert o.value == round(5819840.0 / 65, 1) == 89536.0 and o.change_pct == pytest.approx((5819840.0 / (5819840.0 - 5398380.0) - 1) * 100, abs=1e-3)
    post = json.loads(json.dumps(rec))                                                     # after M05: the chain's own contracts
    post["rows"][0]["pe"].update(oi_contracts=89536.0, oi_chg_contracts=83052.0)
    assert E.extract("oi_strike", k, got_for("oi_strike", k, post), TODAY).value == 89536.0
    assert E.unit_for("oi_strike", k) == "contracts"
    r = rule("oi_strike:NIFTY:24500:PE", "above", 80000)
    assert E.condition_text(r) == "at or over 80,000 contracts"
    assert "89,536 contracts is at or over 80,000 contracts" in E.evaluate(r, o, NOW).fire["text"]
    # negative control: no lot and no oi_contracts → no value (never NSE's shares printed as contracts)
    bare = {k_: v for k_, v in rec.items() if k_ != "lot"}
    miss = E.extract("oi_strike", k, got_for("oi_strike", k, bare), TODAY)
    assert miss.value is None and "lot size" in miss.note


def test_days_to_results_is_dated_by_the_stored_calendar_row_not_today() -> None:
    ev = {"rows": [{"symbol": "HINDALCO", "event_date": "2026-11-06", "kind": "RESULTS", "first_seen": "2026-10-24 18:02:51",
                    "announced_at": "2026-10-24T17:40:00"}]}
    h = {"symbol": "HINDALCO"}
    o = E.extract("results_days", h, got_for("results_days", h, ev), TODAY)
    assert (o.value, o.as_of) == (0.0, "2026-10-24") and o.source.endswith(": the calendar row as first stored that day")
    f = E.evaluate(rule("results_days:HINDALCO", "below", 5), o, NOW).fire
    assert f["as_of"] == "2026-10-24" and "· as of 2026-10-24 ·" in f["text"] and f["text"].count("2026-10-24") == 1   # dated once
    # negative control: the evaluation date is not the as-of; a row with no stored date reads undated
    assert o.as_of != TODAY.isoformat()
    und = E.extract("results_days", h, got_for("results_days", h, {"rows": [{"symbol": "HINDALCO", "event_date": "2026-11-06", "kind": "RESULTS"}]}), TODAY)
    assert und.as_of is None and "undated" in E.evaluate(rule("results_days:HINDALCO", "below", 5), und, NOW).fire["text"]


def test_a_chain_rule_says_when_the_nearest_expiry_rolled() -> None:
    r = rule("oi_wall:NIFTY:CE", "changed", repeat="repeat", cooldown_min=0)
    a = obs(25000.0, extra={"expiry": "2026-11-09"})
    same = obs(25500.0, extra={"expiry": "2026-11-09"})
    rolled = obs(26000.0, extra={"expiry": "2026-11-11"})
    evs = run(r, a, same, rolled)
    assert fired(evs) == [False, True, True]
    assert "rolled" not in evs[1].fire["text"]                                             # negative control: same contract
    assert "the nearest expiry rolled 2026-11-09 → 2026-11-11: the two readings are two contracts" in evs[2].fire["text"]
    assert evs[2].fire["prev_expiry"] == "2026-11-09" and evs[2].fire["expiry"] == "2026-11-11"
    named = rule("oi_wall:NIFTY:CE:2026-11-09", "changed", repeat="repeat", cooldown_min=0)  # a named expiry never rolls
    assert "rolled" not in run(named, a, obs(26000.0, extra={"expiry": "2026-11-11"}))[1].fire["text"]


def test_a_percentile_on_a_short_store_says_how_many_sessions_it_used() -> None:
    r = rule("iv30:NIFTY", "pctile_above", 90)                                             # window 252
    m, why = E.measure(r, obs(95.5, tuple(float(x) for x in range(1, 101))))
    assert m == 95.0 and why == "percentile over 100 of the 252 sessions asked (the store holds 100)"
    assert "percentile 95 of 100 sessions" in E.evaluate(r, obs(95.5, tuple(float(x) for x in range(1, 101))), NOW).fire["text"]
    # negative control: a full window carries no such note
    assert E.measure(r, obs(95.5, tuple(float(x) for x in range(1, 300))))[1] is None
    assert E.validate_rule({"series": "iv30:NIFTY", "op": "pctile_above", "value": 90, "window": E.MAX_WINDOW})["window"] == 399
    with pytest.raises(E.RuleError, match="1–399"):
        E.validate_rule({"series": "iv30:NIFTY", "op": "pctile_above", "value": 90, "window": 400})
    assert E.needs("iv30", {"symbol": "NIFTY"}, TODAY)[0].params == (("symbol", "NIFTY"), ("days", "400"))


ROLL = {"symbol": "NIFTY", "current": {"date": "2026-11-05", "near_expiry": "2026-11-24", "dte": 19, "roll_pct": 21.4},
        "curve_avg": [{"dte": 18, "roll_pct": 9.0}, {"dte": 19, "roll_pct": 8.2}], "avg3": 78.3, "history": [], "updating": False}


def test_rollover_pace_against_the_three_cycle_average_at_the_same_dte() -> None:
    s = {"symbol": "NIFTY"}
    need = E.needs("rollover_pace", s, TODAY)[0]
    assert need == E.needs("rollover", s, TODAY)[0] and dict(need.params)["cycles"] == "3"   # one shared read, 3 cycles
    o = E.extract("rollover_pace", s, {need: ROLL}, TODAY)
    assert o.value == pytest.approx(13.2) and o.as_of == "2026-11-05" and "19 days to expiry: 21.4 % vs 8.2 %" in o.source
    f = E.evaluate(rule("rollover_pace:NIFTY", "above", 10), o, NOW).fire
    assert f and f["badge"] == "context" and f["text"].startswith("NIFTY rollover vs the 3-cycle average at the same DTE +13.2 pp is at or over +10.0 pp")
    # negative control: no earlier cycle at this DTE → no value (never the final-rollover average avg3 instead)
    off = {**ROLL, "current": {**ROLL["current"], "dte": 23}}
    assert E.extract("rollover_pace", s, {need: off}, TODAY).value is None


def test_reads_that_start_a_refresh_are_flagged_and_a_skip_reads_as_no_value() -> None:
    flagged = {n.path for k in E.KINDS for n in E.needs(k, {"symbol": "NIFTY", "strike": 24500.0, "side": "CE", "index": "NIFTY",
                                                             "dataset": "any"}, TODAY) if n.side_effect}
    assert flagged == {"/db/fii-dii-cash", "/db/events", "/db/surveillance", "/db/fo/rollover"}
    k = {"symbol": "KAYNES"}
    o = E.extract("fo_ban", k, got_for("fo_ban", k, E.ReadSkipped("skipped inside the 18:30–21:15 IST freeze window")), TODAY)
    assert o.value is None and o.note.startswith("skipped inside") and "read failed" not in o.note
    # negative control: a real failure still says so
    assert E.extract("fo_ban", k, got_for("fo_ban", k, RuntimeError("503")), TODAY).note.startswith("read failed")
