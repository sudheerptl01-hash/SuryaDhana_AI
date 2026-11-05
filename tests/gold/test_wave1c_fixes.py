"""Wave 1c (the fix round after the critics, 5 Nov 2026) — every data-service rule that changed, each with a negative
control: the magnitude-aware fund-driver label (C-TRADER-3 / C-BEGINNER-1 / C-DATA-15), explicit UTC offsets on every
serialised datetime (C-TRADER-1 / C-DATA-1 / C-DATA-6), table-backed catalog ids served by ``reads.series`` (C-DATA-3 /
C-TRADER-8 / C-BEGINNER-6/14/15), the IMF ounce scale and bound (C-TRADER-6 / C-BEGINNER-3 / C-DATA-5), COMEX FND / LTD
events from the calendar with the PRF fallback (C-TRADER-13 / C-BEGINNER-4 / C-DATA-8), per-month daily bars from the
curve job (C-TRADER-9 / C-BEGINNER-6), ``sessions_spanned`` on MCX OI deltas (C-TRADER-18 / C-BEGINNER-5) and the three
Asia catalog ids (C-BEGINNER-16 / C-DATA-17)."""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import json
import re
from datetime import date, datetime

import pandas as pd
import pytest
from _support import G_CME, G_KITCO, G_MACRO, G_PHYS, FakeHttp, FakeResponse, read
from gold import (
    catalog_seed,
    cot_metrics,
    db,
    driver_rule,
    ingest_cme,
    ingest_local,
    ingest_physical,
    ingest_yahoo,
    jobs,
    pit,
    reads,
)

NAIVE_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
ANY_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


# ── 1. the fund-driver label ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dp,dl,ds,label", [
    # ── the critics' formula, case by case (C-TRADER-3 fix text; C-BEGINNER-1 wording) ──
    (-1.64, 1538, 182, "funds bought the dip"),        # the 27 Oct 2026 week the critics caught (was 'new shorts'): net +1,356
    (-1.0, -3000, 500, "long liquidation"),            # ΔL<0 and |ΔL| 3,000 ≥ max(ΔS,0) 500
    (-1.0, -100, 2000, "new shorts"),                  # |ΔL| 100 < 2,000 → ΔS>0 and ΔS ≥ max(ΔL,0)
    (-1.0, 100, 2000, "new shorts"),                   # new shorts dominate the new longs (net −1,900)
    (-1.0, 2000, 2000, "new shorts"),                  # net 0 on a down week → the bigger bearish leg (no closed longs) → new shorts
    (-1.0, -2000, 2000, "long liquidation"),           # tie between the two bearish legs → the closing leg, tested first
    (-1.0, 500, -200, "funds bought the dip"),         # both legs against the price (net +700)
    (-1.0, -1538, -182, "long liquidation"),           # both legs closed, liquidation the bigger leg: net −1,356
    (-1.0, -182, -1538, "funds bought the dip"),       # both legs closed, covering 8× the liquidation: net +1,356 → NOT 'long liquidation'
    (-1.0, 0, 300, "new shorts"), (-1.0, -300, 0, "long liquidation"),
    (1.64, -1538, -182, "funds sold into it"),         # the mirror of 27 Oct: funds cut net length into a rising price
    (1.0, 182, 1538, "funds sold into it"),            # both legs opened on an up week, shorts the bigger leg: net −1,356
    (1.0, 3000, -500, "new longs"),                    # ΔL 3,000 > |ΔS| 500
    (1.0, 100, -2000, "short covering"),               # ΔS<0 and |ΔS| 2,000 ≥ max(ΔL,0) 100
    (1.0, 2000, -2000, "short covering"),              # tie between the two bullish legs → the closing leg, tested first
    (1.0, -2000, -2000, "short covering"),             # net 0 on an up week, both legs closed equally → the bullish closed leg (mirror of the row above)
    (1.0, -100, 500, "funds sold into it"),            # both legs against the price (net −600)
    (1.0, 2000, 100, "new longs"),                     # new longs dominate the new shorts (net +1,900)
    (1.0, 0, -300, "short covering"), (1.0, 300, 0, "new longs"),
    (0.0, 1000, -1000, None),                          # no price change → no word (the who-did counts stand alone)
    (-1.0, 0, 0, None), (1.0, 0, 0, None),             # neither leg moved → no word
    (None, 1, 1, None), (1.0, None, 1, None), (1.0, 1, float("nan"), None), (1.0, True, 1, None),
])
def test_driver_label_is_magnitude_aware(dp, dl, ds, label):
    assert driver_rule.driver_label(dp, dl, ds) == label
    assert cot_metrics.driver_label(dp, dl, ds) == label               # cot_metrics delegates; one rule, one place


def test_driver_label_never_contradicts_the_net_change():
    """Negative control on a grid: a down week never says 'long liquidation' / 'new shorts' when the net rose, an up week
    never says 'new longs' / 'short covering' when the net fell, and the old sign-only rule's failure is gone."""
    grid = range(-3000, 3001, 500)
    for dl in grid:
        for ds in grid:
            if dl == 0 and ds == 0:
                continue
            down, up = driver_rule.driver_label(-1.0, dl, ds), driver_rule.driver_label(1.0, dl, ds)
            net = dl - ds
            assert (down == "funds bought the dip") == (net > 0), (dl, ds, down)
            assert (up == "funds sold into it") == (net < 0), (dl, ds, up)
            if net <= 0:        # the bigger bearish leg: |closed longs| vs new shorts (ties → the closing leg)
                assert down == ("long liquidation" if dl < 0 and -dl >= max(ds, 0) else "new shorts")
            if net >= 0:
                assert up == ("short covering" if ds < 0 and -ds >= max(dl, 0) else "new longs")
    assert driver_rule.driver_label(-1.0, 1, 1) is not None and driver_rule.driver_label(-1.64, 1538, 182) != "new shorts"


def test_driver_rule_is_pure_python_and_self_describing():
    import importlib
    from pathlib import Path

    text = Path(importlib.util.find_spec("gold.driver_rule").origin).read_text(encoding="utf-8")
    assert "import pandas" not in text and "from gold" not in text     # ui-api can import or mirror it verbatim
    assert driver_rule.ALL_LABELS == {"long liquidation", "new shorts", "funds bought the dip", "short covering", "new longs",
                                      "funds sold into it"}
    assert "bigger of the two legs" in driver_rule.RULE_TEXT


def test_cot_payload_carries_the_rule_text_and_an_aware_release_at(store, now):
    from gold import ingest_cot

    for ds, f in (("disagg_f", "cot_gold_disagg_futures_only.csv"), ("disagg_c", "cot_gold_disagg_combined.csv")):
        raw, typed = ingest_cot.parse_csv_text(read(ROOT_COT / f), ds, now=now)
        ingest_cot.ingest(store, ds, raw, typed)
    ingest_yahoo.ingest_daily(store, ingest_yahoo.parse_daily_csv(read(G_MACRO / "data" / "yahoo_GC_F.csv"), "GC=F", now=now))
    s = cot_metrics.summary(store, weeks=4)
    assert s["driver_rule"] == driver_rule.RULE_TEXT and s["driver_label"] in driver_rule.ALL_LABELS
    assert s["latest"]["release_at"] == "2026-10-23T19:30:00+00:00"   # Fri 15:30 ET, stamped UTC (was a naive string)
    assert s["latest"]["next_release_ist"].endswith("+05:30")


ROOT_COT = G_MACRO.parent / "G-COT" / "data"


# ── 2. no naive datetime string leaves reads.py ──────────────────────────────────────────────────────

def _walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def test_every_datetime_string_served_by_reads_carries_an_offset(store, now):
    _, bars = ingest_yahoo.parse_chart(read(G_KITCO / "yahoo_gcf_7d_1m.json"), expect_interval="1m")
    ingest_yahoo.ingest_intraday(store, ingest_yahoo.intraday_frame(bars, "GC=F", "1m", now=now))
    ingest_yahoo.ingest_daily(store, ingest_yahoo.parse_daily_csv(read(G_MACRO / "data" / "yahoo_GC_F.csv"), "GC=F", now=now))
    ingest_physical.ingest_series(store, pit.series_frame("UST_REAL_10Y", [(date(2026, 10, 23), 2.66)], freq="D", source="treasury_csv",
                                                          release_kind="treasury", now=now), now=now)
    ingest_cme.ingest_prf(store, read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now, ref_prices={"GC": 4007.9})
    ingest_local.ingest_events(store, now=now)
    ingest_local.upsert_preopen_log(store, {"day": "2026-10-26", "fair_open": 144181.0, "snapshot_at": "2026-10-26T03:15:00"}, now=now)
    payloads = {
        "series": reads.series(store, ["UST_REAL_10Y", "COMEX_GC_FRONT"], start=date(2026, 10, 1)),
        "bars_1m": reads.bars(store, symbol="GC=F", interval="1m", start=pd.Timestamp("2026-10-20").to_pydatetime()),
        "bars_1d": reads.bars(store, symbol="GC=F", interval="1d", start=date(2026, 10, 1)),
        "cot": reads.cot(store), "catalog": reads.catalog(store), "events": reads.events(store, start=date(2026, 10, 26)),
        "log": reads.log(store), "prf": reads.cme_prf(store), "curve": reads.curve(store, exchange="COMEX"),
        "etf": reads.etf(store), "asia": reads.asia(store), "margins": reads.margins(store), "calendar": reads.cme_calendar(store),
    }
    seen_dt = 0
    for name, payload in payloads.items():
        json.dumps(payload)                                              # JSON-safe
        for path, v in _walk(payload, name):
            if isinstance(v, str) and ANY_DT.match(v):
                seen_dt += 1
                assert not NAIVE_DT.match(v), f"naive datetime string at {path}: {v!r}"
                assert v.endswith(("+00:00", "Z", "+05:30")), f"{path}: {v!r}"
    assert seen_dt > 100                                                 # the walk really saw bars, releases and as-ofs
    ts = payloads["bars_1m"]["rows"][-1]["ts"]
    assert ts.endswith("+00:00") and pd.Timestamp(ts).tz is not None
    # negative controls: a DATE column stays a bare date; an already-aware input is converted, not double-stamped
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payloads["bars_1d"]["rows"][-1]["trade_date"])
    assert db.iso_utc(pd.Timestamp("2026-10-26 05:00")) == "2026-10-26T05:00:00+00:00"
    assert db.iso_utc(pd.Timestamp("2026-10-26 10:30", tz="Asia/Kolkata")) == "2026-10-26T05:00:00+00:00"
    assert db.iso_utc(date(2026, 10, 26)) == "2026-10-26" and db.iso_utc(None) is None


# ── 3. table-backed catalog ids served by reads.series ──────────────────────────────────────────────

def test_series_serves_yahoo_bar_etf_and_asia_backed_ids_point_in_time(store, now):
    from gold import ingest_physical as ph

    for sym, f in (("DX-Y.NYB", "yahoo_DX-Y_NYB.csv"), ("INR=X", "yahoo_INR_X.csv"), ("EURUSD=X", "yahoo_EURUSD_X.csv"),
                   ("GOLDBEES.NS", "yahoo_GOLDBEES_NS.csv")):
        ingest_yahoo.ingest_daily(store, ingest_yahoo.parse_daily_csv(read(G_MACRO / "data" / f), sym, now=now))
    db.upsert(store, "gold_etf_holdings", ph.parse_gld_archive(read(G_PHYS / "gld_hist_archive.bin", binary=True), now=now))
    db.upsert(store, "gold_asia_daily", ph.parse_sge_daily_html(read(G_PHYS / "sge_daily_intl.html"), now=now))
    out = reads.series(store, ["DXY_CLOSE", "USDINR_CLOSE", "FX_EURUSD", "GOLDBEES_CLOSE", "GLD_TONNES", "SGE_AUTD_OI", "SGE_AUTD_DIRECTION",
                               "NOPE"], start=date(2026, 10, 1))
    by = {s["series_id"]: s for s in out["series"]}
    assert by["NOPE"]["points"] == []
    for sid in ("DXY_CLOSE", "USDINR_CLOSE", "FX_EURUSD", "GOLDBEES_CLOSE", "GLD_TONNES"):
        pts = by[sid]["points"]
        assert len(pts) >= 10, sid
        assert all(p["release_at"].endswith("+00:00") for p in pts) and by[sid]["name"] and by[sid]["unit"]
    dxy = by["DXY_CLOSE"]["points"][-1]
    bar = db.query_df(store, "SELECT trade_date, close FROM gold_daily_bars WHERE symbol = 'DX-Y.NYB' ORDER BY trade_date DESC LIMIT 1").iloc[0]
    assert dxy["report_date"] == str(pd.Timestamp(bar.trade_date).date()) and dxy["value"] == pytest.approx(float(bar.close))
    assert dxy["release_at"] == db.iso_utc(now)                                                 # release_at = first_seen_at
    # the seed's last DXY row is Sunday 25 Oct evening → dated Monday 26 Oct; fetched 05:00 UTC Monday it is the in-progress
    # session, so the series says 'partial' (the Friday 23 Oct point is a 'close')
    assert dxy["report_date"] == "2026-10-26" and by["DXY_CLOSE"]["quality"] == "partial"
    assert reads.series(store, ["DXY_CLOSE"], end=date(2026, 10, 23))["series"][0]["quality"] == "close"
    gld = by["GLD_TONNES"]["points"][-1]
    assert gld["report_date"] == "2026-10-22" and gld["value"] == 1045.64 and gld["release_at"] == "2026-10-23T00:30:00+00:00"
    assert by["SGE_AUTD_OI"]["points"] and by["SGE_AUTD_DIRECTION"]["points"][-1]["value"] in (-1.0, 0.0, 1.0)
    # point-in-time: an as-of before the fetch sees no bar (first_seen_at is the bar's release), an ETF row before its
    # 00:30 IST release is unseen too; weekly resample still applies
    asof = {s["series_id"]: s["points"] for s in reads.series(store, ["DXY_CLOSE", "GLD_TONNES"],
                                                                 asof=pd.Timestamp("2026-10-22 18:00").to_pydatetime())["series"]}
    assert asof["DXY_CLOSE"] == []
    assert asof["GLD_TONNES"][-1]["report_date"] == "2026-10-21"      # the 22 Oct row is released 23 Oct 00:30 UTC: unseen
    wk = reads.series(store, ["USDINR_CLOSE"], start=date(2026, 9, 1), freq="W")["series"][0]["points"]
    assert all(pd.Timestamp(p["report_date"]).weekday() == 4 for p in wk) and len(wk) >= 6
    # negative control: a gold_series id is untouched by the routing (same answer as before)
    assert reads.series(store, ["UST_REAL_10Y"])["series"][0]["points"] == []


def test_the_three_asia_ids_have_catalog_rows_and_shfe_front_is_the_max_oi_contract(store, now):
    rows = {r["series_id"]: r for r in catalog_seed.build_rows()}
    for sid in ("SGE_AUTD_OI", "SGE_AUTD_DIRECTION", "SHFE_AU_FRONT_OI"):
        assert rows[sid]["verdict"] == "PUBLISH-CONTEXT" and rows[sid]["badge"] == "context" and rows[sid]["verdict_reason"], sid
    ingest_physical.ingest_shfe(store, read(G_PHYS / "shfe_kx_new_20261023.json"), date(2026, 10, 23), now=now)
    pts = reads.series(store, ["SHFE_AU_FRONT_OI"])["series"][0]["points"]
    top = db.query_df(store, "SELECT contract, open_interest FROM gold_asia_daily WHERE exchange = 'SHFE' ORDER BY open_interest DESC LIMIT 1").iloc[0]
    assert len(pts) == 1 and pts[0]["value"] == float(top.open_interest)
    assert reads.series(store, ["SHFE_AU_FRONT_OI"])["series"][0]["quality"] == top.contract      # the contract is named, not hidden


# ── 4. IMF ounces: units, the ×1000 cross-check, the 300 Moz bound ──────────────────────────────────

def _imf_csv(rows: list[tuple[str, str, str, float]]) -> str:
    head = "DATAFLOW,COUNTRY,INDICATOR,SECTOR,FREQUENCY,TIME_PERIOD,OBS_VALUE,SCALE"
    return head + "\n" + "\n".join(f"IMF.STA:IRFCL(12.0.0),{c},{i},S1XS1311,M,{tp},{v},6" for c, i, tp, v in rows) + "\n"


OZ, USD = "IRFCLDT1_IRFCL56V_FTO", "IRFCLDT1_IRFCL56_USD"


def test_imf_ounces_are_units_and_the_bra_x1000_row_is_rescaled_by_its_own_usd_value(now):
    text = _imf_csv([("IND", OZ, "2026-M08", 28309311.059), ("IND", USD, "2026-M08", 28309311.059 * 4000),
                     ("BRA", OZ, "2026-M08", 5544278722.99971), ("BRA", USD, "2026-M08", 24558327160.74),
                     ("USA", OZ, "2026-M07", 261499000.0), ("USA", USD, "2026-M07", 11041058800.0)])   # USA books gold at $42.22/oz
    df = ingest_physical.parse_imf_csv(text, now=now, ref_price=4078.7)
    v = {(r.series_id, str(r.report_date)): (r.value, r.quality) for r in df.itertuples(index=False)}
    assert v[("IMF_GOLD_OZ_IND", "2026-08-31")] == (pytest.approx(28309311.059), "official")       # 28.3 Moz = 880.5 t, untouched
    assert v[("IMF_GOLD_OZ_BRA", "2026-08-31")] == (pytest.approx(5544278.72299971), "rescaled_x1000")   # 5.54 Moz ≈ 172 t, $4,430/oz
    assert v[("IMF_GOLD_OZ_USA", "2026-07-31")] == (pytest.approx(261499000.0), "official")        # book value: no divisor fits → kept
    assert v[("IMF_GOLD_USD_BRA", "2026-08-31")][0] == 24558327160.74                              # USD never rescaled
    # the catalog says so
    row = {r["series_id"]: r for r in catalog_seed.build_rows()}["IMF_GOLD_OZ_BRA"]
    assert row["unit"] == "oz" and "TROY OUNCES" in row["pro_note"] and "300 Moz" in row["pro_note"]


def test_imf_bound_rejects_an_impossible_ounce_value_and_the_batch_median_stands_in_for_the_reference(now):
    # no ref_price: the batch median of market-value reporters (IND, CHN at ~$4,000) is the reference; USA's $42 is excluded
    text = _imf_csv([("IND", OZ, "2026-M08", 28.3e6), ("IND", USD, "2026-M08", 28.3e6 * 4000), ("CHN", OZ, "2026-M08", 77.47e6),
                     ("CHN", USD, "2026-M08", 77.47e6 * 3950), ("USA", OZ, "2026-M07", 261.5e6), ("USA", USD, "2026-M07", 261.5e6 * 42.22),
                     ("BRA", OZ, "2026-M08", 5.544e9), ("BRA", USD, "2026-M08", 5.544e6 * 4100),
                     ("ZZZ", OZ, "2026-M08", 9.9e12), ("ZZZ", USD, "2026-M08", 1.0)])                  # no divisor fits, > 300 Moz
    df = ingest_physical.parse_imf_csv(text, now=now)
    v = {r.series_id: (r.value, r.quality) for r in df.itertuples(index=False)}
    assert v["IMF_GOLD_OZ_BRA"] == (pytest.approx(5.544e6), "rescaled_x1000") and v["IMF_GOLD_OZ_USA"][1] == "official"
    assert "IMF_GOLD_OZ_ZZZ" not in v and "IMF_GOLD_USD_ZZZ" in v                                 # rejected ounces, kept USD
    assert ingest_physical.imf_oz_scale(1.0e6, 4.0e9, 4000.0) == (1.0, "official")
    assert ingest_physical.imf_oz_scale(1.0e9, 4.0e9, 4000.0) == (1e3, "rescaled_x1000")
    assert ingest_physical.imf_oz_scale(1.0e12, 4.0e9, 4000.0) == (1e6, "rescaled_x1000000")
    assert ingest_physical.imf_oz_scale(None, 4.0e9, 4000.0) == (1.0, "official")
    # the real India sample is unchanged by the check (its own USD value agrees with the ounces)
    real = ingest_physical.parse_imf_csv(read(G_PHYS / "imf_irfcl_india.csv"), now=now, ref_price=3400.0)
    r = real[(real["series_id"] == "IMF_GOLD_OZ_IND") & (real["report_date"] == date(2026, 8, 31))].iloc[0]
    assert r.value == pytest.approx(28309311.059) and r.quality == "official"


# ── 5. COMEX FND / LTD events: the calendar first, the daily PRF as fallback ─────────────────────────

def test_fnd_and_ltd_events_come_from_the_prf_when_the_sunday_calendar_is_missing(store, now):
    ingest_cme.ingest_prf(store, read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True), now=now, ref_prices={"GC": 4007.9})
    dates = ingest_local.comex_contract_dates(store)
    z26 = dates[(dates["symbol"] == "GC") & (dates["mmy"] == "202612")].iloc[0]
    assert (db.to_date(z26.first_notice), db.to_date(z26.last_trade), z26.source) == (date(2026, 11, 30), date(2026, 12, 29), "cme_prf")
    ev = ingest_local.compile_events(store, now=now)
    fnd = ev[(ev["kind"] == "COMEX_FND") & (ev["name"] == "COMEX GC 2026-12 first notice day")].iloc[0]
    ltd = ev[(ev["kind"] == "COMEX_LTD") & (ev["name"] == "COMEX GC 2026-12 last trading day")].iloc[0]
    assert fnd["event_date"] == date(2026, 11, 30) and fnd["source"] == "cme_prf" and ltd["event_date"] == date(2026, 12, 29)
    assert ltd["time_ist"] == "23:00" and "COMEX_FIRST_INTENT" not in set(ev["kind"])            # the PRF carries no intent day
    nxt = ev[(ev["kind"] == "COMEX_FND") & (ev["name"] == "COMEX GC 2027-02 first notice day")].iloc[0]
    assert nxt["event_date"] == date(2027, 1, 29)
    # the calendar, once stored, wins over the PRF for the months it carries (and adds the intent day)
    ingest_cme.ingest_product_calendar(store, str(G_CME / "product-calendar-new.xml"), now=now)
    dates2 = ingest_local.comex_contract_dates(store)
    assert dates2[(dates2["symbol"] == "GC") & (dates2["mmy"] == "202612")].iloc[0].source == "cme_calendar"
    ev2 = ingest_local.compile_events(store, now=now)
    assert ev2[(ev2["kind"] == "COMEX_FND") & (ev2["name"] == "COMEX GC 2026-12 first notice day")].iloc[0]["event_date"] == date(2026, 11, 30)
    assert "COMEX_FIRST_INTENT" in set(ev2["kind"]) and not ev2.duplicated(["event_date", "kind", "name"]).any()
    # the read endpoint shows the stored calendar for the operator
    cal = reads.cme_calendar(store, symbol="GC")
    assert cal["as_of"] and any(r["mmy"] == "202612" and r["first_notice"] == "2026-11-30" for r in cal["rows"])
    assert reads.cme_calendar(store, symbol="ZZ") == {"symbol": "ZZ", "as_of": None, "rows": []}


def test_cme_groups_recompile_the_events_so_fnd_exists_the_same_run(store, now, monkeypatch):
    monkeypatch.setattr(jobs, "ftp_fetch", lambda url, **kw: read(G_CME / "cmeg.comex.fut.prf.csv.zip", binary=True))
    ctx = jobs.Ctx(store=store, http=FakeHttp(), now=now, backfill_from=None, force=True, params={}, progress=None)
    res = jobs.run_group("cme_prf", ctx)
    assert res["status"] == "ok" and res["events"]["inserted"] > 0 and "COMEX_FND" in res["events"]["kinds"]
    ev = reads.events(store, start=date(2026, 11, 1), end=date(2026, 12, 31), kinds=["COMEX_FND", "COMEX_LTD"])["rows"]
    assert any(r["event_date"] == "2026-11-30" and "GC 2026-12" in r["name"] for r in ev)


# ── 6. per-month daily bars from the curve job ──────────────────────────────────────────────────────

def test_curve_job_stores_the_months_own_daily_bars(store, now):
    http = FakeHttp({"chart/GCJ27.CMX": FakeResponse(200, read(G_KITCO / "yahoo_gcj27_5d_1d.json")),
                     "chart/GCQ27.CMX": FakeResponse(200, read(G_KITCO / "yahoo_gcq27_5d_1d.json"))})
    res = ingest_yahoo.fetch_curve(store, http, symbols=("GCJ27.CMX", "GCQ27.CMX", "GCZ99.CMX"), now=now)
    assert res["GCJ27.CMX"] == {"status": "ok", "rows": 1, "daily_bars": 5} and res["GCZ99.CMX"]["status"] == "http_404"
    b = reads.bars(store, symbol="GCJ27.CMX", interval="1d", start=date(2026, 10, 1))
    assert b["symbol"] == "GCJ27.CMX" and b["series_id"] is None and [r["trade_date"] for r in b["rows"]][-1] == "2026-10-26"
    assert b["rows"][-1]["source"] == "yahoo"                                        # a last trade, labelled by its source
    hist = reads.curve_history(store, exchange="COMEX", symbol="GC", days=60)["rows"]     # GCJ27's last bar is the Sunday→Monday
    assert {r["expiry"] for r in hist} == {"2027-04-28", "2027-08-27"} and all(r["quality"] == "last_trade" for r in hist)   # partial, GCQ27's Friday
    assert reads.curve(store, exchange="COMEX")["rows"][0]["close"] == b["rows"][-1]["close"]   # the curve point and the bar agree
    assert reads.bars(store, symbol="GCZ26.CMX", interval="1d")["rows"] == []        # negative control: an unfetched month stays empty


# ── 7. sessions_spanned on MCX OI deltas ────────────────────────────────────────────────────────────

def _mcx_row(d: date, expiry: date, oi: int, now: datetime) -> dict:
    return {"trade_date": d, "exchange": "MCX", "symbol": "GOLD", "expiry": expiry, "settle": 140000.0, "open_interest": oi,
            "oi_change": None, "unit": "INR/10g", "source": "icici_master_band", "quality": "proxy", "session_date": d,
            "release_at": now, "first_seen_at": now}


def test_mcx_oi_deltas_carry_sessions_spanned(store, now):
    from gold.ingest_india import recompute_curve_oi_change

    e = date(2026, 12, 4)
    rows = [_mcx_row(date(2026, 10, 1), e, 15000, now), _mcx_row(date(2026, 10, 5), e, 15200, now),      # 2 Oct = full closure
            _mcx_row(date(2026, 10, 29), e, 15605, now), _mcx_row(date(2026, 11, 3), e, 16282, now),     # 30 Oct, 2 Nov missing
            _mcx_row(date(2026, 11, 4), e, 16300, now)]
    db.upsert(store, "gold_curve", pd.DataFrame(rows))
    recompute_curve_oi_change(store)
    hist = {r["trade_date"]: r for r in reads.curve_history(store, exchange="MCX", symbol="GOLD", days=60)["rows"]}
    assert hist["2026-10-01"]["sessions_spanned"] is None and hist["2026-10-01"]["oi_change"] is None    # no prior row
    assert (hist["2026-10-05"]["sessions_spanned"], hist["2026-10-05"]["oi_change_from"]) == (1, "2026-10-01")  # Fri 2 Oct closed: one session
    assert (hist["2026-11-03"]["oi_change"], hist["2026-11-03"]["sessions_spanned"], hist["2026-11-03"]["oi_change_from"]) == (677, 3, "2026-10-29")
    assert hist["2026-11-04"]["sessions_spanned"] == 1                                                   # a normal day
    latest = reads.curve(store, exchange="MCX")
    assert latest["date"] == "2026-11-04" and latest["rows"][0]["sessions_spanned"] == 1
    assert latest["ghost_date"] == "2026-10-05" and latest["ghost_1w"][0]["sessions_spanned"] == 1             # the curve ≤ 7 days back
    gap = reads.curve(store, exchange="MCX", day=date(2026, 11, 3))["rows"][0]
    assert (gap["oi_change"], gap["sessions_spanned"], gap["oi_change_from"]) == (677, 3, "2026-10-29")        # the critics' 3-session delta
    assert reads.sessions_between(date(2026, 10, 30), date(2026, 11, 2)) == 1 and reads.sessions_between(None, date(2026, 11, 2)) is None
    assert reads.sessions_between(date(2026, 11, 2), date(2026, 11, 2)) is None


# ── 8. a daily bar fetched before its session close is 'partial' (C-DATA-21 / C-TRADER-25 / C-DATA-20) ───────────────

def test_daily_bars_fetched_before_the_session_close_are_flagged_partial(store):
    from datetime import timedelta

    # the 03:10 IST job (21:40 UTC) runs 20 min before the WINTER Globex close (17:00 ET = 22:00 UTC); summer close 21:00 UTC
    assert ingest_yahoo.session_close_utc("GC=F", date(2026, 11, 4)) == datetime(2026, 11, 4, 22, 0)
    assert ingest_yahoo.session_close_utc("GC=F", date(2026, 7, 1)) == datetime(2026, 7, 1, 21, 0)
    assert ingest_yahoo.session_close_utc("GOLDBEES.NS", date(2026, 11, 4)) == datetime(2026, 11, 4, 10, 0)     # 15:30 IST
    assert ingest_yahoo.session_close_utc("^TNX", date(2026, 11, 4)) == datetime(2026, 11, 4, 21, 0)             # 16:00 NY cash
    assert ingest_yahoo.session_close_utc("GCZ26.CMX", date(2026, 11, 4)) == datetime(2026, 11, 4, 22, 0)
    early, final = datetime(2026, 11, 4, 21, 40), datetime(2026, 11, 5, 21, 40)
    rows = pd.DataFrame([{"trade_date": date(2026, 11, 3), "symbol": "GC=F", "open": 1, "high": 1, "low": 1, "close": 3940.4, "adj_close": 3940.4,
                          "volume": 172512, "source": "yahoo", "first_seen_at": early - timedelta(hours=23)},     # 22:40 UTC 3 Nov: after ITS close
                         {"trade_date": date(2026, 11, 4), "symbol": "GC=F", "open": 1, "high": 1, "low": 1, "close": 4078.7, "adj_close": 4078.7,
                          "volume": 172512, "source": "yahoo", "first_seen_at": early}])
    ingest_yahoo.ingest_daily(store, rows)
    b = {r["trade_date"]: r for r in reads.bars(store, symbol="GC=F", interval="1d", start=date(2026, 11, 1))["rows"]}
    assert b["2026-11-04"]["partial"] is True and b["2026-11-04"]["first_seen_at"] == "2026-11-04T21:40:00+00:00"
    assert b["2026-11-03"]["partial"] is False                                          # fetched after ITS close: final
    s = reads.series(store, ["COMEX_GC_FRONT"], start=date(2026, 11, 1), asof=final)["series"][0]     # PIT: as of the next fetch
    assert s["quality"] == "partial" and s["points"][-1]["value"] == 4078.7                 # the series says so too
    # the next day's re-fetch (5-day window) overwrites the row with a later first_seen_at → final, same key, no duplicate
    rows.loc[1, "first_seen_at"] = final
    ingest_yahoo.ingest_daily(store, rows.iloc[[1]])
    b2 = reads.bars(store, symbol="GC=F", interval="1d", start=date(2026, 11, 1))["rows"]
    assert len(b2) == 2 and b2[-1]["partial"] is False
    assert reads.series(store, ["COMEX_GC_FRONT"], start=date(2026, 11, 1), asof=final)["series"][0]["quality"] == "close"
    # negative controls: an unknown fetch time is never flagged; an aware IST stamp converts; intraday rows carry no flag
    assert ingest_yahoo.is_partial("GC=F", date(2026, 11, 4), None) is False
    assert ingest_yahoo.is_partial("GC=F", date(2026, 11, 4), pd.Timestamp("2026-11-05 03:10", tz="Asia/Kolkata")) is True
    assert ingest_yahoo.is_partial("GC=F", date(2026, 11, 4), pd.Timestamp("2026-11-05 03:40", tz="Asia/Kolkata")) is False
    assert "partial" not in reads.bars(store, symbol="GC=F", interval="1m")


def test_imf_mixed_scale_series_is_rescaled_per_month_not_per_country() -> None:
    """BRA publishes units to Feb 2026 and ×1000 from Mar 2026: the early rows must stay, the late rows divide (re-check major)."""
    from datetime import datetime, timezone

    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    text = _imf_csv([
        ("BRA", OZ, "2026-M02", 5_544_279.0), ("BRA", USD, "2026-M02", 5_544_279.0 * 2900),
        ("BRA", OZ, "2026-M03", 5_544_278_723.0), ("BRA", USD, "2026-M03", 5_544_279.0 * 3000),
        ("BRA", OZ, "2026-M09", 5_544_278_723.0), ("BRA", USD, "2026-M09", 5_544_279.0 * 3700),
        ("BRA", OZ, "2026-M10", 5_544_278_723.0),                                   # no USD row: latest pair's divisor
    ])
    df = ingest_physical.parse_imf_csv(text, now=now, ref_price=4000.0)
    oz = df[df["series_id"] == "IMF_GOLD_OZ_BRA"].set_index("report_date")
    assert len(oz) == 4
    assert abs(oz.loc[oz.index.min(), "value"] - 5_544_279.0) < 1 and oz.loc[oz.index.min(), "quality"] == "official"
    late = oz[oz.index > oz.index.min()]
    assert (abs(late["value"] - 5_544_279.0) < 1).all() and set(late["quality"]) == {"rescaled_x1000"}


def test_imf_duplicate_period_records_collapse_to_one_row_per_month() -> None:
    """The IRFCL CSV repeats (country, period) rows; two rows per month broke the gold_series primary key (4 Nov)."""
    from datetime import datetime, timezone

    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    text = _imf_csv([("DEU", OZ, "2025-M01", 108_300_000.0), ("DEU", OZ, "2025-M01", 108_300_000.0),
                     ("DEU", USD, "2025-M01", 108_300_000.0 * 2700), ("DEU", USD, "2025-M01", 108_300_000.0 * 2700)])
    df = ingest_physical.parse_imf_csv(text, now=now, ref_price=2700.0)
    assert len(df) == 2 and not df.duplicated(["series_id", "report_date"]).any()
