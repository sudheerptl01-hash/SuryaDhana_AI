#!/usr/bin/env python3
"""History extension (2016-10-03..2021-09-30) of the P3 staging tables, for
the history stream (P4).

The same staging files (fo_daily_stock, index_daily, fo_participant_oi) are
rebuilt from every raw file on disk (min_date=None), so the 2016-2021 rows are
appended with the same schema. The spot close for 2016-2021 F&O rows comes
from P4's ml/data_hist/equity_eod_2016_2021.parquet when P4 has finalised it
(EQ/BE rows); otherwise spot_close and basis_near stay NaN for those rows.
Candidate days are every weekday plus the weekend special sessions of the
period: a 404 marks a holiday, a file whose internal date differs from its
name (an archive echo) is excluded.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd  # noqa: E402

from ml.extdata import common as C  # noqa: E402

HIST_DIR = C.ML / "data_hist"


def hist_spot() -> tuple[pd.DataFrame | None, str]:
    final = HIST_DIR / "equity_eod_2016_2021.parquet"
    if not final.exists():
        return None, "P4 equity_eod_2016_2021.parquet not final yet: hist spot_close/basis NaN"
    e = pd.read_parquet(final, columns=["date", "ticker", "series", "close", "turnover"])
    e["date"] = pd.to_datetime(e["date"])
    e = e[e["series"].isin(["EQ", "BE"])]
    e = e.sort_values(["date", "ticker", "series"]).drop_duplicates(["date", "ticker"], keep="first")
    return e[["date", "ticker", "close", "turnover"]], f"{final.relative_to(C.REPO)} (EQ/BE)"


def hist_coverage(fo: pd.DataFrame, idx: pd.DataFrame, part: pd.DataFrame) -> dict:
    from ml.extdata.download import load_status
    cand = C.hist_candidate_days()
    out = {"window": f"{C.HIST_START}..{C.HIST_END}", "candidate_days": len(cand)}
    meta = json.loads((C.OUT / "parse_meta.json").read_text())
    p4 = None
    sp = HIST_DIR / "sessions_2016_2021.csv"
    if sp.exists():
        s = pd.read_csv(sp)
        col = next((c for c in s.columns if c.lower() in ("date", "session", "session_date")), None)
        if col:
            p4 = set(pd.to_datetime(s[col]).dt.date)
    per = {}
    for kind, frame in (("fo", fo), ("indices", idx), ("participant", part)):
        have = {d for d in pd.to_datetime(frame["date"]).dt.date.unique()
                if C.HIST_START <= d <= C.HIST_END}
        st = load_status(kind)
        n404 = sum(1 for r in st.values() if r.get("status") == "404" and r.get("date")
                   and C.HIST_START.isoformat() <= r["date"] <= C.HIST_END.isoformat())
        excl = [m["file"] for m in meta[kind] if not m.get("date_ok")
                and m.get("file_date", "9999") <= C.HIST_END.isoformat()]
        rec = {"sessions_with_file": len(have), "http_404_days": n404,
               "excluded_content_date_mismatch": excl,
               "by_year": {int(y): sum(1 for d in have if d.year == y)
                           for y in range(C.HIST_START.year, C.HIST_END.year + 1)}}
        if p4 is not None:
            rec["p4_sessions_without_file"] = sorted(d.isoformat() for d in p4 - have
                                                     if C.HIST_START <= d <= C.HIST_END)
            rec["files_on_non_p4_days"] = sorted(d.isoformat() for d in have - p4)
        per[kind] = rec
    out["per_source"] = per
    days = {k: {d for d in pd.to_datetime(f["date"]).dt.date.unique() if C.HIST_START <= d <= C.HIST_END}
            for k, f in (("fo", fo), ("indices", idx), ("participant", part))}
    union = set().union(*days.values())
    out["cross_source_gaps"] = {k: sorted(d.isoformat() for d in union - v) for k, v in days.items()}
    meta_p = meta.get("participant", [])
    out["participant_files_title_without_year"] = sorted(m["file"] for m in meta_p
                                                        if m.get("title_without_year"))
    out["participant_files_without_title_accepted"] = sorted(
        m["file"] for m in meta_p if m.get("title_missing") and m.get("date_ok"))
    out["p4_session_list"] = "ml/data_hist/sessions_2016_2021.csv" if p4 is not None else \
        "not available at build time"
    f = fo[(fo["date"] <= pd.Timestamp(C.HIST_END)) & (fo["has_future"] == 1)]
    out["fo_rows_hist"] = int(len(fo[fo["date"] <= pd.Timestamp(C.HIST_END)]))
    out["fo_members_per_year_hist"] = {int(y): round(float(s.groupby("date")["ticker"].nunique().mean()), 1)
                                       for y, s in f.groupby(f["date"].dt.year)}
    out["hist_fut_rows_with_spot_share"] = round(float(f["spot_close"].notna().mean()), 4) if len(f) else None
    return out
