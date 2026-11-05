"""T3 replay — the physical / ETF / official-sector / OTC bodies (G-PHYSICAL), the India pages (G-INDIA, the public
ICICI master, Zerodha, IBJA, RBI, AMFI) and the local files (briefs, log.json). Every number is one SOURCES.md quotes."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
from _support import FIXTURES, G_CME, G_INDIA, G_PHYS, ROOT, read
from gold import db, ingest_india, ingest_local, pit
from gold import ingest_physical as ph


def _val(df: pd.DataFrame, sid: str, d: date) -> float:
    return float(df[(df["series_id"] == sid) & (df["report_date"] == d)]["value"].iloc[0])


# ── ETF ──────────────────────────────────────────────────────────────────────────────────────────────

def test_gld_archive_xlsx(now):
    df = ph.parse_gld_archive(read(G_PHYS / "gld_hist_archive.bin", binary=True), now=now)
    assert len(df) == 5515 and df["report_date"].min() == date(2004, 11, 18) and df["report_date"].max() == date(2026, 10, 22)
    assert df.iloc[0]["tonnes"] == 8.09 and df.iloc[-1]["tonnes"] == 1045.64 and df.iloc[-2]["tonnes"] == 1057.62
    assert date(2004, 11, 25) not in set(df["report_date"])                       # 'US Holiday' rows skipped
    assert df.iloc[-1]["shares"] == pytest.approx(33618491.91 / 0.09165555, rel=1e-6) and df.iloc[-1]["release_at"] == pd.Timestamp("2026-10-23 00:30")


def test_iau_product_page(now):
    df = ph.parse_iau_page(read(G_PHYS / "iau_page.html"), now=now)
    assert len(df) == 1 and df.iloc[0]["tonnes"] == 463.05 and df.iloc[0]["report_date"] == date(2026, 10, 23) and df.iloc[0]["fund"] == "IAU"


# ── WGC (display-only, attributed) ───────────────────────────────────────────────────────────────────

def test_wgc_flows_holdings_archive_premiums(now):
    flows = ph.parse_wgc_flows(read(G_PHYS / "wgc_fsapi_flows.json"), now=now)
    wk = date(2026, 10, 16)
    assert _val(flows, "WGC_ETF_FLOW_T_GLOBAL", wk) == pytest.approx(13.69, abs=0.05)          # week 42: global +13.69 t
    assert _val(flows, "WGC_ETF_FLOW_USD_MN_GLOBAL", wk) == pytest.approx(1900, abs=10)         # +$1.90 bn
    assert (flows["freq"] == "W").all() and flows[flows["series_id"] == "WGC_ETF_FLOW_T_NA"]["report_date"].min() <= date(2018, 1, 12)
    hold = ph.parse_wgc_holdings(read(G_PHYS / "wgc_fsapi_holdings.json"), now=now)
    assert _val(hold, "WGC_ETF_HOLD_T_GLOBAL", wk) == pytest.approx(4278.9, abs=0.5)
    assert (_val(hold, "WGC_ETF_HOLD_T_NA", wk), _val(hold, "WGC_ETF_HOLD_T_EU", wk), _val(hold, "WGC_ETF_HOLD_T_ASIA", wk)) == \
        pytest.approx((2123.2, 1529.3, 549.9), abs=0.1)
    arch = ph.parse_wgc_archive(read(G_PHYS / "wgc_fsapi_archive.json"), now=now)
    assert _val(arch, "WGC_ETF_HOLD_T_IN", wk) == pytest.approx(124.4, abs=0.1)
    asof, tbl = ph.wgc_archive_table(read(G_PHYS / "wgc_fsapi_archive.json"), "top10_ca", "Weekly")
    assert asof == wk and tbl.iloc[0]["Fund"] == "SPDR Gold Shares" and float(tbl.iloc[0]["Demand (tonnes)"]) == pytest.approx(6.19, abs=0.01)
    prem = ph.parse_wgc_premiums(read(G_PHYS / "wgc_fsapi_prem_full.json"), now=now)
    assert _val(prem, "WGC_PREMIUM_IN", wk) == pytest.approx(11.44, abs=0.01) and _val(prem, "WGC_PREMIUM_CN", wk) == pytest.approx(7.76, abs=0.01)
    assert flows["release_at"].max() <= pd.Timestamp(now)


def test_wgc_balance_sheet_and_price_marks(now):
    sd = ph.parse_wgc_sd(read(G_PHYS / "wgc_fsapi_sd.json"), now=now)
    q = date(2026, 6, 30)
    got = {k: _val(sd, f"WGC_SD_{k}", q) for k in ("MINE", "RECYCLED", "HEDGING", "JEWELLERY", "TECHNOLOGY", "BAR_COIN", "ETF", "CENTRAL_BANKS")}
    assert got == pytest.approx({"MINE": 965.6, "RECYCLED": 326.1, "HEDGING": -22.8, "JEWELLERY": 310.3, "TECHNOLOGY": 80.4,
                                 "BAR_COIN": 307.1, "ETF": -44.8, "CENTRAL_BANKS": 288.9}, abs=0.1)
    assert _val(sd, "WGC_SD_OTC_OTHER", q) == pytest.approx(327, abs=1.0) and _val(sd, "WGC_SD_LBMA_AVG_PRICE", q) == 4506.3
    assert (sd["freq"] == "Q").all() and sd["report_date"].min() == date(2010, 3, 31) and sd["series_id"].nunique() == 10
    px = ph.parse_wgc_price(read(G_PHYS / "wgc_fsapi_price.json"), now=now)
    assert _val(px, "LBMA_PM_USD", date(2026, 10, 23)) == 4013.30 and px[px["series_id"] == "SGE_AM_CNY_WGC"]["value"].iloc[-1] > 800
    assert px[px["series_id"] == "MCX_AM_INR_WGC"]["value"].iloc[0] == 60359


# ── IMF ──────────────────────────────────────────────────────────────────────────────────────────────

def test_imf_irfcl_csv(now):
    df = ph.parse_imf_csv(read(G_PHYS / "imf_irfcl_india.csv"), now=now)
    assert _val(df, "IMF_GOLD_OZ_IND", date(2026, 8, 31)) == pytest.approx(28309311.059)          # 28.31 Moz = 880.5 t
    assert _val(df, "IMF_GOLD_OZ_IND", date(2026, 8, 31)) * 31.1034768 / 1e6 == pytest.approx(880.5, abs=0.1)
    assert set(df["series_id"]) == {"IMF_GOLD_OZ_IND", "IMF_GOLD_USD_IND"} and (df["freq"] == "M").all()
    url, params = ph.imf_url(["IND", "CHN"], "2000-01")
    assert url.startswith("https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/IND+CHN.IRFCLDT1_IRFCL56V_FTO") and params["format"] == "csv"


# ── Shanghai ─────────────────────────────────────────────────────────────────────────────────────────

def test_sge_daily_table(now):
    df = ph.parse_sge_daily_html(read(G_PHYS / "sge_daily_intl.html"), now=now)
    spot = df[(df["contract"] == "Au99.99") & (df["trade_date"] == date(2026, 10, 23))].iloc[0]
    assert (spot["close"], spot["vwap"], spot["volume_kg"]) == (864.00, 863.44, 13963.7)
    td = df[(df["contract"] == "Au(T+D)") & (df["trade_date"] == date(2026, 10, 23))].iloc[0]
    assert (td["close"], td["volume_kg"], td["open_interest"], td["direction"], td["delivery_lots"]) == (863.38, 56720.0, 260054, "Long to Short", 24570)
    assert not df["contract"].str.startswith(("Ag", "Pt")).any() and (df["unit"] == "CNY/g").all()


def test_sge_benchmark_html_json_and_monthly_pdf(now):
    h = ph.parse_sge_benchmark_html(read(G_PHYS / "sge_bm_daily.html"), now=now)
    assert _val(h, "SGE_SHAU_AM", date(2026, 10, 23)) == 862.91 and _val(h, "SGE_SHAU_PM", date(2026, 10, 23)) == 862.76 and len(h) == 14
    j = ph.parse_sge_benchmark_json(read(G_PHYS / "sge_graph_jzj.json"), now=now)
    am = j[j["series_id"] == "SGE_SHAU_AM"]
    assert len(am) == 2553 and am.iloc[0]["report_date"] == date(2016, 4, 19) and am.iloc[0]["value"] == 256.92
    assert h[h["series_id"] == "SGE_SHAU_PM"]["release_at"].iloc[0] == pd.Timestamp("2026-10-23 06:15")       # 14:15 Beijing
    m = ph.parse_sge_monthly_pdf(read(G_PHYS / "sge_highlights_sep2026.pdf", binary=True), now=now)
    assert _val(m, "SGE_WITHDRAWALS_KG", date(2026, 9, 30)) == 92083.24 and _val(m, "SGE_DELIVERY_RATIO", date(2026, 9, 30)) == 51.03


def test_shfe_kx_json(store, now):
    df = ph.parse_shfe_kx(read(G_PHYS / "shfe_kx_new_20261023.json"), date(2026, 10, 23), now=now)
    row = df[df["contract"] == "au2612"].iloc[0]
    assert (row["settle"], row["open_interest"], row["oi_change"]) == (869.2, 198578, -9623) and df["open_interest"].sum() == 368618
    assert ph.ingest_shfe(store, read(G_PHYS / "shfe_kx_new_20261023.json"), date(2026, 10, 23), now=now)["total_oi"] == 368618
    assert ph.parse_shfe_kx(read(G_PHYS / "shfe_kx_new_20251024.json"), date(2025, 10, 24), now=now)["open_interest"].sum() > 0
    assert ph.parse_shfe_kx(read(G_PHYS / "shfe_kx_20251024.json"), date(2025, 10, 24), now=now).empty         # the old path's HTML 404 body


# ── LBMA / Swiss ─────────────────────────────────────────────────────────────────────────────────────

def test_lbma_turnover_vault_and_swiss_zip(now):
    t = ph.parse_lbma_turnover(read(G_PHYS / "lbma_trade_data_page.html"), now=now)
    assert _val(t, "LBMA_OTC_TURNOVER_USD_BN", date(2026, 10, 16)) == 964.17 and _val(t, "LBMA_OTC_TURNOVER_SILVER_USD_BN", date(2026, 10, 16)) == 129.69
    assert ph.lbma_vault_href(read(G_PHYS / "lbma_vault_page.html")).endswith("LBMA-London-Vault-Holdings-Data-September-2026.xlsx")
    v = ph.parse_lbma_vault_xlsx(read(G_PHYS / "lbma_vault_sep2026.xlsx", binary=True), now=now)
    assert _val(v, "LBMA_VAULT_GOLD_T", date(2026, 9, 30)) == pytest.approx(9821, abs=1) and _val(v, "LBMA_VAULT_SILVER_T", date(2026, 9, 30)) == pytest.approx(28985, abs=1)
    assert v[v["series_id"] == "LBMA_VAULT_GOLD_T"]["report_date"].min() == date(2016, 7, 31)
    assert _val(v, "LBMA_VAULT_GOLD_T", date(2026, 9, 30)) - _val(v, "LBMA_VAULT_GOLD_T", date(2026, 8, 31)) == pytest.approx(189, abs=1)
    sw = ph.parse_swiss_zip(str(FIXTURES / "swiss_tn8_synthetic.zip"), now=now)
    assert _val(sw, "SWISS_GOLD_EXPORT_IN_KG", date(2026, 8, 31)) == 12345.5 and _val(sw, "SWISS_GOLD_EXPORT_IN_KG", date(2026, 9, 30)) == 21000.25


# ── India ────────────────────────────────────────────────────────────────────────────────────────────

def test_ibja_am_pm_tables(now):
    df = ingest_india.parse_ibja_html(read(G_INDIA / "s_ibjarates.com_.html"), now=now)
    d = date(2026, 10, 23)
    assert (_val(df, "IBJA_999_AM", d), _val(df, "IBJA_995_AM", d)) == (141448, 140882)
    assert (_val(df, "IBJA_999_PM", d), _val(df, "IBJA_995_PM", d), _val(df, "IBJA_916_PM", d), _val(df, "IBJA_SILVER_999_PM", d)) == (141630, 141063, 129733, 194415)
    assert date(2026, 10, 20) not in set(df["report_date"])                        # no fix on Dussehra
    pm = df[(df["series_id"] == "IBJA_999_PM") & (df["report_date"] == d)].iloc[0]
    assert df["series_id"].nunique() == 12 and pm["release_at"] == pd.Timestamp("2026-10-23 12:30")


def test_rbi_wss_and_reference_rate(now):
    w = ingest_india.parse_rbi_wss(read(G_PHYS / "rbi_pr_63855.html"), now=now)
    d = date(2026, 10, 16)
    assert (_val(w, "RBI_GOLD_RESERVES_INR_CR", d), _val(w, "RBI_GOLD_RESERVES_USD_MN", d), _val(w, "RBI_RESERVES_TOTAL_USD_MN", d)) == (1004583, 105800, 721016)
    assert ingest_india.parse_rbi_wss(read(G_INDIA / "wss_23oct.html"), now=now).equals(w)
    r = ingest_india.parse_rbi_reference_rate(read(FIXTURES / "rbi_reference_rate_archive_synthetic.html"), now=now)
    assert _val(r, "USDINR_FBIL", date(2026, 10, 23)) == 94.9432 and _val(r, "USDINR_FBIL", date(2026, 10, 22)) == 94.6986
    side = read(G_INDIA / "rbi_pr.html")
    assert ingest_india.parse_rbi_reference_rate(side, now=now).empty                            # the sidebar carries no date: never guessed
    assert _val(ingest_india.parse_rbi_reference_rate(side, now=now, as_of=date(2026, 10, 23)), "USDINR_FBIL", date(2026, 10, 23)) == 94.9432


def test_icici_master_labels_the_session_never_the_file_date(store, now):
    df = ingest_india.parse_mcx_master(read(FIXTURES / "MCXScripMaster_gold_20261026.txt"), date(2026, 10, 26), now=now)
    assert len(df) == 30 and (df["trade_date"] == date(2026, 10, 23)).all() and (df["session_date"] == date(2026, 10, 23)).all()
    assert (df["quality"] == "proxy").all() and (df["source"] == "icici_master_band").all() and (df["release_at"] == pd.Timestamp("2026-10-26 02:00")).all()
    gold = df[df["symbol"] == "GOLD"].sort_values("expiry").iloc[0]
    assert (gold["expiry"], gold["settle"], gold["band_lo"], gold["band_hi"], gold["open_interest"]) == (date(2026, 12, 4), 143309.0, 139010.0, 147608.0, 16217)
    assert set(df["symbol"]) == {"GOLD", "GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"}
    assert df[df["symbol"] == "GOLDM"].sort_values("expiry").iloc[0]["open_interest"] == 42926
    assert dict(df.groupby("symbol")["unit"].first()) == {"GOLD": "INR/10g", "GOLDM": "INR/10g", "GOLDTEN": "INR/10g", "GOLDGUINEA": "INR/8g", "GOLDPETAL": "INR/1g"}
    assert ingest_india.previous_mcx_session(date(2026, 10, 26)) == date(2026, 10, 23)      # Monday file → Friday's session
    assert ingest_india.previous_mcx_session(date(2026, 10, 5)) == date(2026, 10, 1)        # Fri 2 Oct full holiday skipped
    assert ingest_india.previous_mcx_session(date(2026, 10, 20)) == date(2026, 10, 19)
    assert ingest_india.ingest_mcx_master(store, read(FIXTURES / "MCXScripMaster_gold_20261026.txt"), date(2026, 10, 26), now=now)["gold_front"]["settle"] == 143309.0


def test_zerodha_margin_mirror(now):
    df = ingest_india.parse_zerodha_margins(read(G_INDIA / "m_zerodha.com_margin-calculator_Commodity_.html"), now=now)
    assert (df["trade_date"] == date(2026, 10, 25)).all() and (df["margin_pct"] == 9.25).all() and (df["source"] == "zerodha_nrml").all()
    m = {(r.symbol, r.expiry): r.margin_ccy for r in df.itertuples(index=False)}
    assert m[("GOLD", date(2026, 12, 4))] == 1325636 and m[("GOLDM", date(2026, 11, 5))] == 131165 and m[("GOLDTEN", date(2026, 11, 30))] == 13291
    assert m[("GOLDGUINEA", date(2026, 11, 30))] == 10686 and m[("GOLDPETAL", date(2026, 11, 30))] == 1335
    assert ingest_india.family_expiry("GOLD", 2026, 12) == date(2026, 12, 4) and ingest_india.family_expiry("GOLDM", 2026, 11) == date(2026, 11, 5)


def test_amfi_gold_etf_row(now):
    df = ingest_india.parse_amfi_xls(read(G_INDIA / "amfi" / "amsep2026repo.xls", binary=True), now=now)
    d = date(2026, 9, 30)
    assert (_val(df, "AMFI_GOLD_ETF_SCHEMES", d), _val(df, "AMFI_GOLD_ETF_FOLIOS", d)) == (26, 12677259)
    assert _val(df, "AMFI_GOLD_ETF_NET_CR", d) == pytest.approx(4450.61, abs=0.01)
    # SOURCES.md F16 quotes "month-end AUM ₹1,88,934 cr": that figure is the AVERAGE AUM for the month; the month-end column is ₹1,86,310 cr
    assert _val(df, "AMFI_GOLD_ETF_AUM_CR", d) == pytest.approx(186310.4, abs=0.1) and _val(df, "AMFI_GOLD_ETF_AVG_AUM_CR", d) == pytest.approx(188933.9, abs=0.1)
    assert ingest_india.amfi_url(d) == "https://portal.amfiindia.com/spages/amsep2026repo.xls"


# ── local ────────────────────────────────────────────────────────────────────────────────────────────

def test_briefs_validate_dedupe_and_index(store, now, tmp_path):
    # gold_premarket/ is a LIVE folder (the owner's scheduled brief task adds a file most mornings): replay the ten briefs
    # of 9–23 Oct 2026 from a temp copy so the count never moves under the test
    folder = tmp_path / "briefs"
    folder.mkdir()
    for src in sorted((ROOT / "gold_premarket").glob("202610*.json")):
        (folder / src.name).write_bytes(src.read_bytes())
    (folder / "notes.json").write_text("{}")                                     # ignored: not YYYYMMDD.json
    res = ingest_local.ingest_briefs(store, folder, now=now)
    assert res["inserted"] == 10 and res["errors"] == []
    assert ingest_local.ingest_briefs(store, folder, now=now) == {"inserted": 0, "skipped": 10, "errors": []}
    row = db.query_df(store, "SELECT * FROM gold_brief_docs WHERE report_date = DATE '2026-10-23'").iloc[0]
    assert (row["bias"], row["confidence"], row["model_fair_open"], row["open_signal"], row["schema_version"]) == ("bearish", 0.55, 142707.0, "preopen_unavailable", "1.0.0")
    assert json.loads(row["doc"])["gap_model"]["chase_threshold_inr"] == 300
    with pytest.raises(ValueError, match="schema"):
        ingest_local.parse_brief(json.dumps({"meta": {"report_date": "2026-10-23"}, "baseline": {}}), now=now)


def test_preopen_log_migration_flags_stale_rows_by_rule(store, now):
    res = ingest_local.migrate_preopen_log(store, ROOT / "data" / "gold_preopen" / "log.json", now=now)
    assert res["inserted"] >= 4 and {"2026-10-12", "2026-10-15", "2026-10-20", "2026-10-23"} <= set(res["days"])
    rows = db.query_df(store, "SELECT day, error, naive_error, stale_baseline, inputs_json, baseline_session FROM gold_preopen_log ORDER BY day")
    by = {str(r.day)[:10]: r for r in rows.itertuples(index=False)}
    assert (by["2026-10-15"].error, by["2026-10-15"].naive_error) == (-3518.0, -968.0) and by["2026-10-23"].error == -2880.0
    assert by["2026-10-15"].stale_baseline and by["2026-10-20"].stale_baseline and not by["2026-10-12"].stale_baseline
    assert rows["inputs_json"].isna().all() and str(by["2026-10-12"].baseline_session)[:10] == "2026-10-09"
    assert ingest_local.stale_baseline_rule({"day": "2026-10-20", "baseline_source": "MCX settlement 16 Oct", "inr_now": 1, "inr_ref": 2})
    assert not ingest_local.stale_baseline_rule({"day": "2026-10-26", "baseline_source": "MCX settlement 23 Oct", "inr_now": 94.9, "inr_ref": 94.93})


def test_health_row_and_compiled_events(store, now):
    from gold import ingest_cme

    h = ingest_local.health_row({"verdict": {"line": "WEAK WEEK, DOLLAR-DRIVEN · describes, does not predict"}, "gauges": [{"key": "trend"}]}, now=now)
    assert h.iloc[0]["day"] == date(2026, 10, 26) and json.loads(h.iloc[0]["gauges"]) == [{"key": "trend"}]
    ingest_cme.ingest_product_calendar(store, str(G_CME / "product-calendar-new.xml"), now=now)
    ev = ingest_local.compile_events(store, now=now)
    kinds = set(ev["kind"])
    assert {"COT_RELEASE", "COMEX_FND", "COMEX_LTD", "COMEX_FIRST_INTENT", "MCX_EXPIRY", "MCX_HOLIDAY", "FESTIVAL", "MCX_SPECIAL", "BUDGET"} <= kinds
    fnd = ev[(ev["kind"] == "COMEX_FND") & ev["name"].str.contains("GC 2026-12")].iloc[0]
    assert fnd["event_date"] == date(2026, 11, 30)
    assert ev[(ev["kind"] == "MCX_EXPIRY") & ev["name"].str.contains("GOLD Dec-26")].iloc[0]["event_date"] == date(2026, 12, 4)
    cot = ev[(ev["kind"] == "COT_RELEASE") & (ev["event_date"] == date(2026, 10, 31))].iloc[0]
    assert cot["time_ist"] == "01:00"
    assert ev[ev["kind"] == "MCX_SPECIAL"].iloc[0]["time_ist"] == "14:20" and not ev.duplicated(["event_date", "kind", "name"]).any()
    assert pit.release_rule("cot", date(2026, 10, 27)).date() == date(2026, 10, 30)
