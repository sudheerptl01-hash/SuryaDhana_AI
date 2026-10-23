#!/usr/bin/env python3
"""Parse the exchange's daily announcement lists (An<date>.txt in every PR bundle) into records.

Sources: ml/data_raw/hist/pr/PR*.zip (2016-10..2021-09) and ml/data_raw/pr/PR*.zip (2021-10..2026-10).
The true date of a bundle is the date inside its An member's name (an<ddmmyy>.txt or an<ddmmyyyy>.txt);
some bundle file names are wrong (PR020118.zip holds 2019-01-02, PR060424.zip holds 2024-06-04).

Record layout, profiled across the ten years (see EVENTS.md section 2):
  header   "COMPANY NAME    SYMBOL    : ANNOUNCEMENTS"
  wide     "<Company name>{2+ spaces}<SYMBOL>{pad} : <rest>"            (2016-10 .. 2025)
  narrow   "<Company name> <SYMBOL> : <rest>"                            (2026)
  rest     "<Category> <SYMBOL> : <text>"  or  "<Category> <SYMBOL>: <text>"     (2019 onwards, most lines)
           "<Category>-XBRL <TEXT>"                                               (XBRL filings, 2023 onwards)
           "<Category> <text>"                                                   (no separator)
           "<text[:k]><Category><text[k-1:]>"                                    (2016-2019: the category is
                                                                                   spliced into the text)
Lines that do not start a record (the text of an announcement can contain line breaks) are appended to the
previous record.  Category extraction uses the explicit separators where present, otherwise a dictionary of
categories learned from the explicit lines and from the spliced lines' company-name overlap.

Outputs ml/data_ext/events_raw.parquet (one row per record) and ml/results/improve2/events/parse.json.
Usage: python3 -m ml.events.parse [--workers 2]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import os
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parents[1]
BUNDLE_DIRS = [ML / "data_raw" / "hist" / "pr", ML / "data_raw" / "pr"]
OUT_RAW = ML / "data_ext" / "events_raw.parquet"
OUT_DIR = ML / "results" / "improve2" / "events"
VOCAB = Path(__file__).resolve().parent / "vocabulary.json"
EOD = ML / "results" / "improve" / "cache" / "eod_export_10y.parquet"
FEAT_PRICES = ML / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
TEXT_MAX = 1500          # characters of announcement text kept per record
MEMBER_RE = re.compile(r"(?i)^an(\d{6}|\d{8})\.txt$")
SYM = r"(?=[A-Z0-9&\-_.]*[A-Z])[A-Z0-9][A-Z0-9&\-_.]*"  # NSE symbols contain a letter
RE_WIDE = re.compile(r"^(?P<name>\S.*?)\s{2,}(?P<sym>" + SYM + r")\s*: ?(?P<rest>.*)$")
RE_NARROW = re.compile(r"^(?P<name>\S.*?) (?P<sym>" + SYM + r") : (?P<rest>.*)$")
RE_XBRL = re.compile(r"^(?P<cat>[^:]{3,140}?)-XBRL\b ?(?P<text>.*)$")
HEADER = "COMPANY NAME"
T0 = time.time()


def log(msg: str) -> None:
    print(f"[events.parse +{time.time() - T0:6.0f}s] {msg}", flush=True)


# ----------------------------------------------------------------------------- inventory
def member_date(name: str) -> dt.date | None:
    m = MEMBER_RE.match(os.path.basename(name))
    if not m:
        return None
    d = m.group(1)
    return dt.datetime.strptime(d, "%d%m%y" if len(d) == 6 else "%d%m%Y").date()


def inventory() -> pd.DataFrame:
    """Every PR bundle with its announcement member, the member's date and a content hash."""
    rows = []
    for root in BUNDLE_DIRS:
        for z in sorted(root.glob("PR*.zip")):
            bdate = dt.datetime.strptime(z.name[2:8], "%d%m%y").date()
            try:
                zf = zipfile.ZipFile(z)
            except zipfile.BadZipFile as e:
                rows.append(dict(bundle=str(z.relative_to(ML)), bundle_date=bdate, member=None, member_date=None,
                                 sha256=None, bytes=0, error=f"bad zip: {e}"))
                continue
            mems = [i for i in zf.infolist() if member_date(i.filename)]
            if not mems:
                rows.append(dict(bundle=str(z.relative_to(ML)), bundle_date=bdate, member=None, member_date=None,
                                 sha256=None, bytes=0, error="no announcement member"))
            for i in mems:
                raw = zf.read(i.filename)
                rows.append(dict(bundle=str(z.relative_to(ML)), bundle_date=bdate, member=i.filename,
                                 member_date=member_date(i.filename), sha256=hashlib.sha256(raw).hexdigest(),
                                 bytes=len(raw), member_time=str(dt.datetime(*i.date_time)), error=None))
    return pd.DataFrame(rows)


def select(inv: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """One bundle per true (member) date.  A bundle whose member date disagrees with its file name is skipped
    when the true date is also present in a correctly named bundle; byte-identical duplicates (the overlap of
    the two download folders) keep the copy in ml/data_raw/pr/.  Every decision is logged."""
    ok = inv[inv["member"].notna()].copy()
    ok["name_ok"] = ok["bundle_date"] == ok["member_date"]
    ok["recent_dir"] = ok["bundle"].str.startswith("data_raw/pr/")
    keep, decisions = [], []
    for d, g in ok.groupby("member_date", sort=True):
        if len(g) == 1:
            r = g.iloc[0]
            if not r["name_ok"]:
                decisions.append(dict(member_date=str(d), bundle=r["bundle"], action="kept",
                                      reason="file name disagrees with member date, true date not present elsewhere"))
            keep.append(r)
            continue
        g = g.sort_values(["name_ok", "recent_dir"], ascending=False)
        r = g.iloc[0]
        keep.append(r)
        for _, x in g.iloc[1:].iterrows():
            why = ("file name disagrees with member date; true date present in " + r["bundle"]) if not x["name_ok"] \
                else ("duplicate of " + r["bundle"])
            decisions.append(dict(member_date=str(d), bundle=x["bundle"], action="skipped", reason=why,
                                  identical_bytes=bool(x["sha256"] == r["sha256"])))
    sel = pd.DataFrame(keep).reset_index(drop=True)
    return sel, decisions


# ----------------------------------------------------------------------------- one file
def decode(raw: bytes) -> tuple[str, str]:
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def read_member(bundle: str, member: str) -> tuple[str, str]:
    with zipfile.ZipFile(ML / bundle) as zf:
        return decode(zf.read(member))


def split_records(text: str, known_syms: set[str] | None) -> tuple[list[dict], dict]:
    """Segment one file into records.  A line starts a record if it matches the wide layout, or the narrow
    layout with its symbol confirmed (repeated as "<SYMBOL> :" in the rest, or a symbol seen in the wide layout
    or in the bhavcopy).  Other non-empty lines continue the previous record."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    recs: list[dict] = []
    st = collections.Counter()
    for ln, line in enumerate(lines):
        s = line.rstrip()
        if not s.strip():
            continue
        if not recs and s.startswith(HEADER):
            st["header"] += 1
            continue
        m = RE_WIDE.match(s)
        layout = "wide"
        if m is not None and known_syms is not None and m.group("sym") not in known_syms \
                and not _confirms(m.group("sym"), m.group("rest")):
            m = None
        if m is None:
            m = RE_NARROW.match(s)
            layout = "narrow"
            if m is not None and not (_confirms(m.group("sym"), m.group("rest"))
                                      or (known_syms is not None and m.group("sym") in known_syms)):
                m = None
        if m is None:
            if recs:
                recs[-1]["rest"] += " " + s.strip()
                recs[-1]["n_cont"] += 1
                st["continuation_lines"] += 1
            else:
                st["orphan_lines"] += 1
            continue
        recs.append(dict(line_no=ln, company=" ".join(m.group("name").split()), symbol=m.group("sym"),
                         rest=m.group("rest").strip(), layout=layout, n_cont=0))
        st[f"records_{layout}"] += 1
    return recs, dict(st)


def _confirms(sym: str, rest: str) -> bool:
    head = rest[:220]
    return (f" {sym} :" in head) or (f" {sym}:" in head) or head.startswith(f"{sym} :")


# ----------------------------------------------------------------------------- categories
def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def explicit_category(sym: str, rest: str) -> tuple[str | None, str, str]:
    """Category from an explicit separator: "<cat> SYM : text", "<cat> SYM: text", "<cat>-XBRL TEXT"."""
    head = rest[:260]
    best = None
    for mk in (f" {sym} :", f" {sym}:"):
        p = head.find(mk)
        if p > 0 and (best is None or p < best[0]):
            best = (p, len(mk))
    if best is not None:
        p, n = best
        return rest[:p].strip(), rest[p + n:].strip(), "cat_sym"
    m = RE_XBRL.match(rest)
    if m:
        return m.group("cat").strip(), m.group("text").strip(), "xbrl"
    return None, rest, ""


def spliced_category(company: str, rest: str, max_k: int = 40) -> tuple[str | None, str]:
    """2016-2019 layout: rest = text[:k] + category + text[k-1:] (k >= 1) or category + " " + text (k = 0), where
    text starts with the company name.  Returns (category, text) or (None, rest)."""
    name = company
    if len(name) < 4:
        return None, rest
    best = None
    for k in range(min(max_k, len(name)), -1, -1):
        if rest[:k] != name[:k]:
            continue
        a = max(k - 1, 0)
        probe = name[a:a + 10]
        if len(probe) < 4:
            continue
        q = rest.find(probe, k + 1)
        if q <= k or q - k > 160:
            continue
        cat = rest[k:q].strip()
        if not cat or len(cat) < 3:
            continue
        best = (cat, (rest[:k] + rest[q + (1 if k > 0 else 0):]) if k > 0 else rest[q:])
        break
    if best is None:
        return None, rest
    return best


def first_pass(args) -> tuple[collections.Counter, collections.Counter, collections.Counter]:
    """Learn categories and symbols from one file: explicit categories, spliced categories, wide symbols."""
    bundle, member = args[:2]
    text, _ = read_member(bundle, member)
    recs, _ = split_records(text, None)
    expl, spl, syms = collections.Counter(), collections.Counter(), collections.Counter()
    for r in recs:
        if r["layout"] == "wide":
            syms[r["symbol"]] += 1
        cat, _, how = explicit_category(r["symbol"], r["rest"])
        if cat is not None:
            expl[cat] += 1
            continue
        c2, _ = spliced_category(r["company"], r["rest"])
        if c2 is not None:
            spl[c2] += 1
    return expl, spl, syms


OPENERS = ("the exchange", "members of the exchange", "this is to", "pursuant to", "further to", "we wish",
           "dear sir", "in terms of", "in compliance", "with reference", "the company", "the board", "intimation")


def build_dictionary(expl: collections.Counter, spl_old: collections.Counter, min_expl: int = 3,
                     min_spliced: int = 5) -> list[str]:
    """Category dictionary: explicit categories seen >= min_expl times, plus categories of the spliced layout
    (learned only from files dated before 2019, the years of that layout) seen >= min_spliced times that look
    like a category: start with a capital or digit, <= 100 characters, no announcement prose, not a truncated
    fragment of an explicit category.  Longest first."""
    ex = {c for c, n in expl.items() if n >= min_expl and 2 <= len(c) <= 150}
    bad = ("has informed", "has submitted", "had sought", "has sought", "Net Asset Value", " : ", "inform you")
    sp = set()
    for c, n in spl_old.items():
        if n < min_spliced or not (2 <= len(c) <= 100) or not (c[0].isupper() or c[0].isdigit()):
            continue
        if any(b in c for b in bad):
            continue
        if any(c != e and e.endswith(c) for e in ex):
            continue
        sp.add(c)
    return sorted(ex | sp, key=lambda c: (-len(c), c))


def compile_dictionary(cats_sorted: list[str]) -> re.Pattern:
    return re.compile("|".join(re.escape(c) for c in cats_sorted))


def assign_category(company: str, sym: str, rest: str, cat_re: re.Pattern, max_len: int) -> tuple[str, str, str]:
    """(category, text, method).  Order: explicit separator; dictionary category at the start of the rest
    (longest); dictionary category spliced after a prefix of the text (leftmost, then longest), where the prefix
    must be the start of the company name or of a standard opener; company-name overlap; none."""
    cat, text, how = explicit_category(sym, rest)
    if cat is not None:
        return cat, text, how
    m = cat_re.match(rest)
    if m and (m.end() == len(rest) or not rest[m.end()].isalnum()):
        return m.group(0), rest[m.end():].strip(), "dict_prefix"
    lname = " ".join(company.lower().split())
    for m in cat_re.finditer(rest, 1, min(len(rest), 46 + max_len)):
        p = m.start()
        if p > 45:
            break
        pre = " ".join(rest[:p].lower().split())
        if lname.startswith(pre) or any(o.startswith(pre) for o in OPENERS):
            return m.group(0), (rest[:p] + rest[m.end() + 1:]).strip(), "dict_spliced"
        if p <= 30 and len(m.group(0)) >= 15:  # text starting with another party's name (takeover disclosures)
            return m.group(0), (rest[:p] + rest[m.end() + 1:]).strip(), "dict_spliced_loose"
    c2, t2 = spliced_category(company, rest)
    if c2 is not None and len(c2) <= 100 and "has informed" not in c2 and "had sought" not in c2:
        return c2, t2, "derived"
    return "", rest, "none"


RE_BM = re.compile(r"^(?P<name>\S.*?)\s+(?P<sym>" + SYM + r")\s*:\s*(?P<d>\d{1,2}-[A-Za-z]{3}-\d{4})\s*:\s?(?P<p>.*)$")
BM_MEMBER_RE = re.compile(r"(?i)^bm(\d{6}|\d{8})\.txt$")


def board_meetings(bundle: str, mdate) -> tuple[list[dict], dict]:
    """The bundle's board-meeting list (Bm<date>.txt): "<Company> <SYMBOL> : <meeting date> : <purpose>".
    Used only to tell whether a later "Outcome of Board Meeting" was the outcome of a meeting intimated for
    financial results (EVENTS.md rule R3); never counted as an announcement."""
    with zipfile.ZipFile(ML / bundle) as zf:
        mem = [n for n in zf.namelist() if BM_MEMBER_RE.match(os.path.basename(n))]
        if not mem:
            return [], {"bm_member": 0}
        text, _ = decode(zf.read(mem[0]))
    out: list[dict] = []
    for ln, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        s = line.strip()
        if not s or (not out and s.upper().startswith("COMPANY NAME")):
            continue
        m = RE_BM.match(s)
        if m is None:
            if out:
                out[-1]["text"] = (out[-1]["text"] + " " + s)[:TEXT_MAX]
            continue
        md = pd.to_datetime(m.group("d"), format="%d-%b-%Y", errors="coerce")
        out.append(dict(file_date=mdate, symbol=m.group("sym"), company=" ".join(m.group("name").split()),
                        category_raw="(board meeting list)", text=m.group("p").strip()[:TEXT_MAX],
                        text_len=len(m.group("p")), cat_method="bm", layout="bm", n_cont=0, line_no=ln,
                        bundle=bundle, bm_date=md))
    return out, {"bm_member": 1, "bm_records": len(out)}


def second_pass(args) -> tuple[list[dict], dict]:
    bundle, member, mdate, known_syms, cat_re, max_len = args
    text, enc = read_member(bundle, member)
    recs, st = split_records(text, known_syms)
    out = []
    for r in recs:
        cat, body, how = assign_category(r["company"], r["symbol"], r["rest"], cat_re, max_len)
        out.append(dict(file_date=mdate, symbol=r["symbol"], company=r["company"], category_raw=cat,
                        text=body[:TEXT_MAX], text_len=len(body), cat_method=how, layout=r["layout"],
                        n_cont=r["n_cont"], line_no=r["line_no"], bundle=bundle, bm_date=pd.NaT))
    st["encoding"] = enc
    bm, bst = board_meetings(bundle, mdate)
    st.update(bst)
    return out + bm, st


# ----------------------------------------------------------------------------- main
_KNOWN: set[str] = set()
_CATS: list[str] = []
_CAT_RE: re.Pattern | None = None


def _second(args):
    bundle, member, mdate = args
    return second_pass((bundle, member, mdate, _KNOWN, _CAT_RE, len(_CATS[0]) if _CATS else 0))


def learn_vocabulary(sel: pd.DataFrame, workers: int = 2) -> dict:
    """The parser's fixed parameters, learned once from the whole corpus (like the rule table, from text only; no
    price information): the category dictionary and the list of known symbols (wide-layout symbols seen >= 3 times,
    plus every EQ/BE bhavcopy symbol).  Saved to VOCAB and held fixed by every later parse, including the
    point-in-time tests, so that a file's records depend on that file alone."""
    jobs = list(zip(sel["bundle"], sel["member"]))
    with mp.get_context("fork").Pool(workers) as pool:
        res = pool.map(first_pass, jobs, chunksize=8)
    expl, spl, syms = collections.Counter(), collections.Counter(), collections.Counter()
    for (a, b, c), d in zip(res, sel["member_date"]):
        expl.update(a)
        if d.year <= 2018:
            spl.update(b)
        syms.update(c)
    eod_syms = set(pd.read_parquet(EOD, columns=["ticker"])["ticker"].unique())
    known = sorted({s for s, n in syms.items() if n >= 3} | eod_syms)
    cats = build_dictionary(expl, spl)
    voc = {"learned_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "files": int(len(sel)),
           "rule": "categories: explicit separator categories seen >= 3 times + spliced-layout categories (files "
                   "before 2019) seen >= 5 times that look like a category; symbols: wide-layout symbols seen >= 3 "
                   "times + EQ/BE bhavcopy symbols",
           "n_explicit_categories": len(expl), "n_spliced_candidates": len(spl),
           "categories": cats, "known_symbols": known}
    VOCAB.write_text(json.dumps(voc, indent=0))
    return voc


def load_vocabulary() -> tuple[set[str], list[str], re.Pattern]:
    voc = json.loads(VOCAB.read_text())
    cats = voc["categories"]
    return set(voc["known_symbols"]), cats, compile_dictionary(cats)


def parse_file(bundle: str, member: str, mdate, vocab: tuple[set[str], list[str], re.Pattern]) -> pd.DataFrame:
    """Records of one bundle (announcements + board-meeting list) with the fixed vocabulary: used by the
    point-in-time checks to recompute from the raw zip files."""
    known, cats, cat_re = vocab
    out, _ = second_pass((bundle, member, mdate, known, cat_re, len(cats[0]) if cats else 0))
    return pd.DataFrame(out)


def run(workers: int = 2, relearn: bool = False) -> dict:
    global _KNOWN, _CATS, _CAT_RE
    inv = inventory()
    sel, decisions = select(inv)
    log(f"inventory: {len(inv)} bundles, {inv['member'].notna().sum()} announcement members; "
        f"selected {len(sel)} dates; {len(decisions)} decisions logged")
    if relearn or not VOCAB.exists():
        voc = learn_vocabulary(sel, workers)
        log(f"vocabulary learned: {voc['n_explicit_categories']} explicit categories, {voc['n_spliced_candidates']} "
            f"spliced candidates -> dictionary {len(voc['categories'])}; {len(voc['known_symbols'])} known symbols")
    _KNOWN, _CATS, _CAT_RE = load_vocabulary()
    log(f"vocabulary: {len(_CATS)} categories, {len(_KNOWN)} known symbols ({VOCAB.name})")
    ctx = mp.get_context("fork")
    eod_syms = set(pd.read_parquet(EOD, columns=["ticker"])["ticker"].unique())
    jobs2 = list(zip(sel["bundle"], sel["member"], sel["member_date"]))
    with ctx.Pool(workers) as pool:
        res2 = pool.map(_second, jobs2, chunksize=8)
    recs, per_file = [], []
    for (out, st), (b, m, d) in zip(res2, jobs2):
        recs.extend(out)
        per_file.append(dict(bundle=b, member=m, member_date=str(d), records=sum(r["layout"] != "bm" for r in out), **st))
    ev = pd.DataFrame(recs)
    ev["file_date"] = pd.to_datetime(ev["file_date"])
    ev["bm_date"] = pd.to_datetime(ev["bm_date"])
    ev["source"] = np.where(ev["layout"] == "bm", "bm", "an")
    log(f"second pass: {len(ev):,} records ({(ev['source'] == 'bm').sum():,} board-meeting list rows)")
    # session mapping: a file dated on a non-session date maps to the next session
    sess = np.sort(pd.read_parquet(FEAT_PRICES, columns=["date"])["date"].unique()).astype("datetime64[ns]")
    fd = ev["file_date"].to_numpy(dtype="datetime64[ns]")
    pos = np.searchsorted(sess, fd, side="left")
    ev["session_date"] = pd.NaT
    inside = pos < len(sess)
    ev.loc[inside, "session_date"] = sess[pos[inside]]
    ev["session_date"] = pd.to_datetime(ev["session_date"])
    ev["file_on_session"] = ev["file_date"] == ev["session_date"]
    ev["in_eod"] = ev["symbol"].isin(eod_syms)
    for c in ("symbol", "company", "category_raw", "cat_method", "layout", "bundle", "source"):
        ev[c] = ev[c].astype("string")
    ev = ev.sort_values(["file_date", "source", "line_no"], kind="stable").reset_index(drop=True)
    OUT_RAW.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_RAW.with_suffix(".tmp.parquet")
    ev.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(OUT_RAW)
    pf = pd.DataFrame(per_file)
    sess_set = set(pd.DatetimeIndex(sess).date)
    file_dates = set(sel["member_date"])
    no_file_sessions = sorted(str(d) for d in sess_set - file_dates)
    off_session_files = sorted(str(d) for d in file_dates - sess_set)
    year = pd.to_datetime(pf["member_date"]).dt.year
    by_year = {}
    for y, g in pf.groupby(year):
        e = ev[(ev["file_date"].dt.year == y) & (ev["source"] == "an")]
        by_year[int(y)] = {"bundles_parsed": int(len(g)), "records": int(g["records"].sum()),
                           "continuation_lines": int(g.get("continuation_lines", pd.Series(0)).fillna(0).sum()),
                           "layout_wide": int((e["layout"] == "wide").sum()), "layout_narrow": int((e["layout"] == "narrow").sum()),
                           "cat_method": {k: int(v) for k, v in e["cat_method"].value_counts().items()},
                           "symbols": int(e["symbol"].nunique()), "symbols_in_bhavcopy": int(e.loc[e["in_eod"], "symbol"].nunique()),
                           "records_symbol_in_bhavcopy": int(e["in_eod"].sum()),
                           "board_meeting_list_rows": int(((ev["file_date"].dt.year == y) & (ev["source"] == "bm")).sum())}
    summary = {
        "sources": [str(p.relative_to(ML)) for p in BUNDLE_DIRS],
        "bundles_found": int(len(inv)), "bundles_with_member": int(inv["member"].notna().sum()),
        "bundle_errors": inv[inv["error"].notna()][["bundle", "error"]].to_dict("records"),
        "dates_selected": int(len(sel)), "selection_decisions": decisions,
        "name_vs_member_date_mismatches": inv[(inv["member"].notna()) & (inv["bundle_date"] != inv["member_date"])]
        [["bundle", "bundle_date", "member", "member_date"]].astype(str).to_dict("records"),
        "member_generated_after_next_open": _late_members(sel, sess),
        "sessions_in_calendar": int(len(sess)), "sessions_without_file": no_file_sessions,
        "files_on_non_session_dates": off_session_files,
        "records": int((ev["source"] == "an").sum()), "board_meeting_list_rows": int((ev["source"] == "bm").sum()),
        "records_after_last_session": int(ev["session_date"].isna().sum()),
        "encodings": {k: int(v) for k, v in pf["encoding"].value_counts().items()},
        "dictionary_categories": len(_CATS), "dictionary_rule": "explicit categories seen >= 3 times plus "
        "spliced-layout categories seen >= 5 times that look like a category (build_dictionary)",
        "vocabulary": str(VOCAB.relative_to(ML)),
        "known_symbols": len(_KNOWN), "text_max_chars": TEXT_MAX,
        "by_year": by_year,
        "seconds": round(time.time() - T0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "parse.json").write_text(json.dumps(summary, indent=1, default=str))
    pf.to_csv(OUT_DIR / "parse_files.csv", index=False)
    log(f"wrote {OUT_RAW} ({len(ev):,} records) and parse.json")
    return summary


def _late_members(sel: pd.DataFrame, sess: np.ndarray) -> list[dict]:
    """Members whose zip timestamp is later than 09:15 on the next session (would break "usable at t")."""
    out = []
    sd = pd.DatetimeIndex(sess)
    for _, r in sel.iterrows():
        ts = pd.Timestamp(r["member_time"])
        d = pd.Timestamp(r["member_date"])
        nxt = sd[sd > d]
        if len(nxt) and ts > nxt[0] + pd.Timedelta(hours=9, minutes=15):
            out.append(dict(member_date=str(d.date()), member_time=str(ts), next_session=str(nxt[0].date())))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--relearn", action="store_true", help="re-learn the fixed vocabulary (dictionary, symbols)")
    a = ap.parse_args()
    run(a.workers, a.relearn)


if __name__ == "__main__":
    main()
