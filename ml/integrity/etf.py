#!/usr/bin/env python3
"""Point-in-time ETF list from the PR bundles' etf files, and the EQUITY_L equity master.

etf_list.csv     symbol, first_seen, last_seen, n_days, underlying (last non-empty),
                 security, series_seen  -- union of SYMBOL over every etf file on disk
equity_master.csv EQUITY_L.csv (currently listed equities): symbol, company, series,
                 listing_date, paid_up_value, market_lot, isin, face_value

Comparison with the label study's name rule (ml/label_study.py ETF_PATTERN and
ETF_NAME_EXCEPTIONS; LABEL_STUDY.md "Labels to carry", item 5) over the tickers of
the store (EQ/BE rows of the parquet export) and over the v1 dataset's tickers.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/etf.py
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from ml.integrity.common import DATA_EXT, DATA_V1, EOD_EXPORT, OUT, RAW_MASTER, log, wjson  # noqa: E402
from ml.integrity.corporate_actions import read_members  # noqa: E402

ETF_PATTERN = r"(?:BEES|ETF|LIQUID|LIQID|GILT|BETF|SENSEX|NIFTY|GOLD|SILV|CASE$|360$|BND$|BETA$|ADD$)"
ETF_NAME_EXCEPTIONS = {"BETA", "SKYGOLD", "SILVERTUC", "SHANTIGOLD", "GOLDIAM", "PNBGILTS", "DECNGOLD"}


def etf_list() -> tuple[pd.DataFrame, dict]:
    etf, st = read_members("etf")
    etf = etf[etf["SYMBOL"] != ""]
    g = etf.sort_values("file_date").groupby("SYMBOL")
    out = pd.DataFrame({
        "first_seen": g["file_date"].min().dt.strftime("%Y-%m-%d"),
        "last_seen": g["file_date"].max().dt.strftime("%Y-%m-%d"),
        "n_days": g["file_date"].nunique(),
        "underlying": g["UNDERLYING"].agg(lambda s: next((x for x in s[::-1] if x), "")),
        "security": g["SECURITY"].last(),
        "series_seen": g["SERIES"].agg(lambda s: ",".join(sorted(set(s)))),
    }).reset_index().rename(columns={"SYMBOL": "symbol"})
    return out, st


def equity_master() -> pd.DataFrame:
    raw = (RAW_MASTER / "EQUITY_L.csv").read_bytes()
    m = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin-1")
    m.columns = [c.strip().upper() for c in m.columns]
    m = m.apply(lambda s: s.str.strip())
    out = pd.DataFrame({
        "symbol": m["SYMBOL"], "company": m["NAME OF COMPANY"], "series": m["SERIES"],
        "listing_date": pd.to_datetime(m["DATE OF LISTING"], format="%d-%b-%Y", errors="coerce").dt.strftime("%Y-%m-%d"),
        "paid_up_value": pd.to_numeric(m["PAID UP VALUE"], errors="coerce"),
        "market_lot": pd.to_numeric(m["MARKET LOT"], errors="coerce"),
        "isin": m["ISIN NUMBER"], "face_value": pd.to_numeric(m["FACE VALUE"], errors="coerce")})
    return out


def regex_etf(tickers: pd.Series) -> pd.Series:
    t = tickers.astype(str)
    return t.str.contains(ETF_PATTERN, regex=True) & ~t.isin(ETF_NAME_EXCEPTIONS)


def main(argv=None) -> int:
    t0 = time.time()
    DATA_EXT.mkdir(parents=True, exist_ok=True)
    etf, st = etf_list()
    etf.to_csv(DATA_EXT / "etf_list.csv", index=False)
    em = equity_master()
    em.to_csv(DATA_EXT / "equity_master.csv", index=False)
    eod = pd.read_parquet(EOD_EXPORT, columns=["date", "ticker"])
    store_t = pd.Series(sorted(eod["ticker"].unique()))
    etfs = set(etf["symbol"])
    res = {"etf_files": st, "etf_symbols_union": int(len(etf)),
           "equity_master_rows": int(len(em)),
           "equity_master_isin_prefix": {k: int(v) for k, v in em["isin"].str[:3].value_counts().items()},
           "etf_symbols_in_equity_master": sorted(etfs & set(em["symbol"]))}
    for name, tick in (("store_eq_be", store_t),
                       ("v1_dataset", pd.Series(sorted(pd.read_parquet(DATA_V1 / "model_dataset.parquet",
                                                                       columns=["ticker"])["ticker"].unique())))):
        rx = set(tick[regex_etf(tick)])
        inl = set(tick[tick.isin(etfs)])
        res[name] = {"tickers": int(len(tick)), "etf_by_list": int(len(inl)), "etf_by_regex": int(len(rx)),
                     "both": int(len(rx & inl)),
                     "regex_only": sorted(rx - inl), "list_only": sorted(inl - rx)}
    v1 = pd.read_parquet(DATA_V1 / "model_dataset.parquet", columns=["date", "ticker"])
    res["v1_dataset"]["rows"] = int(len(v1))
    res["v1_dataset"]["etf_rows_by_list"] = int(v1["ticker"].isin(etfs).sum())
    res["v1_dataset"]["etf_row_share_by_list"] = float(v1["ticker"].isin(etfs).mean())
    res["v1_dataset"]["etf_rows_by_regex"] = int(regex_etf(v1["ticker"]).sum())
    # list-only names: what the etf files say they track
    lo = etf[etf["symbol"].isin(res["v1_dataset"]["list_only"] + res["store_eq_be"]["list_only"])]
    res["list_only_detail"] = lo[["symbol", "security", "underlying", "first_seen", "last_seen"]].drop_duplicates(
        "symbol").to_dict("records")
    ro = sorted(set(res["store_eq_be"]["regex_only"]) | set(res["v1_dataset"]["regex_only"]))
    res["regex_only_detail"] = em[em["symbol"].isin(ro)][["symbol", "company", "isin"]].to_dict("records")
    res["regex_only_not_in_equity_master"] = sorted(set(ro) - set(em["symbol"]))
    res["seconds"] = round(time.time() - t0, 1)
    wjson(OUT / "etf.json", res)
    log(f"etf: union {len(etf)} symbols; v1 dataset ETF tickers by list {res['v1_dataset']['etf_by_list']} "
        f"({res['v1_dataset']['etf_row_share_by_list']:.4f} of rows), by regex {res['v1_dataset']['etf_by_regex']}; "
        f"regex-only {len(res['v1_dataset']['regex_only'])}, list-only {len(res['v1_dataset']['list_only'])}", "etf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
