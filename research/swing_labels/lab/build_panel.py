#!/usr/bin/env python3
"""Build the clean, bias-controlled research panel from raw NSE files.

Fixes the audit's data defects at the source:
  * entity identity = ISIN (union-find bridges ISIN changes that occur with
    symbol continuity, e.g. face-value splits) -> renames don't fragment
    history and reused symbols don't splice unrelated companies;
  * corporate-action adjustment derived from NSE's own PREV_CLOSE field
    (ratio = prev_close_file / previous close on ex-dates) -> back-adjusted
    OHLC and volume, no external CA feed required;
  * one row per (entity, date), EQ preferred over BE/BZ;
  * in-file date validated against the requested date;
  * segment breaks (extreme ratios, >45-day gaps) flagged so labels never
    span them.
Outputs: panel.parquet, index.parquet, sectors.parquet, build_meta.json
"""
import glob
import json
import os
import sys
import zipfile
from multiprocessing import Pool

import numpy as np
import pandas as pd
import requests

LAB = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(LAB, "raw")
SERIES_KEEP = {"EQ", "BE", "BZ"}
META = {}


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(),
                         errors="coerce")


def read_zip_csv(path):
    with zipfile.ZipFile(path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(name) as fh:
            return pd.read_csv(fh, low_memory=False)


def parse_day(args):
    ymd, bhav_path = args
    d = pd.Timestamp(ymd)
    kind = bhav_path.rsplit(".", 2)[-2]
    try:
        df = read_zip_csv(bhav_path)
    except Exception as exc:  # noqa: BLE001
        return None, f"{ymd} bhav read fail {exc}"
    df.columns = [str(c).strip() for c in df.columns]
    if kind == "L":
        df = df[df["SERIES"].astype(str).str.strip().isin(SERIES_KEEP)]
        out = pd.DataFrame({
            "symbol": df["SYMBOL"].astype(str).str.strip(),
            "series": df["SERIES"].astype(str).str.strip(),
            "isin": df["ISIN"].astype(str).str.strip(),
            "open": num(df["OPEN"]), "high": num(df["HIGH"]),
            "low": num(df["LOW"]), "close": num(df["CLOSE"]),
            "prev_close_file": num(df["PREVCLOSE"]),
            "volume": num(df["TOTTRDQTY"]), "turnover": num(df["TOTTRDVAL"]),
            "trades": num(df["TOTALTRADES"]),
            "file_date": pd.to_datetime(df["TIMESTAMP"].astype(str).str.strip(),
                                        format="%d-%b-%Y", errors="coerce"),
        })
    else:
        df = df[df["SctySrs"].astype(str).str.strip().isin(SERIES_KEEP)]
        out = pd.DataFrame({
            "symbol": df["TckrSymb"].astype(str).str.strip(),
            "series": df["SctySrs"].astype(str).str.strip(),
            "isin": df["ISIN"].astype(str).str.strip(),
            "open": num(df["OpnPric"]), "high": num(df["HghPric"]),
            "low": num(df["LwPric"]), "close": num(df["ClsPric"]),
            "prev_close_file": num(df["PrvsClsgPric"]),
            "volume": num(df["TtlTradgVol"]), "turnover": num(df["TtlTrfVal"]),
            "trades": num(df["TtlNbOfTxsExctd"]),
            "file_date": pd.to_datetime(df["TradDt"].astype(str).str.strip(),
                                        errors="coerce"),
        })
    out["fmt"] = kind
    out["date"] = d
    sec_path = os.path.join(RAW, "sec", f"{ymd}.csv")
    note = None
    if os.path.exists(sec_path):
        try:
            s = pd.read_csv(sec_path, skipinitialspace=True, low_memory=False)
            s.columns = [str(c).strip() for c in s.columns]
            s["SERIES"] = s["SERIES"].astype(str).str.strip()
            s = s[s["SERIES"].isin(SERIES_KEEP)]
            sec = pd.DataFrame({
                "symbol": s["SYMBOL"].astype(str).str.strip(),
                "series": s["SERIES"],
                "vwap": num(s["AVG_PRICE"]),
                "deliv_qty": num(s["DELIV_QTY"]),
                "deliv_pct": num(s["DELIV_PER"]),
                "sec_close": num(s["CLOSE_PRICE"]),
            }).drop_duplicates(["symbol", "series"])
            out = out.merge(sec, on=["symbol", "series"], how="left")
        except Exception as exc:  # noqa: BLE001
            note = f"{ymd} sec parse fail {exc}"
    else:
        note = f"{ymd} no sec file"
    for c in ("vwap", "deliv_qty", "deliv_pct", "sec_close"):
        if c not in out.columns:
            out[c] = np.nan
    return out, note


def parse_idx(path):
    ymd = os.path.basename(path)[:8]
    try:
        df = pd.read_csv(path)
    except Exception:  # noqa: BLE001
        return None
    df.columns = [str(c).strip() for c in df.columns]
    return pd.DataFrame({
        "date": pd.Timestamp(ymd),
        "index": df["Index Name"].astype(str).str.strip(),
        "open": num(df["Open Index Value"]), "high": num(df["High Index Value"]),
        "low": num(df["Low Index Value"]), "close": num(df["Closing Index Value"]),
    })


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        p = self.p
        p.setdefault(x, x)
        root = x
        while p[root] != root:
            root = p[root]
        while p[x] != root:
            p[x], x = root, p[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if ra < rb:
                self.p[rb] = ra
            else:
                self.p[ra] = rb


def main():
    files = {}
    for p in glob.glob(os.path.join(RAW, "bhav", "*.zip")):
        ymd, kind = os.path.basename(p).split(".")[:2]
        if ymd not in files or kind == "L":
            files[ymd] = p
    days = sorted(files.items())
    print(f"parsing {len(days)} trading days", flush=True)
    with Pool(4) as pool:
        res = pool.map(parse_day, days, chunksize=8)
    notes = [n for _, n in res if n]
    frames = [f for f, _ in res if f is not None]
    panel = pd.concat(frames, ignore_index=True)
    META["parse_notes_count"] = len(notes)
    META["parse_notes_sample"] = notes[:20]
    print(f"raw rows {len(panel):,}", flush=True)

    # --- turnover unit check (must be rupees) ---------------------------------
    for fmt in ("L", "U"):
        sub = panel[(panel.fmt == fmt) & (panel.volume > 1000) & (panel.close > 0)]
        if len(sub):
            ratio = float((sub.turnover / (sub.volume * sub.close)).median())
            META[f"turnover_unit_ratio_{fmt}"] = ratio
            if 1e-6 < ratio < 1e-4:
                panel.loc[panel.fmt == fmt, "turnover"] *= 1e5   # lakhs -> rupees
                META[f"turnover_scaled_{fmt}"] = "lakhs->rupees"
    # --- sanity -------------------------------------------------------------------
    panel = panel[(panel.close > 0) & panel.close.notna() & (panel.symbol.str.len() > 0)]
    panel["date_mismatch"] = panel.file_date.notna() & (panel.file_date != panel.date)
    META["date_mismatch_rows"] = int(panel.date_mismatch.sum())
    mm = panel.sec_close.notna() & ((panel.sec_close - panel.close).abs() > 0.011)
    META["sec_vs_bhav_close_mismatch_rows"] = int(mm.sum())
    bad_isin = ~panel["isin"].str.match(r"^IN[A-Z0-9]{10}$", na=False)
    panel.loc[bad_isin, "isin"] = "SYM:" + panel.loc[bad_isin, "symbol"]
    META["rows_without_valid_isin"] = int(bad_isin.sum())

    # --- entity master (union-find over ISIN) -----------------------------------
    uf = UF()
    for i in panel["isin"].unique():
        uf.find(i)
    pri = panel.series.map({"EQ": 0, "BE": 1, "BZ": 2})
    sd = (panel.assign(_p=pri).sort_values(["symbol", "date", "_p"])
               .drop_duplicates(["symbol", "date"])[["symbol", "date", "isin"]])
    sd["prev_isin"] = sd.groupby("symbol")["isin"].shift()
    sd["prev_date"] = sd.groupby("symbol").date.shift()
    tr = sd[sd["prev_isin"].notna() & (sd["isin"] != sd["prev_isin"])]
    bridged, reuse = 0, 0
    for r in tr.itertuples():
        if (r.date - r.prev_date).days <= 10:
            uf.union(r.isin, r.prev_isin)
            bridged += 1
        else:
            reuse += 1
    META["isin_changes_bridged_by_symbol_continuity"] = bridged
    META["symbol_reuse_not_bridged"] = reuse
    panel["entity"] = panel["isin"].map(lambda x: uf.find(x))
    sym_per_entity = panel.groupby("entity").symbol.nunique()
    META["entities"] = int(panel.entity.nunique())
    META["entities_with_multiple_symbols(renames)"] = int((sym_per_entity > 1).sum())

    # --- one row per (entity, date) ---------------------------------------------
    panel["_p"] = panel.series.map({"EQ": 0, "BE": 1, "BZ": 2})
    before = len(panel)
    panel = (panel.sort_values(["entity", "date", "_p", "turnover"],
                               ascending=[True, True, True, False])
                  .drop_duplicates(["entity", "date"]).drop(columns="_p"))
    META["dup_entity_date_rows_dropped"] = int(before - len(panel))
    panel = panel.sort_values(["entity", "date"]).reset_index(drop=True)

    # --- continuity diagnostics (NSE PREV_CLOSE is NOT CA-adjusted) -------------
    g = panel.groupby("entity", sort=False)
    close_prev = g.close.shift()
    date_prev = g.date.shift()
    panel["gap_prev_days"] = (panel.date - date_prev).dt.days
    pcf = panel.prev_close_file
    pc_mis = close_prev.notna() & pcf.notna() & ((pcf - close_prev).abs() > np.maximum(0.011, 0.0005 * close_prev))
    META["prev_close_mismatch_rows"] = int(pc_mis.sum())
    META["prev_close_mismatch_by_date_top"] = (panel.loc[pc_mis].groupby("date").size()
                                               .sort_values(ascending=False).head(10)
                                               .rename(lambda d: str(d.date())).to_dict())
    panel["raw_open"] = panel.open
    panel["raw_close"] = panel.close

    # --- corporate-action adjustment from NSE Bc (book closure) records ---------
    import ca as CA
    fv = {}
    try:
        os.environ.setdefault("REQUESTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
        rq = requests.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
                          headers={"User-Agent": "suryadhana-research/1.0"}, timeout=40)
        if rq.status_code == 200:
            from io import StringIO
            eq = pd.read_csv(StringIO(rq.text))
            eq.columns = [c.strip() for c in eq.columns]
            fv = dict(zip(eq["SYMBOL"].str.strip(), pd.to_numeric(eq["FACE VALUE"], errors="coerce")))
    except Exception as exc:  # noqa: BLE001
        META["equity_l_error"] = str(exc)
    events, ratio, block, ca_stats = CA.build_events(panel, face_values=fv)
    META["ca"] = ca_stats
    events.to_parquet(os.path.join(LAB, "ca_events.parquet"), index=False)
    panel["ca_ratio"] = ratio
    panel["ca_event"] = ratio != 1.0
    # residual guard: after adjustment, an unexplained >35% one-day move (beyond any
    # NSE band) or a prev-close mismatch >5% is treated as a label block.
    lr_adj = np.log(panel.close.values / (close_prev.values * np.where(ratio != 1.0, ratio, 1.0)))
    resid = np.abs(lr_adj) > np.log(1.35)
    pc_big = (pc_mis & ((pcf - close_prev).abs() / close_prev > 0.05)).values
    panel["label_block"] = block | (resid & ~np.isnan(lr_adj)) | pc_big
    META["label_block_rows"] = int(panel.label_block.sum())
    META["label_block_residual_jumps"] = int((resid & ~np.isnan(lr_adj)).sum())
    META["label_block_prevclose_gap"] = int(pc_big.sum())
    long_gap = panel.gap_prev_days > 45
    panel["seg_break"] = long_gap.fillna(False)
    META["seg_breaks"] = int(panel.seg_break.sum())
    META["ca_events_rows"] = int(panel.ca_event.sum())
    lr = np.log(panel.ca_ratio.values)
    lr_s = pd.Series(lr)
    total = lr_s.groupby(panel.entity.values).transform("sum").values
    cum = lr_s.groupby(panel.entity.values).cumsum().values
    factor = np.exp(total - cum)
    panel["adj_factor"] = factor
    panel["raw_close"] = panel.close
    for c in ("open", "high", "low", "close", "vwap"):
        panel[c] = panel[c] * factor
    panel["volume_adj"] = panel.volume / factor
    panel["deliv_qty_adj"] = panel.deliv_qty / factor
    panel["row_num"] = panel.groupby("entity").cumcount()

    keep = ["date", "entity", "symbol", "isin", "series", "fmt", "open", "high", "low",
            "close", "raw_close", "vwap", "prev_close_file", "volume", "volume_adj",
            "turnover", "trades", "deliv_qty", "deliv_qty_adj", "deliv_pct",
            "adj_factor", "ca_event", "ca_ratio", "seg_break", "label_block", "gap_prev_days",
            "date_mismatch", "row_num", "raw_open"]
    panel = panel[keep]
    for c in ("open", "high", "low", "close", "raw_close", "vwap", "prev_close_file",
              "volume", "volume_adj", "turnover", "trades", "deliv_qty", "deliv_qty_adj",
              "deliv_pct", "adj_factor", "ca_ratio"):
        panel[c] = panel[c].astype("float64")
    panel.to_parquet(os.path.join(LAB, "panel.parquet"), index=False)
    META["rows"] = int(len(panel))
    META["dates"] = [str(panel.date.min().date()), str(panel.date.max().date())]
    META["trading_days"] = int(panel.date.nunique())
    print(f"panel rows {len(panel):,}  entities {META['entities']:,}", flush=True)

    # --- index closes -----------------------------------------------------------
    paths = sorted(glob.glob(os.path.join(RAW, "idx", "*.csv")))
    with Pool(4) as pool:
        idx = pool.map(parse_idx, paths, chunksize=16)
    idx = pd.concat([x for x in idx if x is not None], ignore_index=True)
    idx.to_parquet(os.path.join(LAB, "index.parquet"), index=False)
    META["index_rows"] = int(len(idx))
    META["index_names_sample"] = sorted(idx["index"].unique().tolist())[:400]

    # --- sector map from NSE index constituent lists ----------------------------
    os.environ.setdefault("REQUESTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
    rows = []
    for lst in ("ind_niftytotalmarket_list.csv", "ind_nifty500list.csv",
                "ind_niftymicrocap250_list.csv"):
        try:
            rq = requests.get(f"https://nsearchives.nseindia.com/content/indices/{lst}",
                              headers={"User-Agent": "suryadhana-research/1.0"}, timeout=30)
            if rq.status_code == 200:
                from io import StringIO
                t = pd.read_csv(StringIO(rq.text))
                t.columns = [c.strip() for c in t.columns]
                rows.append(pd.DataFrame({"isin": t["ISIN Code"].str.strip(),
                                          "industry": t["Industry"].str.strip(),
                                          "src": lst}))
        except Exception as exc:  # noqa: BLE001
            META.setdefault("sector_errors", []).append(f"{lst}: {exc}")
    if rows:
        sec = pd.concat(rows).drop_duplicates("isin")
        isin_ent = panel[["isin", "entity"]].drop_duplicates()
        sec = sec.merge(isin_ent, on="isin", how="inner").drop_duplicates("entity")
        sec[["entity", "industry"]].to_parquet(os.path.join(LAB, "sectors.parquet"), index=False)
        META["entities_with_sector"] = int(len(sec))
    with open(os.path.join(LAB, "build_meta.json"), "w") as fh:
        json.dump(META, fh, indent=1, default=str)
    print(json.dumps({k: v for k, v in META.items() if k != "index_names_sample"}, indent=1, default=str))


if __name__ == "__main__":
    sys.exit(main())
