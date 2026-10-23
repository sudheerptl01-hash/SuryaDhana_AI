#!/usr/bin/env python3
"""Fixed classification rules for the announcement records (EVENTS.md section 3 is generated from RULES below).

The rules were fixed from text inspection of the records (categories by year, sampled texts, a few liquid
names' results weeks) before any return statistic was computed.  Classes are flags on each announcement
record (source == "an"); the board-meeting list rows (source == "bm") are only used by rule R3.

  routine      boilerplate: NAV declarations, trading window, newspaper publications, lost/duplicate share
               certificates, depository certificates, and the other compliance filings listed in ROUTINE_*
  results      the release of financial results: R1 a results category; R2 a results-bearing category whose
               text says results were approved / submitted / released; R3 an outcome of a board meeting whose
               intimated purpose (board-meeting list or a "Board Meeting Intimation" record) was financial
               results.  Never an intimation that results will be considered, a newspaper copy, a call
               transcript, a clarification or a re-submission.
  rating       credit ratings
  mgmt_change  resignation, cessation, change in management / directors / auditors / KMP, appointment of
               directors and KMP-level officers, retirement, demise
  orders       bagging / receiving / award of orders or contracts
  insolvency   corporate insolvency resolution process, NCLT admission, BIFR
A routine record carries no other class.  Classes other than routine may overlap.
"""
from __future__ import annotations

import re
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")

I = re.IGNORECASE

# ---------------------------------------------------------------------------- routine
ROUTINE_CATEGORY = [
    r"^Declaration of NAV",
    r"^Trading Window",
    r"^Copy of Newspaper Publication",
    r"^Loss of Share Certificates?$",
    r"^Loss/Duplicate-Share Certificate$",
    r"^Issue of Duplicate Share Certificate$",
    r"^Certificate under SEBI \(Depositories and Participants\) Regulations",
    # similar boilerplate (documented in EVENTS.md)
    r"^Code of Conduct under SEBI ?\(PIT\)",
    r"^Structural Digital Database$",
    r"^Annual Secretarial Compliance Report",
    r"^Quarterly Compliance Report on Corporate governance",
    r"^Registrar & Share Transfer Agent Update$",
    r"^E-mail ID for Investor's Grievance Redressal$",
    r"^Interest Rates Updates$",
    r"^Disclosure of Unitholding pattern",
    r"^Disclosure of all complaints including SCORES",
    r"^Statement of deviation\(s\) or variation\(s\) under Reg\. ?32",
    r"^Monitoring Agency Report$",
    r"^Daily Buy-Back of equity shares$",
]
GENERIC_CATEGORY = r"^(Updates|General Updates|Others|)$"
ROUTINE_TEXT_IN_GENERIC = [  # only applied to the generic categories above
    r"news\s*paper|advertisement|publication of|published in",
    r"loss of (the )?share certificates?|duplicate share certificates?|issue of duplicate",
    r"regulation\s*74\s*\(\s*5\s*\)|depositories and participants",
    r"trading window",
    r"regulation\s*(7\s*\(\s*3\s*\)|40\s*\(\s*(9|10)\s*\)|13\s*\(\s*3\s*\))",
    r"reconciliation of share capital|investor complaints|investor grievance",
    r"(change|changes) in (the )?name of (the )?(registrar|rta|share transfer agent)|link intime|mufg intime",
    r"structural digital database|secretarial compliance report|compliance certificate",
]

# ---------------------------------------------------------------------------- results
RESULTS_CATEGORY = [  # R1: the category is the results release
    r"^Financial Results? Updates$", r"^Results$", r"^Results/Others$", r"^Publish Audited Results$",
    r"^Consolidated Result Updates - IFRS$", r"^Limited Review Report$", r"^Integrated Filing- ?Financial$",
]
RESULTS_BEARING_CATEGORY = [  # R2: category may carry the results release; the text must say so
    r"^Outcome of Board Meeting", r"^Updates$", r"^General Updates$", r"^Press Release", r"^Investor Presentation$",
    r"^Dividend$", r"^Others$", r"^$",
]
RESULTS_TEXT = (r"financial\s*results?|financial\s+statements?\s*/\s*results?|"
                r"\bresults?\s+(of the company\s+)?for\s+the\s+(quarter|half|year|period|nine|first|second|third|fourth|q[1-4])|"
                r"\b(q[1-4]|quarterly|annual|half[- ]yearly)\s+(fy\s*\d+\s+)?results?\b|\bearnings release\b")
RESULTS_EXCLUDE_TEXT = (
    r"to\s+(inter[\s-]*alia\s*,?\s*)?consider|will\s+be\s+(held|considered)|to\s+be\s+held|is\s+scheduled|scheduled\s+(on|to|for)|"
    r"(to|will)\s+announce|announce\w*\s+(the\s+)?(date|schedule)|"
    r"intimation\s+of\s+(the\s+)?(date|board|meeting)|intimation\s+(to|under|regarding|about|pursuant)|prior\s+intimation|"
    r"board\s+meeting\s+intimation|notice\s+of\s+(the\s+)?(board\s+)?meeting|prior\s+notice|"
    r"news\s*paper|advertis|publication|published|publishing|"
    r"con(ference)?\.?\s*call|earnings\s+call|transcript|recording|audio|video|webcast|investor\s+meet|analyst|"
    r"non[-\s]*submission|delay|reasons\s+for|clarification|relaxation|applicability|option\s+to\s+submit|"
    r"rectif|discrepanc|corrigendum|machine[\s-]*readable|searchable|re-?submi|\brevis(ed|ion)\b|trading\s+window")
OUTCOME_CATEGORY = r"^Outcome of Board Meeting"
OUTCOME_TEXT_IN_GENERIC = r"outcome\s+of\s+(the\s+)?board\s+meeting|board\s+meeting\s+outcome"
INTIMATION_CATEGORY = r"^Board Meeting Intimation"
R3_DAYS_HELD_ON = 3        # |intimated meeting date - "held on" date| <= 3 calendar days
R3_DAYS_NO_DATE = 7        # intimated meeting date within the 7 calendar days up to the outcome's file date
DEDUP_SESSIONS = 5         # a results session within 5 sessions after another is the same release

# ---------------------------------------------------------------------------- other classes
RATING_CATEGORY = [r"^Credit Rating"]
RATING_TEXT_IN_GENERIC = (r"credit\s+rating|rating\s+agenc|\b(crisil|icra|care ratings|india ratings|brickwork|acuite|"
                          r"infomerics)\b.{0,80}\brating")
RATING_EXCLUDE_TEXT = r"\besg\b|large\s+corporate|non[- ]applicability"
MGMT_CATEGORY = [
    r"^Resignation", r"^Cessation", r"^Change in Management", r"^Change in Director", r"^Change in Directors/ ?Key Managerial",
    r"^Change in Auditors?", r"^Appointment of Auditors?", r"^Change in Company Secretary", r"^Change in\s+Managing Director",
    r"^Appointment of (Director|Chairman|Managing Director|Chief|Company Secretary|Compliance Officer|Independent)",
    r"^Retirement$", r"^Demise$",
]
MGMT_APPOINTMENT_CATEGORY = r"^Appointment$"
KMP_TEXT = (r"\b(director|managing director|chief executive|ceo|chief financial|cfo|company secretary|compliance officer|"
            r"key managerial|kmp|chairman|chairperson|whole[- ]time|auditors?|chief operating|coo|president)\b")
MGMT_TEXT_IN_GENERIC = r"\b(resign(ation|ed|s)?|cessation|ceased\s+to\s+be)\b"
ORDERS_CATEGORY = [r"(Bagging|Receiving|Awarding).{0,20}(order|contract)"]
ORDERS_TEXT_IN_GENERIC = (r"\b(receiv\w*|receipt\s+of|bag(s|ged|ging)?|secur(ed|es|ing)|wins?|winning|won|award\w*)\b[^.]{0,80}"
                          r"\b(orders?|contracts?|loa|loi)\b|letter\s+of\s+(award|acceptance|intent)|\bl-?1\s+bidder|lowest\s+bidder")
ORDERS_EXCLUDE_TEXT = (r"court|tribunal|nclt|nclat|\bsebi\b|\btax\b|income[- ]tax|\bgst\b|assessment|penalt|demand\s+notice|"
                       r"show[- ]cause|arbitra|order\s+passed|regulatory|interim\s+order|stay\s+order|adjudicat|"
                       r"order[-\s]+in[-\s]+original|commissioner|directorate|enforcement|credit\s+rating")
ORDERS_GENERIC = r"^(Updates|General Updates|Others|Press Release|Press Release \(Revised\)|)$"
INSOLVENCY_CATEGORY = [r"^Corporate Insolvency Resolution Process", r"^BIFR$"]
INSOLVENCY_TEXT_IN_GENERIC = (r"corporate\s+insolvency\s+resolution|\bcirp\b|insolvency\s+and\s+bankruptcy\s+code|"
                              r"interim\s+resolution\s+professional|resolution\s+professional|"
                              r"admitted.{0,60}(section\s*(7|9|10)|insolvency)|nclt.{0,60}admit")

POSTPONE_CATEGORY_DOC = r"^Board [Mm]eeting (Cancelled|Postponed|Adjourned|Deferred|Rescheduled)"
RULES = [  # (class, rule id, where, pattern) -- rendered into EVENTS.md
    ("routine", "RT1", "category", ROUTINE_CATEGORY),
    ("routine", "RT2", "text, when the category is generic (Updates / General Updates / Others / none)", ROUTINE_TEXT_IN_GENERIC),
    ("results", "R1", "category, and text not matching the results exclusions", RESULTS_CATEGORY),
    ("results", "R2", "category in " + " | ".join(RESULTS_BEARING_CATEGORY) + "; text matches RESULTS_TEXT and not the exclusions", [RESULTS_TEXT]),
    ("results", "R2x", "results exclusions (intimation, newspaper, calls, clarification, re-submission, delay)", [RESULTS_EXCLUDE_TEXT]),
    ("results", "R3", f"category {OUTCOME_CATEGORY} (or a generic category whose text is an outcome of a board meeting), not R1/R2, "
                      f"matched to a results-purpose board meeting intimated earlier for the same symbol: meeting date within "
                      f"{R3_DAYS_HELD_ON} days of the 'held on' date in the text, or within the {R3_DAYS_NO_DATE} days up to the "
                      f"file date when the text has no date", [OUTCOME_TEXT_IN_GENERIC]),
    ("results", "R4", "a board meeting intimated for financial results (board-meeting list of the bundles, or a Board Meeting "
                      "Intimation record): the first session on or after the meeting date, if the intimation was filed on or "
                      "before that date and not superseded before it by another intimated date or a cancellation / "
                      "postponement record", [POSTPONE_CATEGORY_DOC]),
    ("results", "RD", f"release session: a results session with another within the previous {DEDUP_SESSIONS} sessions is the same release", []),
    ("rating", "CR1", "category", RATING_CATEGORY),
    ("rating", "CR2", "text, generic category, not ESG / large-corporate boilerplate", [RATING_TEXT_IN_GENERIC]),
    ("mgmt_change", "M1", "category", MGMT_CATEGORY),
    ("mgmt_change", "M2", "category Appointment and text names a director / KMP-level officer", [KMP_TEXT]),
    ("mgmt_change", "M3", "text, generic category: resignation / cessation of a director / KMP-level officer", [MGMT_TEXT_IN_GENERIC]),
    ("orders", "O1", "category", ORDERS_CATEGORY),
    ("orders", "O2", "text, generic or press-release category, not court / regulator / tax orders", [ORDERS_TEXT_IN_GENERIC]),
    ("orders", "O2x", "orders exclusions", [ORDERS_EXCLUDE_TEXT]),
    ("insolvency", "IN1", "category", INSOLVENCY_CATEGORY),
    ("insolvency", "IN2", "text, generic category", [INSOLVENCY_TEXT_IN_GENERIC]),
]

DATE_HELD_ON = re.compile(
    r"held\s+on\s+(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s*(?:the\s+)?)?"
    r"(\d{1,2}(?:st|nd|rd|th)?[-\s/]*[A-Za-z]{3,9}[-\s,/]*\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", I)


def _any(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), I)


def parse_held_on(text: str):
    m = DATE_HELD_ON.search(text[:400])
    if not m:
        return pd.NaT
    s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(1), flags=I).replace(",", " ")
    if re.match(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$", s):
        return pd.to_datetime(s.replace(".", "/").replace("-", "/"), dayfirst=True, errors="coerce")
    return pd.to_datetime(" ".join(s.replace("-", " ").replace("/", " ").split()), errors="coerce", dayfirst=True)


def classify(ev: pd.DataFrame) -> pd.DataFrame:
    """Class flags for every row of events_raw (False on board-meeting list rows, source == "bm")."""
    out = pd.DataFrame(False, index=ev.index, columns=["routine", "results", "rating", "mgmt_change", "orders",
                                                       "insolvency", "non_routine"])
    out["results_rule"] = ""
    an = (ev["source"] == "an").to_numpy()
    cat_all = ev["category_raw"].fillna("").astype(str)
    nav = cat_all.str.startswith("Declaration of NAV").to_numpy()
    out.loc[an & nav, "routine"] = True
    sub = ev[an & ~nav]
    cat = sub["category_raw"].fillna("").astype(str)
    txt = sub["text"].fillna("").astype(str)
    generic = cat.str.match(GENERIC_CATEGORY)
    routine = cat.str.contains(_any(ROUTINE_CATEGORY)) | (generic & txt.str.contains(_any(ROUTINE_TEXT_IN_GENERIC)))
    ok = ~routine
    excl = txt.str.contains(re.compile(RESULTS_EXCLUDE_TEXT, I))
    rtext = txt.str.contains(re.compile(RESULTS_TEXT, I))
    r1 = ok & cat.str.contains(_any(RESULTS_CATEGORY)) & ~excl
    r1 &= ~cat.str.match(re.compile(r"^Integrated Filing", I)) | rtext
    r2 = ok & ~r1 & cat.str.contains(_any(RESULTS_BEARING_CATEGORY)) & rtext & ~excl
    outcome = ok & ~r1 & ~r2 & (cat.str.contains(re.compile(OUTCOME_CATEGORY, I))
                                | (generic & txt.str.contains(re.compile(OUTCOME_TEXT_IN_GENERIC, I))))
    r3 = _match_r3(ev, sub.index[outcome.to_numpy()])
    r3 = pd.Series(sub.index.isin(r3), index=sub.index)
    o = pd.DataFrame(index=sub.index)
    o["routine"] = routine
    o["results_rule"] = np.select([r1, r2, r3], ["R1", "R2", "R3"], "")
    o["results"] = r1 | r2 | r3
    o["rating"] = ok & (cat.str.contains(_any(RATING_CATEGORY))
                        | (generic & txt.str.contains(re.compile(RATING_TEXT_IN_GENERIC, I))
                           & ~txt.str.contains(re.compile(RATING_EXCLUDE_TEXT, I))))
    kmp = txt.str.contains(re.compile(KMP_TEXT, I))
    o["mgmt_change"] = ok & (cat.str.contains(_any(MGMT_CATEGORY)) | (cat.str.match(MGMT_APPOINTMENT_CATEGORY) & kmp)
                             | (generic & txt.str.contains(re.compile(MGMT_TEXT_IN_GENERIC, I)) & kmp))
    og = cat.str.match(ORDERS_GENERIC)
    o["orders"] = ok & (cat.str.contains(_any(ORDERS_CATEGORY))
                        | (og & txt.str.contains(re.compile(ORDERS_TEXT_IN_GENERIC, I))
                           & ~txt.str.contains(re.compile(ORDERS_EXCLUDE_TEXT, I))))
    o["insolvency"] = ok & (cat.str.contains(_any(INSOLVENCY_CATEGORY))
                            | (generic & txt.str.contains(re.compile(INSOLVENCY_TEXT_IN_GENERIC, I))))
    o["non_routine"] = ok
    for c in o.columns:
        out.loc[o.index, c] = o[c].to_numpy()
    return out


def results_calendar(ev: pd.DataFrame) -> pd.DataFrame:
    """Board meetings intimated for financial results: board-meeting list rows whose purpose mentions results, and
    "Board Meeting Intimation" records whose text mentions financial results with a "to be held on" date."""
    bm = ev[(ev["source"] == "bm") & ev["text"].fillna("").str.contains("result", case=False)]
    cal = [bm[["symbol", "file_date", "bm_date"]].rename(columns={"bm_date": "meeting_date"})]
    an = ev[(ev["source"] == "an") & ev["category_raw"].fillna("").str.contains(INTIMATION_CATEGORY, case=False)
            & ev["text"].fillna("").str.contains(r"financial\s*result", case=False)]
    if len(an):
        d = an["text"].str.extract(r"(?i)to\s+be\s+held\s+on\s+(\d{1,2}-[A-Za-z]{3}-\d{4})")[0]
        md = pd.to_datetime(d, format="%d-%b-%Y", errors="coerce")
        cal.append(pd.DataFrame({"symbol": an["symbol"].to_numpy(), "file_date": an["file_date"].to_numpy(),
                                 "meeting_date": md.to_numpy()}))
    c = pd.concat(cal, ignore_index=True).dropna()
    return c.drop_duplicates().reset_index(drop=True)


def _match_r3(ev: pd.DataFrame, idx: pd.Index) -> pd.Index:
    """Rows of `idx` (outcome records) that match a results-purpose board meeting intimated in a file dated on or
    before the outcome's file date (point in time)."""
    if not len(idx):
        return idx[:0]
    cal = results_calendar(ev)
    by = {s: (g["file_date"].to_numpy(dtype="datetime64[ns]"), g["meeting_date"].to_numpy(dtype="datetime64[ns]"))
          for s, g in cal.groupby("symbol", sort=False)}
    sub = ev.loc[idx]
    held = sub["text"].fillna("").map(parse_held_on)
    hit = np.zeros(len(idx), bool)
    day = np.timedelta64(1, "D")
    for j, (sym, fd, ho) in enumerate(zip(sub["symbol"].to_numpy(), sub["file_date"].to_numpy(dtype="datetime64[ns]"),
                                          held.to_numpy(dtype="datetime64[ns]"))):
        g = by.get(sym)
        if g is None:
            continue
        known = g[0] <= fd
        if not known.any():
            continue
        md = g[1][known]
        if not np.isnat(ho) and abs((ho - fd) / day) <= 60:
            hit[j] = bool((np.abs((md - ho) / day) <= R3_DAYS_HELD_ON).any())
        else:
            hit[j] = bool(((md <= fd) & (md >= fd - R3_DAYS_NO_DATE * day)).any())
    return idx[hit]


# ---------------------------------------------------------------------------- results sessions
POSTPONE_CATEGORY = r"^Board [Mm]eeting (Cancelled|Postponed|Adjourned|Deferred|Rescheduled)"


def _next_session(sess: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Index of the first session on or after each date (len(sess) when after the last session)."""
    return np.searchsorted(sess, d.astype("datetime64[ns]"), side="left")


def results_events(ev: pd.DataFrame, cls: pd.DataFrame, sess: np.ndarray) -> pd.DataFrame:
    """Every results observation as (symbol, session index, rule):
      R1-R3  an announcement record classified as results, at the session of its file;
      R4     a board meeting intimated for financial results (board-meeting list, or a "Board Meeting
             Intimation" record), at the first session on or after the meeting date, when the intimation was
             filed on or before the meeting date and was not superseded before the meeting date by a later
             intimation naming another date (more than 3 days apart) or by a cancellation / postponement record.
    Every observation depends only on files dated on or before its session (point in time)."""
    a = ev[cls["results"].to_numpy()]
    out = [pd.DataFrame({"symbol": a["symbol"].to_numpy(), "s": _next_session(sess, a["file_date"].to_numpy()),
                         "rule": cls.loc[a.index, "results_rule"].to_numpy()})]
    cal = results_calendar(ev)
    cal = cal[cal["file_date"] <= cal["meeting_date"]].sort_values(["symbol", "meeting_date", "file_date"])
    cal = cal.drop_duplicates(["symbol", "meeting_date"], keep="first").reset_index(drop=True)
    pp = ev[(ev["source"] == "an") & ev["category_raw"].fillna("").str.match(POSTPONE_CATEGORY)]
    ppby = {s: g["file_date"].to_numpy(dtype="datetime64[ns]") for s, g in pp.groupby("symbol", sort=False)}
    keep = np.ones(len(cal), bool)
    day = np.timedelta64(1, "D")
    for sym, g in cal.groupby("symbol", sort=False):
        f = g["file_date"].to_numpy(dtype="datetime64[ns]")
        d = g["meeting_date"].to_numpy(dtype="datetime64[ns]")
        pf = ppby.get(sym)
        for k, i in enumerate(g.index):
            later = (f > f[k]) & (f <= d[k]) & (np.abs((d - d[k]) / day) > R3_DAYS_HELD_ON)
            if later.any() or (pf is not None and ((pf >= f[k]) & (pf <= d[k])).any()):
                keep[i] = False
    c = cal[keep]
    out.append(pd.DataFrame({"symbol": c["symbol"].to_numpy(), "s": _next_session(sess, c["meeting_date"].to_numpy()),
                             "rule": "R4"}))
    r = pd.concat(out, ignore_index=True)
    r = r[r["s"] < len(sess)]
    return r.reset_index(drop=True)


def release_sessions(rev: pd.DataFrame) -> pd.DataFrame:
    """Rule RD: per symbol, the sessions with a results observation, keeping a session only when no other results
    observation lies in the previous DEDUP_SESSIONS sessions (the re-filings of one release collapse onto its first
    session).  Returns (symbol, s, rules) with the rules observed on that session."""
    g = rev.groupby(["symbol", "s"])["rule"].agg(lambda x: "+".join(sorted(set(x)))).reset_index()
    g = g.rename(columns={"rule": "rules"})
    g = g.sort_values(["symbol", "s"]).reset_index(drop=True)
    prev = g.groupby("symbol")["s"].shift(1)
    first = prev.isna() | ((g["s"] - prev) > DEDUP_SESSIONS)
    return g[first.to_numpy()].reset_index(drop=True)


# ---------------------------------------------------------------------------- CLI
CLASSES = ["routine", "results", "rating", "mgmt_change", "orders", "insolvency", "non_routine"]


def run() -> dict:
    """Classify every record, store the flags in events_raw.parquet (inspection only; the feature build always
    re-classifies its own input) and write classify.json: rule table, class counts by year, the category frequency
    table by year and each category's mapping to classes."""
    import json
    import time
    from pathlib import Path
    ml = Path(__file__).resolve().parents[1]
    raw = ml / "data_ext" / "events_raw.parquet"
    out_dir = ml / "results" / "improve2" / "events"
    t0 = time.time()
    ev = pd.read_parquet(raw)
    ev = ev.drop(columns=[c for c in CLASSES + ["results_rule"] if c in ev.columns])
    cls = classify(ev)
    ev = pd.concat([ev, cls], axis=1)
    tmp = raw.with_suffix(".tmp.parquet")
    ev.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(raw)
    an = ev[ev["source"] == "an"].copy()
    an["year"] = an["file_date"].dt.year
    listed = an[an["in_eod"]]
    by_year = {c: {int(y): int(v) for y, v in an.groupby("year")[c].sum().items()} for c in CLASSES}
    by_year_listed = {c: {int(y): int(v) for y, v in listed.groupby("year")[c].sum().items()} for c in CLASSES}
    rules_by_year = {r: {int(y): int(v) for y, v in an[an["results_rule"] == r].groupby("year").size().items()}
                     for r in ("R1", "R2", "R3")}
    ft = pd.crosstab(listed["category_raw"].fillna(""), listed["year"])
    ft["total"] = ft.sum(axis=1)
    ft = ft.sort_values("total", ascending=False)
    top = ft.head(120)
    mapping = {}
    g = listed.groupby(listed["category_raw"].fillna(""))
    share = g[CLASSES].mean()
    for c in top.index:
        mapping[c] = {k: round(float(share.loc[c, k]), 3) for k in CLASSES if share.loc[c, k] > 0}
    res = {
        "rules": [{"class": a, "id": b, "where": w, "patterns": p} for a, b, w, p in RULES],
        "constants": {"R3_DAYS_HELD_ON": R3_DAYS_HELD_ON, "R3_DAYS_NO_DATE": R3_DAYS_NO_DATE, "DEDUP_SESSIONS": DEDUP_SESSIONS},
        "class_counts_by_year_all_symbols": by_year, "class_counts_by_year_bhavcopy_symbols": by_year_listed,
        "results_rule_counts_by_year": rules_by_year,
        "category_frequency_by_year_bhavcopy_symbols": {
            "years": [int(y) for y in ft.columns if y != "total"], "n_categories": int(len(ft)),
            "top": [{"category": c, "total": int(r["total"]), "by_year": {int(y): int(r[y]) for y in ft.columns if y != "total"}}
                    for c, r in top.iterrows()]},
        "category_to_class_share_top": mapping,
        "seconds": round(time.time() - t0, 1),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classify.json").write_text(json.dumps(res, indent=1))
    print(f"[events.classify] {len(ev):,} rows classified in {res['seconds']}s; classify.json written", flush=True)
    return res


if __name__ == "__main__":
    run()
