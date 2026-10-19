"""Corporate-action engine from NSE's official book-closure (Bc) files.

NSE bhavcopy PREV_CLOSE is NOT adjusted for corporate actions (verified on
TATASTEEL 1:10 split 28-Jul-2022, IRCTC 1:5 split 28-Oct-2021, BAJFINANCE
split+bonus 16-Jun-2025), so adjustment must come from CA records.

Factor convention: pre-ex prices are multiplied by `factor` (<1 for splits,
bonuses, dividends; >1 for consolidations).
"""
import glob
import os
import re

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))

BLOCK_WORDS = ("DEMERGER", "DE-MERGER", "SCHEME", "SCH AGMT", "SCH OF", "ARRANGEMENT",
               "CAPITAL REDUCTION", "REDUCTION OF CAPITAL", "AMALGAMATION", "SPIN", "HIVE",
               "BONUS DEB", "DEBT", "PARTLY PAID", "RETURN OF CAPITAL", "CAP RED", "NCRPS",
               "PREF", "CCPS", "WRNT", "WARRANT", "OCRPS")
NUM = r"(\d+(?:\.\d+)?)"
RE_BONUS = re.compile(r"BONUS\W*" + NUM + r"\s*:\s*" + NUM)
RE_SPLIT_KW = re.compile(r"FV\s*SPL|FVSPL|SPLIT|SUB[\s-]*DIV")
RE_SPLIT = re.compile(r"(?:FV\s*SPL[A-Z]*|SPLIT|SUB[\s-]*DIV[A-Z]*)[^0-9]{0,40}?" + NUM
                      + r"[^0-9]{0,30}?TO[^0-9]{0,15}?" + NUM)
RE_DIV_KW = re.compile(r"INTDIV|FINDIV|SPLDIV|DIVIDEND|DIVDEND|(?<![A-Z-])DIV(?![A-Z])|DIV[-/ ]")
RE_CONS = re.compile(r"CONSOL\w*\s*(?:FRM|FROM)?\s*(?:R[SE]\.?\s*)?" + NUM
                     + r"\s*(?:/-)?\s*TO\s*(?:R[SE]\.?\s*)?" + NUM)
RE_DIV_AMT = re.compile(r"R[SE]\.?\s*-?\s*" + NUM)
RE_RIGHTS = re.compile(r"RIGHTS?\W*(\d+)\s*:\s*(\d+)(?:.*?@\s*(?:PRM|PREM(?:IUM)?)\s*(?:R[SE]\.?\s*)?"
                       + NUM + r")?")


def _parse_date(s):
    s = str(s).strip()
    if not s or s in ("-", "nan"):
        return pd.NaT
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    return pd.NaT


def load_bc():
    rows = []
    for p in sorted(glob.glob(os.path.join(LAB, "raw", "bc", "*.csv"))):
        try:
            df = pd.read_csv(p, dtype=str, encoding="latin1", skipinitialspace=True)
        except Exception:  # noqa: BLE001
            continue
        df.columns = [c.strip().upper() for c in df.columns]
        if "EX_DT" not in df.columns or "PURPOSE" not in df.columns:
            continue
        rows.append(df[["SYMBOL", "SECURITY", "EX_DT", "PURPOSE"]])
    bc = pd.concat(rows, ignore_index=True)
    bc["SYMBOL"] = bc["SYMBOL"].astype(str).str.strip()
    bc["PURPOSE"] = bc["PURPOSE"].astype(str).str.strip().str.upper()
    bc["SECURITY"] = bc["SECURITY"].astype(str)
    bc = bc[~bc["SECURITY"].str.upper().str.contains("NCD|BOND|DEBENTURE|SR\\.|SERIES|% ", regex=True)]
    bc["ex_date"] = bc["EX_DT"].map(_parse_date)
    bc = bc.dropna(subset=["ex_date"]).drop_duplicates(["SYMBOL", "ex_date", "PURPOSE"])
    return bc


def classify(purpose):
    """Return list of (kind, params) parsed from one PURPOSE string."""
    p = re.sub(r"\s+", " ", purpose.upper())
    out = []
    if any(w in p for w in BLOCK_WORDS):
        out.append(("block", {"desc": "unadjustable"}))
        return out
    share_factor = 1.0
    descs = []
    for a, b in RE_BONUS.findall(p):
        a, b = float(a), float(b)
        if a > 0 and b > 0:
            share_factor *= b / (a + b)
            descs.append(f"bonus {a:g}:{b:g}")
    for old, new in RE_CONS.findall(p):
        old, new = float(old), float(new)
        if old > 0 and new > 0:
            share_factor *= new / old
            descs.append(f"consol {old:g}->{new:g}")
    if "CONSOL" not in p:
        for old, new in RE_SPLIT.findall(p):
            old, new = float(old), float(new)
            if old > 0 and new > 0 and new < old:
                share_factor *= new / old
                descs.append(f"split {old:g}->{new:g}")
    if descs:
        out.append(("shares", {"factor": share_factor, "desc": "+".join(descs)}))
    elif RE_SPLIT_KW.search(p) or "BONUS" in p or "CONSOL" in p:
        out.append(("shares_unknown", {"desc": "unparsed:" + p[:40]}))
    for a, b, prem in RE_RIGHTS.findall(p):
        if prem == "":
            out.append(("block", {"desc": "rights_no_price"}))
        else:
            out.append(("rights", {"a": float(a), "b": float(b), "prem": float(prem),
                                   "desc": f"rights {a}:{b}@{prem}"}))
    is_split = bool(RE_SPLIT_KW.search(p))
    if RE_DIV_KW.search(p.replace("SUB-DIV", "").replace("SUBDIV", "").replace("SUB DIV", "")) and not descs and not is_split:
        amts = [float(x) for x in RE_DIV_AMT.findall(p)]
        if amts and " UT" not in p and "PR UT" not in p:
            out.append(("dividend", {"amount": sum(amts), "desc": f"div {sum(amts):g}"}))
    return out


def build_events(panel, face_values=None):
    """Map Bc records to panel rows and compute per-row CA factors.

    Returns (events DataFrame, factor array per row (ratio applied at ex row),
             label_block bool array, stats dict).
    panel must be sorted by entity, date with raw columns open/close (raw).
    """
    bc = load_bc()
    stats = {"bc_records": int(len(bc))}
    n = len(panel)
    ratio = np.ones(n)
    block = np.zeros(n, bool)
    # index: symbol -> array of (date, row)
    sym_rows = panel.groupby("symbol").indices
    dates = panel["date"].values
    ent = panel["entity"].values
    raw_c = panel["raw_close"].values
    raw_o = panel["raw_open"].values
    ev_rows = []
    cnt = {}
    for r in bc.itertuples(index=False):
        kinds = classify(r.PURPOSE)
        if not kinds:
            continue
        rows = sym_rows.get(r.SYMBOL)
        if rows is None:
            cnt["unmapped_symbol"] = cnt.get("unmapped_symbol", 0) + 1
            continue
        dts = dates[rows]
        k = np.searchsorted(dts, np.datetime64(r.ex_date))
        if k >= len(rows) or (dts[k] - np.datetime64(r.ex_date)).astype("timedelta64[D]").astype(int) > 10:
            cnt["no_session_near_exdate"] = cnt.get("no_session_near_exdate", 0) + 1
            continue
        row = rows[k]
        for kind, prm in kinds:
            cnt[kind] = cnt.get(kind, 0) + 1
            ev_rows.append({"row": int(row), "symbol": r.SYMBOL, "ex_date": r.ex_date, "kind": kind,
                            "purpose": r.PURPOSE, **{k_: v for k_, v in prm.items() if k_ != "desc"},
                            "desc": prm.get("desc", "")})
    ev = pd.DataFrame(ev_rows)
    stats["parsed_counts"] = cnt
    if ev.empty:
        return ev, ratio, block, stats
    ev["key"] = ev["kind"] + "|" + ev["desc"].astype(str)
    ev = ev.drop_duplicates(["row", "key"])
    # separate same-day records (e.g. FV split + bonus with one ex-date) -> one combined factor
    sh = ev[ev["kind"] == "shares"]
    if len(sh):
        comb = (sh.groupby("row")
                  .agg(factor=("factor", "prod"), desc=("desc", lambda s: "+".join(sorted(s))),
                       symbol=("symbol", "first"), ex_date=("ex_date", "first"),
                       purpose=("purpose", lambda s: " | ".join(s)))
                  .reset_index())
        comb["kind"] = "shares"
        comb["key"] = "shares|" + comb["desc"]
        ev = pd.concat([ev[ev["kind"] != "shares"], comb], ignore_index=True)
    stats["share_events_after_combining"] = int((ev["kind"] == "shares").sum())
    # exchange often re-lists the same action with an ex-date shifted by 1-7 days;
    # keep one event per (entity, kind, desc) inside any 10-calendar-day cluster.
    ev["entity"] = ent[ev["row"].values]
    ev = ev.sort_values(["entity", "kind", "desc", "ex_date"]).reset_index(drop=True)
    gap = ev.groupby(["entity", "kind", "desc"])["ex_date"].diff().dt.days
    dup = gap.notna() & (gap <= 10) & ev["kind"].isin(["shares", "dividend", "rights", "shares_unknown"])
    stats["duplicate_events_dropped"] = int(dup.sum())
    ev = ev[~dup].reset_index(drop=True)
    applied = []
    located_rows = set()
    val = {"split_bonus_total": 0, "split_bonus_located": 0, "split_bonus_unlocated": 0}
    for e in ev.itertuples(index=False):
        row = e.row
        if row == 0 or ent[row - 1] != ent[row]:
            continue
        prev_c = raw_c[row - 1]
        if e.kind == "block":
            block[row] = True
            applied.append((row, "block", 1.0))
        elif e.kind == "shares":
            f = float(e.factor)
            val["split_bonus_total"] += 1
            # locate the day (ex row +/- 3 sessions, same entity) whose raw jump best matches f
            best, best_err = None, 9e9
            for dk in (0, 1, -1, 2, -2, 3, -3):
                j = row + dk
                if j <= 0 or j >= n or ent[j] != ent[row] or ent[j - 1] != ent[row]:
                    continue
                jr = raw_o[j] / raw_c[j - 1] if raw_o[j] > 0 else raw_c[j] / raw_c[j - 1]
                err = abs(np.log(jr / f))
                if err < best_err:
                    best, best_err = j, err
            if best is not None and best in located_rows:
                val["split_bonus_duplicate_location_skipped"] = val.get("split_bonus_duplicate_location_skipped", 0) + 1
                continue
            if best is not None and best_err < np.log(1.25):
                located_rows.add(best)
                ratio[best] *= f
                applied.append((best, "shares", f))
                val["split_bonus_located"] += 1
            else:
                block[row] = True
                val["split_bonus_unlocated"] += 1
                applied.append((row, "shares_unlocated", 1.0))
        elif e.kind == "shares_unknown":
            best, best_r = None, 1.0
            for dk in (0, 1, -1, 2, -2, 3, -3):
                j = row + dk
                if j <= 0 or j >= n or ent[j] != ent[row] or ent[j - 1] != ent[row]:
                    continue
                jr = raw_o[j] / raw_c[j - 1] if raw_o[j] > 0 else raw_c[j] / raw_c[j - 1]
                if abs(np.log(jr)) > abs(np.log(best_r)):
                    best, best_r = j, jr
            if best is not None and (best_r < 0.75 or best_r > 1.33):
                ratio[best] *= best_r
                applied.append((best, "shares_inferred", best_r))
            else:
                block[row] = True
                applied.append((row, "shares_unknown_block", 1.0))
        elif e.kind == "dividend":
            d = float(e.amount)
            if prev_c > 0 and 0 < d / prev_c < 0.3:
                f = 1 - d / prev_c
                ratio[row] *= f
                applied.append((row, "dividend", f))
            else:
                cnt["dividend_implausible"] = cnt.get("dividend_implausible", 0) + 1
        elif e.kind == "rights":
            fv = None
            if face_values is not None:
                fv = face_values.get(e.symbol)
            if fv is None or not np.isfinite(fv):
                block[row] = True
                applied.append((row, "rights_unresolved", 1.0))
                continue
            issue = fv + float(e.prem)
            a, b = float(e.a), float(e.b)
            if prev_c > 0 and issue < prev_c:
                terp = (b * prev_c + a * issue) / (a + b)
                f = terp / prev_c
                ratio[row] *= f
                applied.append((row, "rights", f))
    stats["validation"] = val
    stats["applied_counts"] = pd.Series([a[1] for a in applied]).value_counts().to_dict()
    return ev, ratio, block, stats
