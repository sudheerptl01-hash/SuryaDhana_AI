#!/usr/bin/env python3
"""Industry map, sector-index map and equity master (ml/data_ext/).

industry_map.csv     symbol, industry, source_list -- NSE "Industry" from the
                     index constituent lists, first list wins in the order
                     Nifty 500, Midcap 150, Smallcap 250, Microcap 250, Nifty 50.
                     If the file already exists (written by another stream) it
                     is kept unchanged.
sector_index_map.csv industry -> index name as printed in ind_close_all (plus
                     fallback index), verified against every parsed index file.
equity_master.csv    from EQUITY_L.csv (kept unchanged if P1 already wrote it).

POINT-IN-TIME CAVEAT: the constituent lists are a snapshot downloaded on the
build date (2026-10-19). The industry label of a company is close to static,
but WHICH names carry a label is survivorship-biased: a name is classified
only if it belongs to one of these indices today. features.py therefore puts
every unlisted universe name in an explicit "Unclassified" group (no NaN
pattern that marks today's index members), and the report quantifies the
residual bias.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd  # noqa: E402

from ml.extdata import common as C  # noqa: E402

LIST_ORDER = ["ind_nifty500list.csv", "ind_niftymidcap150list.csv",
              "ind_niftysmallcap250list.csv", "ind_niftymicrocap250_list.csv",
              "ind_nifty50list.csv"]

# proposed by the lead (task brief); verified / adjusted by verify_sector_map()
SECTOR_PROPOSAL = {
    "Financial Services": ("Nifty Financial Services", None),
    "Information Technology": ("Nifty IT", None),
    "Healthcare": ("Nifty Healthcare Index", "Nifty Pharma"),
    "Automobile and Auto Components": ("Nifty Auto", None),
    "Fast Moving Consumer Goods": ("Nifty FMCG", None),
    "Metals & Mining": ("Nifty Metal", None),
    "Realty": ("Nifty Realty", None),
    "Oil Gas & Consumable Fuels": ("Nifty Oil & Gas", None),
    "Power": ("Nifty Energy", None),
    "Consumer Durables": ("Nifty Consumer Durables", None),
    "Media Entertainment & Publication": ("Nifty Media", None),
    "Capital Goods": ("Nifty Infrastructure", None),
    "Construction": ("Nifty Infrastructure", None),
    "Chemicals": ("Nifty Commodities", None),
    "Construction Materials": ("Nifty Commodities", None),
}


def build_industry_map(force: bool = False) -> tuple[pd.DataFrame, dict]:
    dest = C.EXT / "industry_map.csv"
    info: dict = {"path": str(dest.relative_to(C.REPO))}
    frames, conflicts = [], []
    for name in LIST_ORDER:
        p = C.RAW_LISTS / name
        d = pd.read_csv(p)
        d.columns = [c.strip() for c in d.columns]
        d = d.rename(columns={"Symbol": "symbol", "Industry": "industry",
                              "ISIN Code": "isin", "Company Name": "company_name",
                              "Series": "series"})
        d["symbol"] = d["symbol"].astype(str).str.strip()
        d["industry"] = d["industry"].astype(str).str.strip()
        d["source_list"] = name
        frames.append(d[["symbol", "industry", "source_list", "isin", "company_name"]])
    allrows = pd.concat(frames, ignore_index=True)
    for sym, g in allrows.groupby("symbol"):
        if g["industry"].nunique() > 1:
            conflicts.append({"symbol": sym, "industries": sorted(g["industry"].unique())})
    first = allrows.drop_duplicates("symbol", keep="first").reset_index(drop=True)
    info.update({"n_symbols": int(len(first)), "conflicts": conflicts,
                 "per_list_rows": allrows.groupby("source_list").size().to_dict(),
                 "industries": first["industry"].value_counts().to_dict()})
    mine = first[["symbol", "industry", "source_list"]].reset_index(drop=True)
    if dest.exists() and not force:
        kept = pd.read_csv(dest)
        same = kept.shape == mine.shape and kept.astype(str).equals(mine.astype(str))
        info["written_by_this_stream"] = bool(same)
        info["note"] = ("unchanged since this stream wrote it" if same else
                        "file already existed (another stream); kept unchanged")
        return kept, info
    mine.to_csv(dest, index=False)
    info["written_by_this_stream"] = True
    return mine, info


def build_equity_master(force: bool = False) -> dict:
    dest = C.EXT / "equity_master.csv"
    marker = "EQUITY_L.csv (archives.nseindia.com, downloaded 2026-10-19)"
    if dest.exists() and not force:
        ex = pd.read_csv(dest)
        mine = "source" in ex.columns and (ex["source"] == marker).all()
        return {"path": str(dest.relative_to(C.REPO)), "written_by_this_stream": bool(mine),
                "rows": int(len(ex)),
                "note": ("unchanged since this stream wrote it" if mine else
                         "file already existed (P1); kept unchanged")}
    e = pd.read_csv(C.RAW_LISTS / "EQUITY_L.csv")
    e.columns = [c.strip() for c in e.columns]
    e = e.rename(columns={"SYMBOL": "symbol", "NAME OF COMPANY": "company_name",
                          "SERIES": "series", "DATE OF LISTING": "listing_date",
                          "PAID UP VALUE": "paid_up_value", "MARKET LOT": "market_lot",
                          "ISIN NUMBER": "isin", "FACE VALUE": "face_value"})
    for c in e.columns:
        if e[c].dtype == object or str(e[c].dtype).startswith("str"):
            e[c] = e[c].astype(str).str.strip()
    e["listing_date"] = pd.to_datetime(e["listing_date"], format="%d-%b-%Y",
                                       errors="coerce").dt.date
    e["source"] = marker
    e.to_csv(dest, index=False)
    return {"path": str(dest.relative_to(C.REPO)), "written_by_this_stream": True,
            "rows": int(len(e)), "series": e["series"].value_counts().to_dict()}


def verify_sector_map(idx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Check every proposed index name against the parsed ind_close_all files
    (presence share overall and per year) and write sector_index_map.csv."""
    files_per_year = idx.groupby(idx["date"].dt.year)["date"].nunique()
    n_files = idx["date"].nunique()
    rows, checks = [], {}
    names = set(idx["index_name"].unique())
    for ind, (primary, fallback) in SECTOR_PROPOSAL.items():
        for nm in [primary] + ([fallback] if fallback else []):
            if nm in checks:
                continue
            sub = idx[idx["index_name"] == nm]
            per_year = (sub.groupby(sub["date"].dt.year)["date"].nunique()
                        / files_per_year).round(4).fillna(0.0)
            checks[nm] = {"present_in_files": int(sub["date"].nunique()),
                          "share_of_files": round(sub["date"].nunique() / n_files, 4),
                          "first": str(sub["date"].min().date()) if len(sub) else None,
                          "last": str(sub["date"].max().date()) if len(sub) else None,
                          "share_by_year": {int(k): float(v) for k, v in per_year.items()},
                          "exists": nm in names}
        rows.append({"industry": ind, "index_name": primary,
                     "fallback_index_name": fallback or "",
                     "primary_share_of_files": checks[primary]["share_of_files"]})
    smap = pd.DataFrame(rows)
    smap.to_csv(C.EXT / "sector_index_map.csv", index=False)
    return smap, {"n_index_files": int(n_files), "index_checks": checks,
                  "similar_names": {nm: sorted(x for x in names
                                               if nm.split()[1].lower() in x.lower())[:8]
                                    for nm in checks if not checks[nm]["exists"]}}


if __name__ == "__main__":
    m, info = build_industry_map()
    print(info)
    print(build_equity_master())
