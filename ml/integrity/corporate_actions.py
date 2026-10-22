#!/usr/bin/env python3
"""Corporate actions from the daily PR bundles' bc files (P1, ml/IMPROVEMENT_PLAN.md).

Ratio rules (multiplicative factor applied to every bar BEFORE the ex-date, the
convention of nse_historical_ingest.apply_corporate_actions):
  "FVSPLT FRM RS A TO RS B" (any spelling: FV SPLT, FVSPLTFRM, RS10TO RS2, ...) -> B/A
  "BONUS a:b" (a bonus shares for every b held)                                  -> b/(a+b)
       orientation checked against the observed price; the flipped reading
       a/(a+b) is taken only when it agrees and the standard one does not (counted)
  face-value consolidation "FRM RE A TO RS B" with B > A                          -> B/A (> 1)
  several split/bonus/consolidation components on one (ticker, ex_date) compound.
Everything else is recorded with its kind and purpose text and ratio NaN:
  rights, dividend (incl. interim / special / final), buyback, meeting (AGM/EGM),
  book closure, merger/amalgamation, demerger, scheme of arrangement, capital
  reduction, interest/redemption, distribution, call money, other.
  Demerger, scheme of arrangement, capital reduction and rights are unadjustable
  price breaks and go to price_break_flags.csv (with splits/bonuses that failed
  validation, kind suffixed "_unvalidated").

Validation per (ticker, ex_date) with a split/bonus/consolidation component:
  observed_ratio = open(first stored session >= ex_date) / close(last stored session < ex_date)
  (EQ/BE rows of the store after the P1 session fixes; same orientation as the ratio,
  i.e. the inverse of close(ex-1)/open(ex)); agree if |observed/ratio - 1| <= 0.15.
  I2 pass mark: >= 95% of events agree.  When the same (ticker, ratio) is listed
  with several ex-dates within 120 days (an ex-date revised by the exchange) the
  ex-date whose observed jump agrees is kept and the others are marked superseded.

Completeness: (ticker, date) with a non-empty CORP_IND in the pd files and
|close/prev stored close - 1| > 22% that carry no parsed ratio are listed.

Outputs: ml/data_ext/corporate_actions_feed.csv (ticker, ex_date, ratio, kind, source,
validated; one row per validated (ticker, ex_date)), ml/data_ext/corporate_actions_all.csv,
ml/data_ext/price_break_flags.csv, ml/results/improve/integrity/corporate_actions.json.

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/corporate_actions.py
"""
from __future__ import annotations

import io
import re
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.integrity.common import DATA_EXT, OUT, RAW, bundle_inner_date, bundle_ok, log, wjson  # noqa: E402

AGREE_TOL = 0.15
REVISION_WINDOW_DAYS = 120
SHIFT_SESSIONS = 3
JUMP = 0.22
KNOWN = [("NESTLEIND", "2024-01-05", 0.1), ("IRCTC", "2021-10-28", 0.2),
         ("TATASTEEL", "2022-07-28", 0.1), ("RELIANCE", "2024-10-28", 0.5)]
UNADJUSTABLE = {"demerger", "scheme_of_arrangement", "capital_reduction", "rights"}
ADJUSTABLE = {"split", "bonus", "consolidation"}

NUM = r"(\d+(?:\.\d+)?)"
CUR = r"(?:RS|RE|INR)?\.?\s*"
RE_SPLIT = re.compile(r"(?:FV\s*SPLI?T|FVSPLI?T|SPLIT|SUB[\s-]*DIVISION)\s*(?:FRM|FROM|OF)?\s*(?:FV\s*)?"
                      + CUR + NUM + r"\s*(?:/-)?\s*(?:PER\s*SH(?:ARE)?)?\s*TO\s*" + CUR + NUM)
RE_CONSOL = re.compile(r"(?:CONSOL\w*|CONSL\w*|FV\s*CONSOL\w*)\s*(?:OF\s*SHARES?\s*)?(?:FRM|FROM)?\s*"
                       + CUR + NUM + r"\s*(?:/-)?\s*TO\s*" + CUR + NUM)
RE_BONUS = re.compile(r"BONUS\s*[-:]?\s*(?:ISSUE\s*)?(\d+)\s*[:/]\s*(\d+)")
# ETF / fund units: "ADD ISSUANCE 9:1" = 9 additional units per 1 held (economically a bonus)
RE_ADDISSUE = re.compile(r"ADD(?:ITIONAL|L|\.)?\s*ISSU\w*\s*(?:OF\s*UNITS\s*)?(\d+)\s*[:/]\s*(\d+)")


def _norm(p: str) -> str:
    return re.sub(r"\s+", " ", str(p).upper()).strip()


def classify(purpose: str) -> list[dict]:
    """Components of one purpose text: [{'kind', 'ratio', 'a', 'b'}]."""
    p = _norm(purpose)
    comps: list[dict] = []
    for m in RE_SPLIT.finditer(p):
        a, b = float(m.group(1)), float(m.group(2))
        if a > 0 and b > 0 and b < a:
            comps.append({"kind": "split", "ratio": b / a, "a": a, "b": b})
        elif a > 0 and b > a:
            comps.append({"kind": "consolidation", "ratio": b / a, "a": a, "b": b})
    for m in RE_CONSOL.finditer(p):
        a, b = float(m.group(1)), float(m.group(2))
        if a > 0 and b > a:
            comps.append({"kind": "consolidation", "ratio": b / a, "a": a, "b": b})
    for rx in (RE_BONUS, RE_ADDISSUE):
        for m in rx.finditer(p):
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                comps.append({"kind": "bonus", "ratio": b / (a + b), "a": a, "b": b})
    if comps:
        return comps
    rules = [
        ("demerger", r"DE-?\s*MERGER"),
        ("scheme_of_arrangement", r"SCHEME OF ARR|ARRANGEMENT|SCH OF ARR"),
        ("capital_reduction", r"CAPITAL REDUCTION|REDUCTION OF (SHARE )?CAPITAL|CAP\.? ?RED"),
        ("rights", r"\bRI?GHTS?|\bRIGHT ISSUE"),
        ("merger", r"\bMERGER\b|AMALGAMATION|AMALG"),
        ("buyback", r"BUY\s*-?\s*BACK"),
        ("interest_redemption", r"INTEREST|\bINT\s*PAYMENT|\bINTPAYMENT|\bINT\s*[&/]|REDEMPTI?O?N|REDMPTN|REDEMPTN|\bMATURITY"),
        ("distribution", r"DISTRI|INCOME DIST"),
        ("call_money", r"\bCALL\b|CALL\s*-|CALL MONEY|FNL ?CALL|FNLCALL"),
        ("dividend", r"DIV|DIVIDEND|\bINT\s*-\s*RS|\bSPL\s*-\s*RS|\bFIN\s*-\s*RS"),
        ("meeting", r"\bAGM\b|\bEGM\b|\bEOGM\b|GENERAL ME|GEN\.? MEET|POSTAL BALLOT|\bMEETING"),
        ("book_closure", r"BOOK CLOSURE|\bBC\b"),
    ]
    for kind, rx in rules:
        if re.search(rx, p):
            return [{"kind": kind, "ratio": np.nan, "a": np.nan, "b": np.nan}]
    return [{"kind": "other", "ratio": np.nan, "a": np.nan, "b": np.nan}]


# text columns that may contain a comma, and columns that must look like dates / numbers
_SHAPE = {"bc": {"text": ["SECURITY", "PURPOSE"], "date": ["RECORD_DT", "BC_STRT_DT", "BC_END_DT", "EX_DT",
                                                          "ND_STRT_DT", "ND_END_DT"], "num": []},
          "etf": {"text": ["SECURITY", "UNDERLYING"], "date": [],
                  "num": ["PREVIOUS CLOSE PRICE", "OPEN PRICE", "HIGH PRICE", "LOW PRICE", "CLOSE PRICE"]},
          "pd": {"text": ["SECURITY"], "date": [], "num": ["PREV_CL_PR", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                                                          "CLOSE_PRICE"]}}
_DATE_RX = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})?\s*$")
_NUM_RX = re.compile(r"^\s*-?\d*\.?\d*\s*$")


def _robust_read(raw: bytes, prefix: str) -> tuple[pd.DataFrame, int, int]:
    """csv rows with more fields than the header: re-join the extra fields into the text
    column whose choice leaves every date / number column well-formed."""
    import csv
    text = raw.decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    header = [c.strip().upper() for c in rows[0]]
    shape = _SHAPE[prefix]
    out, fixed, dropped = [], 0, 0
    for r in rows[1:]:
        if not r:
            continue
        if len(r) == len(header):
            out.append(r)
            continue
        if len(r) < len(header):
            dropped += 1
            continue
        k = len(r) - len(header)
        ok = None
        for tcol in shape["text"]:
            t = header.index(tcol)
            cand = r[:t] + [",".join(r[t:t + k + 1])] + r[t + k + 1:]
            d = dict(zip(header, cand))
            if all(_DATE_RX.match(d.get(c, "")) for c in shape["date"]) and \
                    all(_NUM_RX.match(d.get(c, "")) for c in shape["num"]):
                ok = cand
                break
        if ok is None:
            dropped += 1
        else:
            out.append(ok)
            fixed += 1
    return pd.DataFrame(out, columns=header), fixed, dropped


def _member(zf: zipfile.ZipFile, prefix: str) -> str | None:
    for n in zf.namelist():
        b = Path(n).name.lower()
        if b.startswith(prefix) and b.endswith(".csv"):
            return n
    return None


def read_members(prefix: str, columns_upper: bool = True) -> tuple[pd.DataFrame, dict]:
    """Concatenate one member type (bc / etf / pd) over every PR bundle on disk."""
    frames, stats = [], {"bundles": 0, "with_member": 0, "empty": 0, "unreadable": 0, "misfiled_skipped": []}
    for z in sorted(RAW.glob("PR*.zip")):
        stats["bundles"] += 1
        if not bundle_ok(z):
            stats["misfiled_skipped"].append(f"{z.name} holds {bundle_inner_date(z)}")
            continue
        try:
            fdate = pd.Timestamp(pd.to_datetime(z.stem[2:], format="%d%m%y"))
            with zipfile.ZipFile(z) as zf:
                name = _member(zf, prefix)
                if name is None:
                    continue
                raw = zf.read(name)
        except (zipfile.BadZipFile, ValueError):
            stats["unreadable"] += 1
            continue
        stats["with_member"] += 1
        try:
            df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding="latin-1")
        except pd.errors.EmptyDataError:
            stats["empty"] += 1
            continue
        except pd.errors.ParserError:
            df, fx, dr = _robust_read(raw, prefix)
            stats.setdefault("rows_rejoined", 0)
            stats.setdefault("rows_dropped", 0)
            stats.setdefault("files_with_overlong_rows", []).append(f"{z.name}/{name}")
            stats["rows_rejoined"] += fx
            stats["rows_dropped"] += dr
        if columns_upper:
            df.columns = [c.strip().upper() for c in df.columns]
        df = df.apply(lambda s: s.str.strip())
        df["file_date"] = fdate
        df["source_file"] = f"{z.name}/{name}"
        frames.append(df)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out, stats


def _dt(s: pd.Series) -> pd.Series:
    """bc dates: dd/mm/yyyy until mid-2025, ISO yyyy-mm-dd after (both seen in the archive)."""
    x = s.astype(str).str.strip().replace({"": np.nan, "nan": np.nan})
    out = pd.to_datetime(x, format="%d/%m/%Y", errors="coerce")
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        miss = out.isna() & x.notna()
        if not miss.any():
            break
        out = out.where(~miss, pd.to_datetime(x.where(miss), format=fmt, errors="coerce"))
    return out.astype("datetime64[ns]")


def load_bc() -> tuple[pd.DataFrame, dict]:
    bc, stats = read_members("bc")
    bc["purpose"] = bc["PURPOSE"].map(_norm)
    bc["ex_date"] = _dt(bc["EX_DT"])
    bc["record_date"] = _dt(bc["RECORD_DT"])
    bc["bc_start"] = _dt(bc["BC_STRT_DT"])
    stats["rows"] = int(len(bc))
    stats["rows_without_ex_date"] = int(bc["ex_date"].isna().sum())
    # one record per (symbol, ex_date or record/bc date, purpose)
    bc["key_date"] = bc["ex_date"].fillna(bc["record_date"]).fillna(bc["bc_start"])
    g = bc.groupby(["SYMBOL", "key_date", "purpose"], dropna=False)
    ev = g.agg(series=("SERIES", "first"), security=("SECURITY", "first"),
               ex_date=("ex_date", "first"), record_date=("record_date", "first"),
               first_seen=("file_date", "min"), last_seen=("file_date", "max"),
               n_files=("file_date", "nunique"), source_file=("source_file", "first")).reset_index()
    ev = ev.rename(columns={"SYMBOL": "ticker"})
    stats["records"] = int(len(ev))
    return ev, stats


def observed_ratios(eod: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """open(first row >= ex) / close(last row < ex) per (ticker, ex_date)."""
    e = eod[["ticker", "date", "open", "close"]].copy()
    e["date"] = pd.to_datetime(e["date"]).astype("datetime64[ns]")
    e = e.sort_values(["ticker", "date"])
    k = keys[["ticker", "ex_date"]].drop_duplicates().dropna().copy()
    k["ex_date"] = pd.to_datetime(k["ex_date"]).astype("datetime64[ns]")
    k = k.sort_values("ex_date")
    after = pd.merge_asof(k, e.rename(columns={"date": "ex_row_date"}).sort_values("ex_row_date"),
                          left_on="ex_date", right_on="ex_row_date", by="ticker", direction="forward")
    eb = e.rename(columns={"date": "prev_row_date", "open": "prev_open", "close": "prev_close_px"})
    eb = eb.sort_values("prev_row_date")
    eb["prev_key"] = eb["prev_row_date"] + pd.Timedelta(days=1)   # strictly before ex_date
    before = pd.merge_asof(k, eb[["ticker", "prev_key", "prev_row_date", "prev_close_px"]],
                           left_on="ex_date", right_on="prev_key", by="ticker", direction="backward")
    out = k.merge(after[["ticker", "ex_date", "ex_row_date", "open"]], on=["ticker", "ex_date"], how="left")
    out = out.merge(before[["ticker", "ex_date", "prev_row_date", "prev_close_px"]], on=["ticker", "ex_date"],
                    how="left")
    out["observed_ratio"] = out["open"] / out["prev_close_px"]
    out["observed_close_prev_over_open_ex"] = out["prev_close_px"] / out["open"]
    out["ex_row_lag_days"] = (out["ex_row_date"] - out["ex_date"]).dt.days
    out["prev_row_gap_days"] = (out["ex_date"] - out["prev_row_date"]).dt.days
    return out.rename(columns={"open": "open_ex", "prev_close_px": "close_prev"})


def _strong(ratio: float) -> bool:
    """A ratio the +-15% band can tell from an ordinary session (<= 0.8 or >= 1.25)."""
    return bool(np.isfinite(ratio) and ratio > 0 and abs(np.log(ratio)) >= np.log(1.25))


def agree(obs, ratio) -> bool:
    return bool(np.isfinite(obs) and np.isfinite(ratio) and ratio > 0 and abs(obs / ratio - 1) <= AGREE_TOL)


def build(eod: pd.DataFrame) -> dict:
    t0 = time.time()
    ev, stats = load_bc()
    log(f"bc: {stats}", "ca")
    rows = []
    for r in ev.itertuples(index=False):
        for c in classify(r.purpose):
            rows.append({"ticker": r.ticker, "ex_date": r.ex_date, "record_date": r.record_date,
                         "key_date": r.key_date, "kind": c["kind"], "component_ratio": c["ratio"],
                         "a": c["a"], "b": c["b"], "purpose": r.purpose, "series": r.series,
                         "security": r.security, "first_seen": r.first_seen, "last_seen": r.last_seen,
                         "n_files": r.n_files, "source_file": r.source_file})
    allc = pd.DataFrame(rows)
    adj = allc[allc["kind"].isin(ADJUSTABLE) & allc["ex_date"].notna()].copy()
    # the same component listed twice for one (ticker, ex_date) under different spellings counts once
    adj["comp_key"] = adj["kind"] + ":" + adj["a"].astype(str) + ":" + adj["b"].astype(str)
    adj = adj.sort_values("last_seen").drop_duplicates(["ticker", "ex_date", "comp_key"], keep="last")
    obs = observed_ratios(eod, adj)
    # ---- per (ticker, ex_date): compound ratio, bonus orientation, validation ----
    groups = []
    for (tkr, exd), g in adj.groupby(["ticker", "ex_date"]):
        o = obs[(obs["ticker"] == tkr) & (obs["ex_date"] == exd)].iloc[0]
        std = float(np.prod(g["component_ratio"]))
        alt_parts = [(r["a"] / (r["a"] + r["b"]) if r["kind"] == "bonus" else r["component_ratio"])
                     for _, r in g.iterrows()]
        alt = float(np.prod(alt_parts))
        ok_std, ok_alt = agree(o["observed_ratio"], std), agree(o["observed_ratio"], alt)
        has_bonus = bool((g["kind"] == "bonus").any()) and abs(alt - std) > 1e-12
        flipped = bool(has_bonus and not ok_std and ok_alt)
        ratio = alt if flipped else std
        groups.append({"ticker": tkr, "ex_date": exd, "kinds": "+".join(sorted(set(g["kind"]))),
                       "n_components": int(len(g)), "ratio": ratio, "ratio_standard": std,
                       "ratio_flipped_reading": alt if has_bonus else np.nan, "bonus_flipped": flipped,
                       "observed_ratio": float(o["observed_ratio"]) if np.isfinite(o["observed_ratio"]) else np.nan,
                       "observed_close_prev_over_open_ex": o["observed_close_prev_over_open_ex"],
                       "close_prev": o["close_prev"], "open_ex": o["open_ex"],
                       "prev_row_date": o["prev_row_date"], "ex_row_date": o["ex_row_date"],
                       "ex_row_lag_days": o["ex_row_lag_days"], "prev_row_gap_days": o["prev_row_gap_days"],
                       "validated": bool(ok_std or flipped),
                       "purpose": " | ".join(sorted(set(g["purpose"]))),
                       "source_file": g.sort_values("last_seen")["source_file"].iloc[-1],
                       "first_seen": g["first_seen"].min(), "last_seen": g["last_seen"].max()})
    ev2 = pd.DataFrame(groups)
    # ---- revised ex-dates: same ticker + same compound ratio within the window ----
    ev2["status"] = np.where(ev2["observed_ratio"].isna(), "no_price_data", "ok")
    ev2 = ev2.sort_values(["ticker", "ex_date"]).reset_index(drop=True)
    for tkr, g in ev2.groupby("ticker"):
        if len(g) < 2:
            continue
        idx = list(g.index)
        for i in idx:
            for j in idx:
                if i >= j:
                    continue
                a, b = ev2.loc[i], ev2.loc[j]
                same = abs(a["ratio_standard"] - b["ratio_standard"]) < 1e-9
                close_in_time = abs((b["ex_date"] - a["ex_date"]).days) <= REVISION_WINDOW_DAYS
                if not (same and close_in_time):
                    continue
                if a["validated"] and b["validated"]:
                    # both agree: two genuine events when the ratio is strong; one revised event
                    # (keep the closer match) when the +-15% band cannot tell a jump from a normal day
                    if _strong(a["ratio_standard"]):
                        continue
                    da = abs(np.log(a["observed_ratio"] / a["ratio"]))
                    db = abs(np.log(b["observed_ratio"] / b["ratio"]))
                    ev2.loc[j if da <= db else i, "status"] = "superseded_revised_ex_date"
                elif a["validated"] and not b["validated"]:
                    ev2.loc[j, "status"] = "superseded_revised_ex_date"
                elif b["validated"] and not a["validated"]:
                    ev2.loc[i, "status"] = "superseded_revised_ex_date"
                elif not a["validated"] and not b["validated"]:
                    # keep the later announcement, mark the other superseded
                    if a["last_seen"] <= b["last_seen"]:
                        ev2.loc[i, "status"] = "superseded_revised_ex_date"
                    else:
                        ev2.loc[j, "status"] = "superseded_revised_ex_date"
    in_store = ev2["prev_row_date"].notna() & ev2["ex_row_date"].notna()
    ev2["in_store_window"] = in_store
    # strict I2 (pre-registered): listed ex-dates, before any shift
    strict = ev2[(ev2["status"] == "ok") & in_store]
    strict_n, strict_agree = int(len(strict)), int(strict["validated"].sum())
    # ex-date shift: a listed date that disagrees while one of the ticker's sessions within
    # +-SHIFT_SESSIONS agrees (the exchange effected the action on another session)
    ev2["effective_ex_date"] = ev2["ex_date"]
    ev2["shift_sessions"] = 0
    e_sorted = eod[["ticker", "date", "open", "close"]].sort_values(["ticker", "date"])
    by_tkr = {t: g.reset_index(drop=True) for t, g in e_sorted.groupby("ticker", sort=False)}
    for i in ev2.index[(ev2["status"] == "ok") & in_store & ~ev2["validated"]]:
        r = ev2.loc[i]
        if not _strong(r["ratio_standard"]):
            continue                      # a weak ratio cannot locate a session
        g = by_tkr.get(r["ticker"])
        if g is None:
            continue
        pos = int(np.searchsorted(g["date"].to_numpy(), np.datetime64(r["ex_row_date"])))
        best = None
        for k in range(-SHIFT_SESSIONS, SHIFT_SESSIONS + 1):
            j = pos + k
            if k == 0 or j < 1 or j >= len(g):
                continue
            obs = g.loc[j, "open"] / g.loc[j - 1, "close"]
            for cand_ratio, flip in ((r["ratio_standard"], False), (r["ratio_flipped_reading"], True)):
                if flip and not np.isfinite(cand_ratio):
                    continue
                if agree(obs, cand_ratio) and (best is None or abs(k) < abs(best[0])):
                    best = (k, j, obs, cand_ratio, flip)
            # standard reading preferred at equal distance (loop order)
        if best is None:
            continue
        k, j, obs, cand_ratio, flip = best
        eff = g.loc[j, "date"]
        clash = ev2[(ev2["ticker"] == r["ticker"]) & (ev2.index != i) & (ev2["ex_date"] == eff)
                    & (np.abs(ev2["ratio_standard"] - r["ratio_standard"]) < 1e-9)]
        if len(clash):
            ev2.loc[i, "status"] = "superseded_revised_ex_date"
            continue
        ev2.loc[i, ["effective_ex_date", "shift_sessions", "observed_ratio", "ratio", "bonus_flipped",
                    "validated", "status"]] = [eff, k, obs, cand_ratio, flip, True, "ex_date_shifted"]
        ev2.loc[i, "close_prev"] = g.loc[j - 1, "close"]
        ev2.loc[i, "open_ex"] = g.loc[j, "open"]
    live = ev2[ev2["status"].isin(["ok", "ex_date_shifted"]) & in_store]
    n_live = int(len(live))
    n_agree = int(live["validated"].sum())
    i2_rate = strict_agree / strict_n if strict_n else float("nan")
    # ---- feed, flags, all ----
    feed = live[live["validated"]][["ticker", "effective_ex_date", "ratio", "kinds", "source_file"]].rename(
        columns={"kinds": "kind", "source_file": "source", "effective_ex_date": "ex_date"})
    feed["validated"] = True
    feed = feed.sort_values(["ticker", "ex_date"])
    DATA_EXT.mkdir(parents=True, exist_ok=True)
    feed_out = feed.assign(ex_date=feed["ex_date"].dt.strftime("%Y-%m-%d"))
    feed_out.to_csv(DATA_EXT / "corporate_actions_feed.csv", index=False)
    other = allc[~allc["kind"].isin(ADJUSTABLE)].copy()
    other_obs = observed_ratios(eod, other.dropna(subset=["ex_date"]))
    other = other.merge(other_obs[["ticker", "ex_date", "observed_ratio"]], on=["ticker", "ex_date"], how="left")
    all_out = pd.concat([
        ev2.assign(kind=ev2["kinds"])[["ticker", "ex_date", "kind", "ratio", "purpose", "observed_ratio",
                                       "validated", "source_file", "status", "effective_ex_date",
                                       "shift_sessions", "bonus_flipped", "ratio_standard",
                                       "close_prev", "open_ex", "prev_row_date", "ex_row_date",
                                       "first_seen", "last_seen"]],
        other.assign(ratio=np.nan, validated=False, status="recorded")[
            ["ticker", "ex_date", "kind", "ratio", "purpose", "observed_ratio", "validated", "source_file",
             "status", "record_date", "first_seen", "last_seen"]],
    ], ignore_index=True).sort_values(["ex_date", "ticker"], na_position="last")
    for c in ("ex_date", "effective_ex_date", "prev_row_date", "ex_row_date", "first_seen", "last_seen",
              "record_date"):
        if c in all_out.columns:
            all_out[c] = pd.to_datetime(all_out[c]).dt.strftime("%Y-%m-%d")
    all_out.to_csv(DATA_EXT / "corporate_actions_all.csv", index=False)
    brk = other[other["kind"].isin(UNADJUSTABLE) & other["ex_date"].notna()][["ticker", "ex_date", "kind", "purpose"]]
    unv = ev2[ev2["status"].isin(["ok", "ex_date_shifted"]) & in_store & ~ev2["validated"]][
        ["ticker", "ex_date", "kinds", "purpose"]]
    unv = unv.rename(columns={"kinds": "kind"}).assign(kind=lambda x: x["kind"] + "_unvalidated")
    flags = pd.concat([brk, unv], ignore_index=True).drop_duplicates(["ticker", "ex_date", "kind"])
    flags = flags.sort_values(["ex_date", "ticker"])
    flags.assign(ex_date=flags["ex_date"].dt.strftime("%Y-%m-%d"))[["ticker", "ex_date", "kind", "purpose"]].to_csv(
        DATA_EXT / "price_break_flags.csv", index=False)
    # ---- known events ----
    known = []
    for tkr, d, r in KNOWN:
        m = feed[(feed["ticker"] == tkr) & (feed["ex_date"] == pd.Timestamp(d))]
        e = ev2[(ev2["ticker"] == tkr) & (ev2["ex_date"] == pd.Timestamp(d))]
        known.append({"ticker": tkr, "ex_date": d, "expected_ratio": r,
                      "found_in_feed": bool(len(m)), "ratio": float(m["ratio"].iloc[0]) if len(m) else None,
                      "observed_ratio": float(e["observed_ratio"].iloc[0]) if len(e) else None,
                      "purpose": e["purpose"].iloc[0] if len(e) else None,
                      "ratio_matches": bool(len(m) and abs(float(m["ratio"].iloc[0]) - r) < 1e-9)})
    # ---- completeness: CORP_IND + |ret| > 22% without a parsed ratio ----
    comp = completeness(eod, feed, ev2, allc)
    disagree = strict[~strict["validated"]].sort_values("ex_date")
    still = set(zip(live.loc[~live["validated"], "ticker"], live.loc[~live["validated"], "ex_date"]))
    res = {
        "bc_stats": stats,
        "records_by_kind": {k: int(v) for k, v in allc.drop_duplicates(
            ["ticker", "key_date", "purpose", "kind"])["kind"].value_counts().items()},
        "adjustable_events": {"ticker_exdate_groups": int(len(ev2)),
                              "superseded_revised_ex_date": int((ev2["status"] == "superseded_revised_ex_date").sum()),
                              "no_price_data_or_outside_store": int(((ev2["status"] == "no_price_data") | ~in_store).sum()),
                              "evaluated": n_live, "agree": n_agree, "disagree": n_live - n_agree,
                              "by_kind_evaluated": {k: int(v) for k, v in live["kinds"].value_counts().items()},
                              "bonus_orientation_flips": int(live["bonus_flipped"].sum()),
                              "bonus_events_evaluated": int(live["kinds"].str.contains("bonus").sum())},
        "I2_by_ratio_strength": {
            lab: {"events": int(len(x)), "agree": int(x["validated"].sum()),
                  "rate": float(x["validated"].mean()) if len(x) else None}
            for lab, x in (("strong_ratio_le_0.8_or_ge_1.25", strict[strict["ratio_standard"].map(_strong)]),
                           ("weak_ratio", strict[~strict["ratio_standard"].map(_strong)]))},
        "I2": {"rate": i2_rate, "events": strict_n, "agree": strict_agree, "pass_mark": 0.95,
               "pass": bool(i2_rate >= 0.95),
               "rule": "|observed/ratio - 1| <= 0.15, observed = open(ex)/close(ex-1) in the ratio's "
                       "orientation, at the LISTED ex-date (no shift); revised duplicates excluded"},
        "after_ex_date_shift": {"events": n_live, "agree": n_agree,
                                "rate": n_agree / n_live if n_live else None,
                                "shifted": int((ev2["status"] == "ex_date_shifted").sum()),
                                "shift_sessions": {str(k): int(v) for k, v in
                                                   ev2.loc[ev2["status"] == "ex_date_shifted", "shift_sessions"]
                                                   .value_counts().items()}},
        "disagreements": disagree[["ticker", "ex_date", "kinds", "purpose", "ratio_standard", "observed_ratio",
                                   "observed_close_prev_over_open_ex", "close_prev", "open_ex",
                                   "prev_row_date", "ex_row_date"]].assign(
            resolved_by_shift=[(t, d) not in still for t, d in zip(disagree["ticker"], disagree["ex_date"])],
            same_day_unadjustable=[_same_day(allc, t, d) for t, d in zip(disagree["ticker"], disagree["ex_date"])]).assign(
            ex_date=lambda x: x["ex_date"].dt.strftime("%Y-%m-%d"),
            prev_row_date=lambda x: pd.to_datetime(x["prev_row_date"]).dt.strftime("%Y-%m-%d"),
            ex_row_date=lambda x: pd.to_datetime(x["ex_row_date"]).dt.strftime("%Y-%m-%d")).to_dict("records"),
        "superseded": ev2[ev2["status"] == "superseded_revised_ex_date"][["ticker", "ex_date", "purpose",
                                                                          "observed_ratio"]].assign(
            ex_date=lambda x: x["ex_date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
        "shifted": ev2[ev2["status"] == "ex_date_shifted"][["ticker", "ex_date", "effective_ex_date",
                                                           "shift_sessions", "purpose", "ratio",
                                                           "observed_ratio"]].assign(
            ex_date=lambda x: x["ex_date"].dt.strftime("%Y-%m-%d"),
            effective_ex_date=lambda x: pd.to_datetime(x["effective_ex_date"]).dt.strftime("%Y-%m-%d"))
        .to_dict("records"),
        "known_events": known,
        "known_events_all_found": all(k["ratio_matches"] for k in known),
        "feed_rows": int(len(feed)),
        "feed_by_kind": {k: int(v) for k, v in feed["kind"].value_counts().items()},
        "price_break_flags": {k: int(v) for k, v in flags["kind"].value_counts().items()},
        "completeness": comp,
        "seconds": round(time.time() - t0, 1),
    }
    wjson(OUT / "corporate_actions.json", res)
    log(f"ca: evaluated {n_live}, agree {n_agree} ({i2_rate:.4f}), feed {len(feed)}, flags {len(flags)}, "
        f"known {[k['ratio_matches'] for k in known]}, completeness gaps {comp['n_missing']}", "ca")
    return res


def _same_day(allc: pd.DataFrame, tkr: str, d) -> str:
    x = allc[(allc["ticker"] == tkr) & (allc["ex_date"] == d) & ~allc["kind"].isin(ADJUSTABLE)]
    return ",".join(sorted(set(x["kind"])))


def completeness(eod: pd.DataFrame, feed: pd.DataFrame, ev2: pd.DataFrame,
                 allc: pd.DataFrame | None = None) -> dict:
    pdf, st = read_members("pd")
    pdf = pdf[pdf["SERIES"].isin(["EQ", "BE"]) & (pdf["CORP_IND"] != "")]
    pdf = pdf.rename(columns={"SYMBOL": "ticker"})[["ticker", "file_date", "CORP_IND", "SERIES"]]
    e = eod[["ticker", "date", "close"]].sort_values(["ticker", "date"]).copy()
    e["ret_1d"] = e["close"] / e.groupby("ticker")["close"].shift(1) - 1
    j = pdf.merge(e, left_on=["ticker", "file_date"], right_on=["ticker", "date"], how="left")
    big = j[j["ret_1d"].abs() > JUMP].copy()
    fk = set(zip(feed["ticker"], feed["ex_date"]))
    anyk = set(zip(ev2["ticker"], ev2["ex_date"]))
    big["in_feed"] = [(t, d) in fk for t, d in zip(big["ticker"], big["date"])]
    big["parsed_but_unvalidated"] = [((t, d) in anyk) and ((t, d) not in fk) for t, d in zip(big["ticker"], big["date"])]
    miss = big[~big["in_feed"]].sort_values("date").copy()
    if allc is not None:
        kinds = allc.dropna(subset=["ex_date"]).groupby(["ticker", "ex_date"])["kind"].agg(
            lambda x: ",".join(sorted(set(x))))
        miss["bc_kinds_on_date"] = [kinds.get((t, d), "") for t, d in zip(miss["ticker"], miss["date"])]
    else:
        miss["bc_kinds_on_date"] = ""
    return {"pd_stats": st, "corp_ind_codes": {k: int(v) for k, v in pdf["CORP_IND"].value_counts().items()},
            "corp_ind_rows_eq_be": int(len(pdf)),
            "corp_ind_with_abs_ret_gt_22pct": int(len(big)),
            "covered_by_feed": int(big["in_feed"].sum()),
            "n_missing": int(len(miss)),
            "n_missing_without_any_bc_record": int((miss["bc_kinds_on_date"] == "").sum()),
            "missing_by_bc_kind": {k if k else "(no bc record)": int(v)
                                   for k, v in miss["bc_kinds_on_date"].value_counts().items()},
            "missing": miss.assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))[
                ["ticker", "date", "CORP_IND", "ret_1d", "parsed_but_unvalidated", "bc_kinds_on_date"]]
            .to_dict("records")}


def main(argv=None) -> int:
    from ml.integrity.sessions import apply_fixes_to_export, load_eod
    import json
    eod = load_eod()
    from ml.integrity.sessions import STAGING
    up = STAGING / "sessions_upsert.parquet"
    if up.exists():
        dele = json.loads((STAGING / "sessions_delete.json").read_text())["delete_dates"]
        eod = apply_fixes_to_export(eod, pd.read_parquet(up), dele)
        log(f"ca: using the store preview with P1 session fixes ({len(eod):,} EQ/BE rows)", "ca")
    build(eod)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
