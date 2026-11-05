"""Wave 1d (5 Nov 2026, after the 43-page review) — every data-service rule that changed, each with a negative control:

1. the ICICI master's band midpoint is the settlement of the session BEFORE its OI session (the blocker), re-keyed by
   every read and by the MCX basis;
2. the MCX settlement proxy: last-30-minute VWAP of Breeze 1-minute bars (``mcx_close``), its group, budget and PIT;
3. the accuracy log's stale-baseline test against that proxy (0.6 %);
4. purity-correct landed references; fresher macro twins (Brent); per-point partial bars; Yahoo volume repeats;
5. the EFP 20-session average; every LBMA turnover period kept; the catalog rows live without a re-seed;
6. event times on the session's real clock (MCX 23:55 in US winter; COMEX LTD 12:30 CT = 00:00 IST next day)."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from _support import FIXTURES, G_CME, read
from gold import (
    catalog_seed,
    db,
    derive,
    ingest_cme,
    ingest_india,
    ingest_local,
    ingest_physical,
    jobs,
    mcx_close,
    pit,
    reads,
)

GRAMS = 31.1034768
BARS = json.loads(read(FIXTURES / "breeze_mcx_gold_dec26_1m_20261103_04.json"))     # real Breeze 1-min bars, GOLD DEC-26
DEC = date(2026, 12, 4)
FEB = date(2027, 2, 5)
TUE, WED, THU = date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)
AFTER_WED_CLOSE = datetime(2026, 11, 4, 18, 40)          # 00:10 IST Thu 5 Nov (UTC-naive)
THU_MORNING = datetime(2026, 11, 5, 3, 0)                # 08:30 IST Thu 5 Nov


def _master_row(trade_date: date, expiry: date, lo: float, hi: float, oi: int, *, symbol: str = "GOLD", release: datetime | None = None,
                session_date: date | None = None) -> dict:
    rel = release or datetime.combine(trade_date + timedelta(days=1), datetime.min.time()) + timedelta(hours=2)   # 07:30 IST next day
    return {"trade_date": trade_date, "exchange": "MCX", "symbol": symbol, "expiry": expiry, "settle": round((lo + hi) / 2, 2), "band_lo": lo,
            "band_hi": hi, "open_interest": oi, "unit": "INR/10g", "source": "icici_master_band", "quality": "proxy",
            "session_date": session_date or ingest_india.band_session(trade_date), "release_at": rel, "first_seen_at": rel}


@pytest.fixture
def masters(store):
    """The two real files of the blocker: published Wed 4 Nov (OI of Tue 3 Nov, band centred on Mon 2 Nov's 1,40,186) and
    Thu 5 Nov (OI of Wed 4 Nov, band 1,35,269–1,43,635 centred on Tue 3 Nov's 1,39,452)."""
    db.upsert(store, "gold_curve", pd.DataFrame([
        _master_row(TUE, DEC, 135980.0, 144392.0, 16282), _master_row(TUE, FEB, 138638.0, 147214.0, 1180),
        _master_row(WED, DEC, 135269.0, 143635.0, 16110), _master_row(WED, FEB, 137782.0, 146304.0, 0)]))
    return store


def _store_vwap(store, session: date, value: float, lots: int = 150, expiry: date = DEC, family: str = "GOLD", now: datetime | None = None):
    res = {"vwap": value, "lots": lots}
    pit.upsert_series(store, mcx_close.frame(family, expiry, session, res, now=now or datetime(2026, 11, 5, 18, 30)),
                      now=now or datetime(2026, 11, 5, 18, 30))


# ── 1. the band belongs to the session before the OI ─────────────────────────────────────────────────

@pytest.mark.parametrize("published,oi_session,band_session", [
    (date(2026, 10, 26), date(2026, 10, 23), date(2026, 10, 22)),    # Monday file: Friday's OI, THURSDAY's settlement (1,43,309 = 1,43,308)
    (date(2026, 10, 27), date(2026, 10, 26), date(2026, 10, 23)),    # 1,42,024 = Fri 23 Oct 1,42,036 (across the weekend)
    (date(2026, 10, 28), date(2026, 10, 27), date(2026, 10, 26)),    # 1,43,073 = Mon 26 Oct 1,43,069
    (date(2026, 10, 30), date(2026, 10, 29), date(2026, 10, 28)),    # 1,43,705 = Wed 28 Oct 1,43,693
    (date(2026, 11, 4), TUE, date(2026, 11, 2)),                     # 1,40,186 = Mon 2 Nov 1,40,190
    (THU, WED, TUE),                                                 # 1,39,452 = Tue 3 Nov 1,39,448 — the page said 'Wed 04 Nov'
    (date(2026, 10, 5), date(2026, 10, 1), date(2026, 9, 30)),       # Fri 2 Oct full holiday skipped
])
def test_band_session_is_one_session_before_the_oi_session(published, oi_session, band_session):
    assert ingest_india.previous_mcx_session(published) == oi_session
    assert ingest_india.band_session(oi_session) == band_session
    assert ingest_india.band_session(oi_session) != oi_session                     # negative control: the pre-1d label


def test_parse_master_keeps_the_raw_band_and_labels_its_settlement_session(now):
    df = ingest_india.parse_mcx_master(read(FIXTURES / "MCXScripMaster_gold_20261026.txt"), date(2026, 10, 26), now=now)
    g = df[(df["symbol"] == "GOLD") & (df["expiry"] == DEC)].iloc[0]
    assert (g["trade_date"], g["session_date"], g["band_lo"], g["band_hi"], g["settle"], g["open_interest"]) == (
        date(2026, 10, 23), date(2026, 10, 22), 139010.0, 147608.0, 143309.0, 16217)


def test_relabel_band_sessions_is_idempotent_and_touches_only_old_rows(store):
    old = _master_row(WED, DEC, 135269.0, 143635.0, 16110, session_date=WED)          # written before wave 1d
    new = _master_row(TUE, DEC, 135980.0, 144392.0, 16282)                             # already labelled (session_date Mon 2 Nov)
    db.upsert(store, "gold_curve", pd.DataFrame([old, new]))
    assert ingest_india.relabel_band_sessions(store) == {"relabelled_dates": 1}
    rows = {db.to_date(r.trade_date): db.to_date(r.session_date) for r in db.query_df(store, "SELECT * FROM gold_curve").itertuples()}
    assert rows == {WED: TUE, TUE: date(2026, 11, 2)}
    assert ingest_india.relabel_band_sessions(store) == {"relabelled_dates": 0}       # second run: nothing left to relabel
    assert db.scalar(store, "SELECT settle FROM gold_curve WHERE trade_date = ?", [WED]) == 139452.0   # values never move


# ── 2. reads re-key the band to its own session ─────────────────────────────────────────────────────

def test_curve_rekeys_settlement_and_never_labels_the_band_with_the_oi_session(masters):
    cur = reads.curve(masters, exchange="MCX", day=WED)
    dec = next(r for r in cur["rows"] if r["expiry"] == "2026-12-04")
    assert (dec["oi_session"], dec["open_interest"], dec["band_midpoint"], dec["band_session"], dec["band_session_label"]) == (
        "2026-11-04", 16110, 139452.0, "2026-11-03", "Tue 03 Nov settlement")
    # no VWAP30 and no later file: Wed 4 Nov's settlement is UNKNOWN to the store — never the band's 1,39,452
    assert dec["settle"] is None and dec["settle_source"] is None and dec["settle_session"] is None
    hist = {(r["trade_date"], r["expiry"]): r for r in reads.curve_history(masters, exchange="MCX", symbol="GOLD", days=4000)["rows"]}
    tue = hist[("2026-11-03", "2026-12-04")]
    assert (tue["settle"], tue["settle_source"], tue["settle_quality"], tue["settle_session"]) == (139452.0, "band_midpoint", "band_proxy",
                                                                                                    "2026-11-03")
    assert tue["settle"] != tue["band_midpoint"] == 140186.0                            # negative control: its own band is Mon 2 Nov's
    _store_vwap(masters, WED, 143236.81)
    dec = next(r for r in reads.curve(masters, exchange="MCX", day=WED)["rows"] if r["expiry"] == "2026-12-04")
    assert (dec["settle"], dec["settle_source"], dec["settle_quality"], dec["settle_session_label"], dec["vwap30_lots"]) == (
        143236.81, "breeze_vwap30", "vwap30_proxy", "Wed 04 Nov settlement", 150)


def test_mcx_settlement_contract_block(masters):
    s = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=THU, asof=THU_MORNING)
    assert (s["settlement"], s["settlement_source"], s["settlement_session"], s["settlement_session_label"], s["settlement_quality"]) == (
        139452.0, "band_midpoint", "2026-11-03", "Tue 03 Nov settlement", "band_proxy")
    assert s["band_midpoint"] == 139452.0 and s["band_session"] == "2026-11-03" and s["settlement_check"] is None
    # the same-session pair agrees (Tue: band 1,39,452 vs VWAP30 1,39,448) → not flagged
    _store_vwap(masters, TUE, 139448.0)
    only_tue = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=THU, asof=THU_MORNING)
    assert only_tue["settlement_source"] == "breeze_vwap30" and only_tue["settlement_session"] == "2026-11-03"
    assert only_tue["band_same_session_pct"] == pytest.approx(0.003, abs=0.001) and only_tue["settlement_check"]["flagged"] is False
    _store_vwap(masters, WED, 143236.81)
    s = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=THU, asof=THU_MORNING)
    assert (s["settlement"], s["settlement_source"], s["settlement_session"], s["settlement_session_label"], s["settlement_quality"]) == (
        143236.81, "breeze_vwap30", "2026-11-04", "Wed 04 Nov settlement", "vwap30_proxy")
    # the newest band (Tue 3 Nov's 1,39,452) against Wed 4 Nov's proxy: −2.64 % → flagged (the blocker, caught by the store)
    assert s["settlement_check"] == {"band_vs_vwap30_pct": pytest.approx(-2.642, abs=0.001), "flagged": True, "threshold_pct": 0.6}
    # PIT: at 17:30 IST Wed the VWAP30 of Wed (released at its 23:55 close) and the Thu file are unknown — the read gives
    # the newest proxy it could have had (Tue's VWAP30), checked against the band visible then (Mon 2 Nov's 1,40,186)
    early = reads.mcx_settlement(masters, symbol="GOLD", expiry=DEC, day=WED, asof=datetime(2026, 11, 4, 12, 0))
    assert (early["settlement_session"], early["settlement_source"], early["band_session"]) == ("2026-11-03", "breeze_vwap30", "2026-11-02")
    assert early["settlement_check"]["band_vs_vwap30_pct"] == pytest.approx(0.529, abs=0.001) and early["band_same_session_pct"] is None
    assert reads.mcx_settlement(masters, symbol="GOLD", day=THU)["expiry"] == "2026-12-04"               # front by default
    assert reads.mcx_settlement(masters, symbol="GOLDPETAL", day=THU)["settlement"] is None


# ── 3. the VWAP30 proxy and its group ────────────────────────────────────────────────────────────────

def test_vwap30_of_real_breeze_bars_matches_the_pm_numbers():
    close = mcx_close.session_close(TUE)
    assert close is not None and f"{close:%H:%M}" == "23:55"                         # US winter (since 1 Nov)
    tue = mcx_close.vwap30(BARS["2026-11-03"], close)
    wed = mcx_close.vwap30(BARS["2026-11-04"], mcx_close.session_close(WED))
    assert tue["vwap"] == pytest.approx(139448.0, abs=0.05) and wed["vwap"] == pytest.approx(143236.8, abs=0.05)
    assert (tue["window"], wed["last_close"], wed["last_oi"]) == ("23:25–23:55 IST", 143293.0, 16110)
    # negative controls: the summer clock (23:00–23:30) or an empty window is not this number
    summer = datetime(2026, 11, 4, 23, 30, tzinfo=mcx_close.IST)
    assert mcx_close.vwap30(BARS["2026-11-04"], summer) is None or mcx_close.vwap30(BARS["2026-11-04"], summer)["vwap"] != wed["vwap"]
    assert mcx_close.vwap30([dict(b, volume=0) for b in BARS["2026-11-04"]], mcx_close.session_close(WED)) is None
    assert f"{mcx_close.session_close(date(2026, 10, 28)):%H:%M}" == "23:30" and mcx_close.session_close(date(2026, 11, 7)) is None


@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 11, 4, 18, 26), TUE),       # 23:56 IST Wed: the close + 2 min has not passed
    (datetime(2026, 11, 4, 18, 27), WED),       # 23:57 IST Wed
    (datetime(2026, 11, 7, 6, 0), date(2026, 11, 6)),     # Saturday: Friday
    (datetime(2026, 11, 9, 2, 0), date(2026, 11, 6)),     # Monday 07:30 IST: Friday
])
def test_latest_completed_session(now, expected):
    assert mcx_close.latest_completed_session(now) == expected


class FakeBreeze:
    def __init__(self, by_day: dict[str, list[dict]] | None = None, status: int = 200) -> None:
        self.by_day, self.status, self.calls = by_day or {}, status, []

    def get_historical_data_v2(self, **kw):
        self.calls.append(kw)
        if self.status != 200:
            return {"Status": self.status, "Error": "Internal Server Error", "Success": None}
        return {"Status": 200, "Error": None, "Success": self.by_day.get(kw["from_date"][:10], []) if kw["expiry_date"].startswith("2026-12-04")
                else []}


def test_vwap30_group_stores_pit_rows_once_and_is_honest_without_a_session(masters):
    fake = FakeBreeze(BARS)
    res = mcx_close.run(masters, lambda: fake, now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None)
    # contracts: DEC (front) — FEB has OI 0 on the Wed file, so it is not averaged (negative control)
    assert res["status"] == "ok" and res["breeze_calls"] == 1 and res["sessions"] == ["2026-11-04"] and res["inserted"] == 2
    kw = fake.calls[0]
    assert (kw["stock_code"], kw["exchange_code"], kw["interval"], kw["from_date"], kw["to_date"]) == (
        "GOLD", "MCX", "1minute", "2026-11-04T23:15:00.000Z", "2026-11-04T23:59:00.000Z")
    rows = db.query_df(masters, "SELECT * FROM gold_series WHERE series_id LIKE 'MCX_GOLD_202612_VWAP30%' ORDER BY series_id")
    assert list(rows["series_id"]) == ["MCX_GOLD_202612_VWAP30", "MCX_GOLD_202612_VWAP30_LOTS"]
    assert (rows["source"] == "breeze_1m_vwap30").all() and (rows["quality"] == "proxy").all()
    assert (rows["release_at"] == pd.Timestamp("2026-11-04 18:25")).all()               # 23:55 IST, the session close
    assert rows.iloc[0]["value"] == pytest.approx(143236.8, abs=0.05) and db.to_date(rows.iloc[0]["report_date"]) == WED
    again = mcx_close.run(masters, lambda: fake, now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None)
    assert again["breeze_calls"] == 0 and again["already_stored"] == 1 and len(fake.calls) == 1          # stored → zero Breeze calls
    none = mcx_close.run(masters, lambda: None, now=AFTER_WED_CLOSE, sessions=[TUE])
    assert none["status"] == "no_session" and none["planned"] == 2 and "Breeze session" in none["reason"]   # Tue: DEC + FEB (OI 1,180)
    back = mcx_close.run(masters, lambda: fake, now=AFTER_WED_CLOSE, backfill_from=date(2026, 11, 2), pace_s=0, sleep=lambda s: None)
    assert back["sessions"] == ["2026-11-02", "2026-11-03", "2026-11-04"] and back["already_stored"] == 1
    tue = [c for c in back["contracts"] if c["session"] == "2026-11-03" and c["status"] == "ok"]
    assert tue and tue[0]["vwap"] == pytest.approx(139448.0, abs=0.05)


def test_vwap30_group_stops_on_budget_and_after_three_failures(masters, monkeypatch):
    from shared import breeze_budget

    for d in (date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2)):
        db.upsert(masters, "gold_curve", pd.DataFrame([_master_row(d, DEC, 139000.0, 147000.0, 15000)]))
    bad = FakeBreeze(status=500)
    res = mcx_close.run(masters, lambda: bad, now=AFTER_WED_CLOSE, backfill_from=date(2026, 10, 28), pace_s=0, sleep=lambda s: None)
    assert res["status"] == "degraded" and res["breeze_calls"] == 3 and len(bad.calls) == 3          # stopped at three in a row
    assert all(c["status"] == "error" and "500" in c["error"] for c in res["contracts"])

    class Refuse:
        def guard(self, caller, method=""):
            assert caller == "data-service.gold_vwap30" and method == "get_historical_data_v2"
            raise breeze_budget.BudgetExceeded(breeze_budget.Decision(False, "day cap reached", caller, method, 0, 4000, 0, 60, 4000, None, 1.0))

    monkeypatch.setattr(breeze_budget, "ledger", lambda: Refuse())
    fake = FakeBreeze(BARS)
    res = mcx_close.run(masters, lambda: fake, now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None)
    assert res["status"] == "budget" and res["breeze_calls"] == 0 and fake.calls == []           # refused BEFORE the SDK ran


def test_vwap30_group_registered_with_the_breeze_getter(store, now):
    assert jobs.resolve("mcx_close") == "mcx_close_vwap30" and jobs.GROUPS["mcx_close_vwap30"].cadence == "always"
    res = jobs.run_job(store, None, "gold_mcx_close", ["mcx_close_vwap30"], now=AFTER_WED_CLOSE)       # no getter (tests / no session)
    g = res["groups"]["mcx_close_vwap30"]
    assert g["status"] == "no_session" and g["planned"] == 2                            # the computed GOLD and GOLDM fronts, no master
    fake = FakeBreeze(BARS)
    res = jobs.run_job(store, None, "gold_mcx_close", ["mcx_close_vwap30"], now=AFTER_WED_CLOSE, breeze=lambda: fake,
                       params={"max_calls": 1})
    assert res["groups"]["mcx_close_vwap30"]["status"] == "capped" and len(fake.calls) == 1        # the per-run call cap holds


# ── 4. the accuracy log's stale test, purity, the basis ──────────────────────────────────────────────

def test_accuracy_log_flags_a_band_baseline_against_the_vwap30(store, now):
    _store_vwap(store, TUE, 139448.0)
    _store_vwap(store, WED, 143236.81)
    ingest_local.upsert_preopen_log(store, {"day": THU, "contract": "GOLD DEC-26", "baseline": 139452.0, "actual_open": 145153.0,
                                            "baseline_source": "MCX settlement 04 Nov (price-band midpoint)", "error": 3256, "naive_error": 5701},
                                    now=now)
    ingest_local.upsert_preopen_log(store, {"day": WED, "contract": "GOLD DEC-26", "baseline": 139448.0, "actual_open": 140000.0,
                                            "baseline_source": "VWAP30 proxy", "error": 10, "naive_error": 552}, now=now)
    log = reads.log(store, days=3650)
    by_day = {r["day"]: r for r in log["rows"]}
    thu, wed = by_day["2026-11-05"], by_day["2026-11-04"]
    assert (thu["settle_vwap30_session"], thu["stale_baseline_vwap30"], thu["baseline_session_real"]) == ("2026-11-04", True, "2026-11-03")
    assert thu["baseline_vs_vwap30_pct"] == pytest.approx(-2.642, abs=0.001) and thu["naive_error_vwap30"] == pytest.approx(1916.19, abs=0.01)
    assert wed["stale_baseline_vwap30"] is False and "baseline_session_real" not in wed          # negative control: a right baseline
    acc = log["accuracy"]
    assert (acc["checked_days_vwap30"], acc["stale_days_vwap30"]) == (2, 1) and "0.6 %" in acc["stale_rule"]


def test_landed_factor_per_purity():
    """PM decision D1: landed (COMEX per FINE oz × INR) is the price of fine gold; purity P compares with landed × P/1000,
    and the purity / quotation grams come from shared/mcx_specs (the one source ui-api reads too)."""
    from shared import mcx_specs

    assert ingest_india.landed_factor("GOLD") == (pytest.approx(0.995), "landed_995")
    assert ingest_india.landed_factor("GOLDM") == (pytest.approx(0.995), "landed_995")
    assert ingest_india.landed_factor("GOLDTEN") == (pytest.approx(0.999), "landed_999")
    assert ingest_india.landed_factor("GOLDPETAL") == (pytest.approx(0.999 / 10), "landed_999")          # quoted per 1 g
    assert ingest_india.landed_factor("GOLDGUINEA") == (pytest.approx(0.999 * 0.8), "landed_999")         # 999 (D1), per 8 g
    for fam, spec in mcx_specs.CONTRACTS.items():                                                       # one source of truth
        assert ingest_india.MCX_PURITY[fam] == int(spec.purity) and ingest_india.QUOTE_GRAMS[fam] == spec.quote_per_grams
    # negative controls: GOLD is not the reference (the round-1 995 convention), the guinea is not priced as 916 (22 ct)
    assert ingest_india.landed_factor("GOLD")[0] != pytest.approx(1.0)
    assert ingest_india.landed_factor("GOLDGUINEA")[0] != pytest.approx(0.916 * 0.8) and ingest_india.landed_factor("GOLDGUINEA")[1] != "landed_916"
    assert ingest_india.landed_factor("GOLDTEN")[0] < 1.0                                               # 999 is never above fine gold
    # D3: a ₹/1 g or ₹/8 g price sits beside ₹/10 g values only scaled (5 Nov: GUINEA ₹1,12,211 / 8 g = ₹1,40,264 / 10 g)
    assert ingest_india.per_10g(112211.0, "GOLDGUINEA") == pytest.approx(140263.75) and ingest_india.per_10g(14033.0, "GOLDPETAL") == 140330.0
    assert ingest_india.per_10g(139452.0, "GOLD") == 139452.0 and ingest_india.per_10g(None, "GOLD") is None


def test_basis_uses_the_vwap30_of_each_session_and_the_band_of_the_session_before(store, now):
    for sym, px in (("GC=F", {TUE: 3940.4, WED: 4070.8}), ("INR=X", {TUE: 94.6, WED: 94.63})):
        db.upsert(store, "gold_daily_bars", pd.DataFrame([{"trade_date": d, "symbol": sym, "open": c, "high": c, "low": c, "close": c,
                                                           "adj_close": c, "volume": 0, "source": "yahoo", "first_seen_at": now}
                                                          for d, c in px.items()]))
    db.upsert(store, "gold_curve", pd.DataFrame([_master_row(WED, DEC, 135269.0, 143635.0, 16110, release=now)]))
    _store_vwap(store, WED, 143236.81, now=now)
    front = mcx_close.session_settlements(store, "GOLD", asof=now)
    assert [(db.to_date(r.session), r.settle, r.source) for r in front.itertuples()] == [(TUE, 139452.0, "band_midpoint"),
                                                                                         (WED, 143236.81, "breeze_vwap30")]
    derive.derive_india(store, now=now)
    b = {db.to_date(r.report_date): (r.value, r.quality) for r in pit.asof_series(store, ["MCX_BASIS_PCT"]).itertuples()}
    dp = {d: c * i / GRAMS * 10 * 1.15 * 0.995 for d, c, i in ((TUE, 3940.4, 94.6), (WED, 4070.8, 94.63))}   # 995 fine (D1)
    assert b[TUE][0] == pytest.approx((139452.0 / dp[TUE] - 1) * 100, abs=0.01) and b[TUE][1] == "derived_band"
    assert b[WED][0] == pytest.approx((143236.81 / dp[WED] - 1) * 100, abs=0.01) and b[WED][1] == "derived_vwap30"
    assert b[WED][0] != pytest.approx((139452.0 / dp[WED] - 1) * 100, abs=0.5)        # negative control: the stale band on Wed
    assert b[WED][0] != pytest.approx((143236.81 / (dp[WED] / 0.995) - 1) * 100, abs=0.1)    # negative control: GOLD vs fine gold


# ── 5. macro twins, partial bars, volume repeats ────────────────────────────────────────────────────

def _bar(sym, d, close, seen, volume=0):
    return {"trade_date": d, "symbol": sym, "open": close, "high": close, "low": close, "close": close, "adj_close": close, "volume": volume,
            "source": "yahoo", "first_seen_at": seen}


def test_fresher_twin_partial_points_and_age(store):
    asof = datetime(2026, 11, 5, 16, 0)
    pit.upsert_series(store, pit.series_frame("FRED_DCOILBRENTEU", [(date(2026, 11, 2), 107.39), (TUE, 107.03)], freq="D", source="fred_csv",
                                              now=asof), now=asof)
    db.upsert(store, "gold_daily_bars", pd.DataFrame([_bar("BZ=F", TUE, 96.1, datetime(2026, 11, 4, 22, 5)),
                                                      _bar("BZ=F", WED, 96.99, datetime(2026, 11, 4, 21, 40))]))   # fetched before the 22:00 UTC close
    reads.invalidate_catalog_cache()
    s = reads.series(store, ["FRED_DCOILBRENTEU", "BRENT_FRONT"], start=date(2026, 10, 1), asof=asof)["series"]
    fred, bz = s[0], s[1]
    assert fred["fresher_twin"]["series_id"] == "BRENT_FRONT" and fred["fresher_twin"]["report_date"] == "2026-11-04"
    assert fred["fresher_twin"]["ahead_days"] == 1 and fred["fresher_twin"]["partial"] is True and fred["age_days"] == 2
    assert bz["points"][-1] == {"report_date": "2026-11-04", "value": 96.99, "release_at": "2026-11-04T21:40:00+00:00", "partial": True}
    assert "partial" not in bz["points"][0] and bz["last_point_partial"] is True and bz["catalog"]["verdict"] == "PUBLISH-CONTEXT"
    assert bz["fresher_twin"] is None                                                    # negative control: FRED is older, not fresher


def test_bars_flag_a_repeated_volume(store, now):
    db.upsert(store, "gold_daily_bars", pd.DataFrame([_bar("GC=F", date(2026, 10, 30), 3898.9, now, 237470),
                                                      _bar("GC=F", date(2026, 11, 2), 3969.6, now, 172512),
                                                      _bar("GC=F", TUE, 3940.4, now, 172512), _bar("GC=F", WED, 4070.8, now, 225876)]))
    rows = reads.bars(store, symbol="GC=F", start=date(2026, 10, 1))["rows"]
    assert [r["volume_repeat"] for r in rows] == [False, False, True, False]


# ── 6. EFP average, LBMA history, the catalog ────────────────────────────────────────────────────────

def _efrp(store, days: list[date], now):
    db.upsert(store, "gold_cme_efrp", pd.DataFrame([{"process_date": d, "product": "GOLD", "product_line": "COMEX", "txn_type": "EFP",
                                                     "contract_expiry": "DEC26", "fut_or_opt": "F", "round_turns": 100 * (i + 1), "row_no": 1,
                                                     "first_seen_at": now} for i, d in enumerate(days)]))


def test_efrp_twenty_session_average(store, now):
    days = [d for d in (date(2026, 9, 28) + timedelta(days=i) for i in range(40)) if d.weekday() < 5][:25]
    _efrp(store, days[:5], now)
    a = reads.efrp_avg(store)
    assert a["avg_round_turns"] is None and a["sessions"] == 4 and "5 prior" in a["note"]           # 4 prior sessions: not enough
    _efrp(store, days, now)
    a = reads.efrp_avg(store)
    prior = [100 * (i + 1) for i in range(4, 24)]                                       # the 20 sessions BEFORE the latest (2,500)
    assert a["latest_round_turns"] == 2500 and a["sessions"] == 20 and a["avg_round_turns"] == pytest.approx(sum(prior) / 20)
    assert a["window"] == {"from": days[4].isoformat(), "to": days[23].isoformat()} and a["note"] is None
    assert reads.cme_efrp(store, start=days[-3])["avg_20d"] == a                         # independent of the caller's window


def test_lbma_turnover_keeps_every_period_and_matches_tonights_page(store, now):
    page = read(FIXTURES / "lbma_trade_turnover_20261105_excerpt.html")
    df = ingest_physical.parse_lbma_turnover(page, now=now)
    gold = df[df["series_id"] == "LBMA_OTC_TURNOVER_USD_BN"]
    assert list(gold["report_date"]) == [date(2026, 10, 16)] and gold["value"].iloc[0] == 964.17
    two = page.replace("period ending 16 October 2026.", "period ending 23 October 2026.") + page
    df2 = ingest_physical.parse_lbma_turnover(two, now=now)
    assert sorted(df2[df2["series_id"] == "LBMA_OTC_TURNOVER_USD_BN"]["report_date"]) == [date(2026, 10, 16), date(2026, 10, 23)]
    ingest_physical.ingest_series(store, df, now=now)
    ingest_physical.ingest_series(store, df2, now=now + timedelta(days=7))
    hist = pit.asof_series(store, ["LBMA_OTC_TURNOVER_USD_BN"])
    assert len(hist) == 2                                                               # history grows, never replaced
    assert ingest_physical.parse_lbma_turnover("<p>no headline</p>", now=now).empty


def test_catalog_code_rows_are_live_without_a_reseed_and_vwap_ids_resolve(store):
    catalog_seed.seed(store)
    db.execute(store, "DELETE FROM gold_series_catalog WHERE series_id IN ('SGE_AUTD_OI', 'SGE_AUTD_DIRECTION', 'SHFE_AU_FRONT_OI')")
    reads.invalidate_catalog_cache()
    ids = {r["series_id"] for r in reads.catalog_rows(store)}
    assert {"SGE_AUTD_OI", "SGE_AUTD_DIRECTION", "SHFE_AU_FRONT_OI", "MCX_GOLD_VWAP30", "BRENT_FRONT"} <= ids
    cat = reads._catalog_map(store)
    assert reads.catalog_row(cat, "MCX_GOLD_202612_VWAP30")["series_id"] == "MCX_GOLD_VWAP30"
    assert reads.catalog_row(cat, "MCX_GOLDPETAL_202611_VWAP30_LOTS")["unit"] == "lots"
    assert reads.catalog_row(cat, "MCX_SILVER_202612_VWAP30") == {}                     # negative control: not a gold family
    jobs._CATALOG_CHECKED.clear()
    assert jobs.ensure_catalog(store) == len(catalog_seed.build_rows())                 # the missing rows are seeded once
    assert jobs.ensure_catalog(store) == 0
    reads.invalidate_catalog_cache()


# ── 7. event times on the real session clock ─────────────────────────────────────────────────────────

def test_ltd_end_time_in_ist_is_dst_correct():
    assert ingest_local.ltd_end_ist(date(2026, 12, 29), "12:30:00 PM") == (date(2026, 12, 30), "00:00", "12:30 CT")   # US winter
    assert ingest_local.ltd_end_ist(date(2027, 6, 28), "12:30:00 PM") == (date(2027, 6, 28), "23:00", "12:30 CT")     # US summer
    assert ingest_local.ltd_end_ist(date(2026, 11, 25), None)[1] == "00:00"


def test_mcx_expiry_time_and_stale_compiled_rows_dropped(store, now):
    ingest_cme.ingest_prf(store, read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now, ref_prices={"GC": 4007.9})
    stale = {"event_date": date(2026, 12, 29), "time_ist": "23:00", "kind": "COMEX_LTD", "name": "COMEX GC 2026-12 last trading day",
             "detail": "old", "country": "US", "impact": "context", "in_session": None, "source": "cme_prf", "first_seen_at": now}
    other = dict(stale, kind="US_DATA", name="Non-Farm Employment Change", source="forexfactory", event_date=date(2026, 11, 6))
    past = dict(stale, kind="MCX_EXPIRY", name="MCX GOLDTEN Sep-26 expiry", source="rule:mcx_specs", event_date=date(2026, 9, 30))
    db.upsert(store, "gold_events", pd.DataFrame([stale, other, past]))
    res = ingest_local.ingest_events(store, now=now)
    assert res["removed_stale"] >= 1
    ev = db.query_df(store, "SELECT * FROM gold_events")
    keys = {(db.to_date(r.event_date), r.kind, r.name): r.time_ist for r in ev.itertuples()}
    assert (date(2026, 12, 29), "COMEX_LTD", "COMEX GC 2026-12 last trading day") not in keys                 # the old key is gone
    assert keys[(date(2026, 12, 30), "COMEX_LTD", "COMEX GC 2026-12 last trading day")] == "00:00"
    assert (date(2026, 11, 6), "US_DATA", "Non-Farm Employment Change") in keys                                # other sources untouched
    assert (date(2026, 9, 30), "MCX_EXPIRY", "MCX GOLDTEN Sep-26 expiry") in keys                              # the past untouched
    assert keys[(date(2026, 11, 5), "MCX_EXPIRY", "MCX GOLDM Nov-26 expiry")] == "23:55"                       # not 23:30 (US winter)
    assert keys[(date(2026, 10, 30), "MCX_EXPIRY", "MCX GOLDTEN Oct-26 expiry")] == "23:30"                    # still US summer on 30 Oct


# ── 8. history line, Fed-path horizons, the router ───────────────────────────────────────────────────

def test_history_carries_one_settlement_per_session_including_skipped_ones(masters):
    _store_vwap(masters, WED, 143236.81)
    h = reads.curve_history(masters, exchange="MCX", symbol="GOLD", days=4000)
    line = [(s["session"], s["settle"], s["quality"]) for s in h["session_settlements"]]
    # Mon 2 Nov has no master row (the OI file was skipped) but its settlement arrives with Tue's band (1,40,186)
    assert line == [("2026-11-02", 140186.0, "band_proxy"), ("2026-11-03", 139452.0, "band_proxy"), ("2026-11-04", 143236.81, "vwap30_proxy")]


def test_fed_path_rows_say_they_are_imm_horizons(store, now):
    db.upsert(store, "gold_fed_path", pd.DataFrame([{"as_of": TUE, "meeting": m, "prob_hike": 80.0, "first_seen_at": now,
                                                      "source": "atlanta_fed_mpt"} for m in (date(2026, 12, 16), date(2026, 12, 9))]))
    rows = {r["meeting"]: r for r in reads.fed_path(store, asof=WED)["rows"]}
    assert rows["2026-12-16"]["horizon_kind"] == "imm_third_wednesday" and "not an FOMC date" in rows["2026-12-16"]["horizon_label"]
    assert rows["2026-12-09"]["horizon_kind"] == "tracker_date"                         # negative control: not a third Wednesday


def test_router_serves_the_settlement_and_hands_the_breeze_getter_to_the_job(masters):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gold import api as gold_api

    seen: list[object] = []

    def submit(kind, fn):
        return {"job_id": "j1", "kind": kind, "status": "done", "result": fn(lambda a, b: None)}

    fake = FakeBreeze(BARS)
    gold_api.configure(get_store=lambda: masters, submit=submit, get_breeze=lambda: seen.append(1) or fake)
    app = FastAPI()
    app.include_router(gold_api.router)
    c = TestClient(app)
    s = c.get("/db/gold/mcx/settlement", params={"symbol": "GOLD", "date": "2026-11-05"}).json()
    assert (s["expiry"], s["settlement_source"], s["band_session_label"]) == ("2026-12-04", "band_midpoint", "Tue 03 Nov settlement")
    assert c.get("/db/gold/mcx/settlement", params={"symbol": "SILVER"}).status_code == 422
    r = c.post("/jobs/ingest-gold?job=gold_mcx_close", json={"groups": ["mcx_close_vwap30"], "params": {"sessions": ["2026-11-03"]}})
    g = r.json()["result"]["groups"]["mcx_close_vwap30"]
    assert seen and g["status"] == "ok" and g["breeze_calls"] == 2 and g["sessions"] == ["2026-11-03"]
    cur = c.get("/db/gold/curve", params={"exchange": "MCX", "date": "2026-11-04"}).json()
    assert [x["settlement_session"] for x in cur["settlements"] if x["expiry"] == "2026-12-04"] == ["2026-11-03"]
    gold_api.configure(get_store=lambda: masters, submit=submit)                         # reset the module-level getter


def test_a_broken_family_is_skipped_for_the_session_and_the_others_still_run(masters):
    db.upsert(masters, "gold_curve", pd.DataFrame([_master_row(WED, date(2026, 11, 30), 140000.0, 148000.0, 22000, symbol="GOLDTEN"),
                                                    _master_row(WED, date(2026, 12, 31), 141000.0, 149000.0, 9000, symbol="GOLDTEN")]))

    class TenBroken(FakeBreeze):
        def get_historical_data_v2(self, **kw):
            if kw["stock_code"] == "GOLDTE":
                self.calls.append(kw)
                return {"Status": 500, "Error": "Internal Server Error", "Success": None}
            return super().get_historical_data_v2(**kw)

    fake = TenBroken(BARS)
    res = mcx_close.run(masters, lambda: fake, now=AFTER_WED_CLOSE, pace_s=0, sleep=lambda s: None)
    st = {(c["family"], c["expiry"]): c["status"] for c in res["contracts"]}
    assert st == {("GOLD", "2026-12-04"): "ok", ("GOLDTEN", "2026-11-30"): "error", ("GOLDTEN", "2026-12-31"): "skipped"}
    assert res["status"] == "ok" and res["breeze_calls"] == 2                           # GOLDTEN's second month never called


def test_log_fallback_stale_rule_honours_a_flagged_settlement_check():
    base = {"day": THU, "baseline_source": "VWAP30 proxy", "inr_now": 94.6, "inr_ref": 94.5}
    assert ingest_local.stale_baseline_rule({**base, "settlement_check": {"band_vs_vwap30_pct": -2.642, "flagged": True}}) is True
    assert ingest_local.stale_baseline_rule({**base, "settlement_check": {"band_vs_vwap30_pct": 0.003, "flagged": False}}) is False
