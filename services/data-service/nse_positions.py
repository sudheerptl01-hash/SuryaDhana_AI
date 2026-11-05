"""
NSE "who is holding overnight" datasets (docs/NSE_DATA_DICTIONARY.md), from the public
archives. Delivery quantity/% already comes with the full bhavcopy (bhavcopy.py).

  fo              F&O bhavcopy → one row per underlying per day: futures OI/price/volume
                  summed across expiries, options call/put OI (nse_fo_daily).
  participant_oi  Long/short contracts by Client, DII, FII, Pro (nse_participant_oi).
  deals           Bulk and block deals by named client, institutional short selling (nse_deals).
  mtf             Margin-trading funded positions per stock + market totals (nse_mtf, nse_mtf_market).

Units (verified against ICICI Breeze on INFY): open interest is in shares in both F&O
formats; traded volume is in contracts; old-format value is ₹ lakh, UDiFF value is ₹.
Raw daily files are cached under <data>/nse_archive/<dataset>/YYYY/, so re-ingesting
never re-downloads. Files are public; NSE wants a browser User-Agent and polite pacing.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import httpx
import pandas as pd

from bhavcopy import HEADERS
from shared.logging import get_logger

logger = get_logger(__name__)

ARCHIVE = "https://nsearchives.nseindia.com"
API = "https://www.nseindia.com/api"
UDIFF_FO_START = date(2024, 7, 8)            # old-format F&O bhavcopy stops on this date
START = {"fo": date(2019, 10, 1), "participant_oi": date(2019, 10, 1),
         "deals": date(2019, 10, 1), "mtf": date(2022, 1, 3)}   # MTF archive begins Jan-2022
DATASETS = tuple(START)


# ── download helpers ─────────────────────────────────────────────────────────────

def _cached_get(url: str, cache: Path, client: httpx.Client, retries: int = 3) -> tuple[Optional[bytes], str]:
    """(bytes or None, status): cached | downloaded | missing | error:<msg>."""
    if cache.exists():
        return cache.read_bytes(), "cached"
    last = ""
    for attempt in range(retries):
        try:
            r = client.get(url)
            if r.status_code == 404:
                return None, "missing"
            if r.status_code == 200 and r.content and not r.content.lstrip().startswith(b"<"):
                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache.with_suffix(cache.suffix + ".tmp")
                tmp.write_bytes(r.content)
                tmp.replace(cache)
                return r.content, "downloaded"
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2.0 * (2 ** attempt))
    return None, f"error:{last}"


def _unzip_first(blob: bytes) -> bytes:
    if blob[:2] != b"PK":
        return blob
    z = zipfile.ZipFile(io.BytesIO(blob))
    name = next((n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))), z.namelist()[0])
    return z.read(name)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip().replace({"-": None, "": None, "nan": None}),
                         errors="coerce")


# ── F&O bhavcopy ────────────────────────────────────────────────────────────────

def fo_urls(day: date) -> list[str]:
    mon = day.strftime("%b").upper()
    old = f"{ARCHIVE}/content/historical/DERIVATIVES/{day:%Y}/{mon}/fo{day:%d}{mon}{day:%Y}bhav.csv.zip"
    new = f"{ARCHIVE}/content/fo/BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    return [new, old] if day >= UDIFF_FO_START else [old, new]


def parse_fo_bhavcopy(blob: bytes, day: date) -> pd.DataFrame:
    """Either F&O format → contract rows: symbol, kind (stock|index), instrument (FUT|OPT),
    expiry, strike, option_type (CE|PE|None), close, settle, contracts, value_lakh, oi, oi_chg."""
    df = pd.read_csv(io.BytesIO(_unzip_first(blob)), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if "FinInstrmTp" in df.columns:                                   # UDiFF, since Jul-2024
        tp = df["FinInstrmTp"].str.strip()
        out = pd.DataFrame({
            "symbol": df["TckrSymb"].str.strip(),
            "kind": tp.map({"STF": "stock", "STO": "stock", "IDF": "index", "IDO": "index"}),
            "instrument": tp.map({"STF": "FUT", "IDF": "FUT", "STO": "OPT", "IDO": "OPT"}),
            "expiry": pd.to_datetime(df["XpryDt"], errors="coerce").dt.date,
            "strike": _num(df["StrkPric"]),
            "option_type": df["OptnTp"].str.strip().where(tp.isin(["STO", "IDO"])),
            "close": _num(df["ClsPric"]), "settle": _num(df["SttlmPric"]),
            "contracts": _num(df["TtlTradgVol"]), "value_lakh": _num(df["TtlTrfVal"]) / 1e5,
            "oi": _num(df["OpnIntrst"]), "oi_chg": _num(df["ChngInOpnIntrst"]),
        })
    elif "INSTRUMENT" in df.columns:                                  # classic fo…bhav.csv
        ins = df["INSTRUMENT"].str.strip()
        out = pd.DataFrame({
            "symbol": df["SYMBOL"].str.strip(),
            "kind": ins.map({"FUTSTK": "stock", "OPTSTK": "stock", "FUTIDX": "index", "OPTIDX": "index"}),
            "instrument": ins.map({"FUTSTK": "FUT", "FUTIDX": "FUT", "OPTSTK": "OPT", "OPTIDX": "OPT"}),
            "expiry": pd.to_datetime(df["EXPIRY_DT"].str.strip(), format="%d-%b-%Y", errors="coerce").dt.date,
            "strike": _num(df["STRIKE_PR"]),
            "option_type": df["OPTION_TYP"].str.strip().where(ins.isin(["OPTSTK", "OPTIDX"])),
            "close": _num(df["CLOSE"]), "settle": _num(df["SETTLE_PR"]),
            "contracts": _num(df["CONTRACTS"]), "value_lakh": _num(df["VAL_INLAKH"]),
            "oi": _num(df["OPEN_INT"]), "oi_chg": _num(df["CHG_IN_OI"]),
        })
    else:
        raise ValueError(f"unknown F&O bhavcopy layout: {list(df.columns)[:6]}")
    out = out.dropna(subset=["kind", "instrument", "symbol"])
    out["date"] = day
    return out.reset_index(drop=True)


def aggregate_fo(contracts: pd.DataFrame) -> pd.DataFrame:
    """Contract rows → one row per (date, symbol). Futures OI is summed across expiries
    (the rollover-neutral measure); price is the nearest expiry's close and settlement."""
    if contracts.empty:
        return pd.DataFrame()
    keys = ["date", "symbol", "kind"]
    fut = contracts[contracts["instrument"] == "FUT"]
    near = (fut.sort_values("expiry").groupby(keys, as_index=False)
            .first()[keys + ["expiry", "close", "settle"]]
            .rename(columns={"expiry": "near_expiry", "close": "fut_close", "settle": "fut_settle"}))
    fsum = fut.groupby(keys, as_index=False).agg(fut_oi=("oi", "sum"), fut_oi_chg=("oi_chg", "sum"),
                                                  fut_contracts=("contracts", "sum"), fut_value_lakh=("value_lakh", "sum"))
    opt = contracts[contracts["instrument"] == "OPT"]
    osum = opt.groupby(keys, as_index=False).agg(opt_contracts=("contracts", "sum"), opt_value_lakh=("value_lakh", "sum"))
    side = (opt.pivot_table(index=keys, columns="option_type", values=["oi", "oi_chg"], aggfunc="sum", fill_value=0))
    side.columns = [f"{'put' if t == 'PE' else 'call'}_{v}" for v, t in side.columns]
    side = side.reset_index()
    out = near.merge(fsum, on=keys, how="outer").merge(osum, on=keys, how="outer").merge(side, on=keys, how="outer")
    for c in ("call_oi", "put_oi", "call_oi_chg", "put_oi_chg"):
        if c not in out:
            out[c] = 0.0
    return out


# ── participant-wise open interest ───────────────────────────────────────────────

PARTICIPANT_COLS = ["fut_idx_long", "fut_idx_short", "fut_stk_long", "fut_stk_short",
                    "opt_idx_call_long", "opt_idx_put_long", "opt_idx_call_short", "opt_idx_put_short",
                    "opt_stk_call_long", "opt_stk_put_long", "opt_stk_call_short", "opt_stk_put_short",
                    "total_long", "total_short"]


def participant_url(day: date) -> str:
    return f"{ARCHIVE}/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"


def parse_participant_oi(blob: bytes, day: date) -> pd.DataFrame:
    """First line is a title; columns carry stray tabs. Column order is fixed by NSE."""
    lines = blob.decode("utf-8", "replace").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.lower().lstrip('"').startswith("client type"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str)
    df = df.iloc[:, :15]
    df.columns = ["client_type"] + PARTICIPANT_COLS
    df["client_type"] = df["client_type"].str.strip().str.upper()
    df = df[df["client_type"].isin(["CLIENT", "DII", "FII", "PRO", "TOTAL"])].copy()
    for c in PARTICIPANT_COLS:
        df[c] = _num(df[c]).astype("Int64")
    df["date"] = day
    return df.reset_index(drop=True)


# ── bulk / block deals and short selling ─────────────────────────────────────────

DEAL_OPTIONS = {"bulk": "bulk_deals", "block": "block_deals", "short": "short_selling"}


def deals_url(kind: str, start: date, end: date) -> str:
    # The JSON variant silently caps at 70 rows; csv=true returns the full set.
    return (f"{API}/historicalOR/bulk-block-short-deals?optionType={DEAL_OPTIONS[kind]}"
            f"&from={start:%d-%m-%Y}&to={end:%d-%m-%Y}&csv=true")


def parse_deals(blob: bytes, kind: str) -> pd.DataFrame:
    text = blob.decode("utf-8-sig", "replace")
    if not text.strip():
        return pd.DataFrame(columns=["date", "kind", "symbol", "security_name", "client_name", "side", "qty", "price", "remarks"])
    df = pd.read_csv(io.StringIO(text), dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    pick = lambda *names: next((df[n] for n in names if n in df.columns), pd.Series([None] * len(df)))  # noqa: E731
    out = pd.DataFrame({
        "date": pd.to_datetime(pick("date").str.strip(), format="%d-%b-%Y", errors="coerce").dt.date,
        "kind": kind,
        "symbol": pick("symbol").str.strip(),
        "security_name": pick("security name").str.strip(),
        "client_name": pick("client name").astype(str).str.strip().replace({"None": None, "nan": None}),
        "side": pick("buy / sell", "buy/sell").astype(str).str.strip().str.upper().replace({"NONE": None, "NAN": None}),
        "qty": _num(pick("quantity traded", "quantity")),
        "price": _num(pick("trade price / wght. avg. price")),
        "remarks": pick("remarks").astype(str).str.strip().replace({"None": None, "nan": None, "-": None}),
    })
    if kind == "short":
        out["side"] = "SELL"
    return out.dropna(subset=["date", "symbol"]).reset_index(drop=True)


# ── margin trading (MTF) ─────────────────────────────────────────────────────────

def mtf_url(day: date) -> str:
    return f"{ARCHIVE}/content/equities/mrg_trading_{day:%d%m%y}.zip"


def parse_mtf(blob: bytes, day: date) -> tuple[pd.DataFrame, dict]:
    """The report opens with four market-total lines (₹ lakh), then a per-stock table."""
    raw = pd.read_csv(io.BytesIO(_unzip_first(blob)), header=None, dtype=str, on_bad_lines="skip")
    totals = {"date": day}
    labels = {"beginning": "begin_lakh", "fresh": "fresh_lakh", "liquidated": "liquidated_lakh", "end of the day": "end_lakh"}
    for _, row in raw.iterrows():
        text = " ".join(str(v) for v in row if isinstance(v, str)).lower()
        for key, col in labels.items():
            if key in text and col not in totals:
                vals = [v for v in _num(pd.Series(list(row))).dropna().tolist() if v > 10]
                if vals:
                    totals[col] = float(vals[-1])
    head = raw.index[raw.apply(lambda r: r.astype(str).str.strip().str.lower().eq("symbol").any(), axis=1)]
    if not len(head):
        raise ValueError("MTF report without a per-stock table")
    table = raw.iloc[int(head[0]) + 1:, :4].copy()
    table.columns = ["symbol", "name", "qty_financed", "amount_lakh"]
    table["symbol"] = table["symbol"].astype(str).str.strip()
    table["qty_financed"] = _num(table["qty_financed"])
    table["amount_lakh"] = _num(table["amount_lakh"])
    table = table.dropna(subset=["qty_financed"])
    table = table[table["symbol"].str.len() > 0]
    table["date"] = day
    return table.reset_index(drop=True), totals


# ── orchestration ────────────────────────────────────────────────────────────────

@dataclass
class DatasetSummary:
    dataset: str
    start: str
    end: str
    requested: int = 0
    loaded: int = 0
    cached: int = 0
    missing: int = 0
    rows_written: int = 0
    failures: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["failures"] = self.failures[:30]
        d["failure_count"] = len(self.failures)
        return d


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(n) for n in range((end - start).days + 1)]


def ingest_daily(store, dataset: str, start: date, end: date, cache_root: Path,
                 progress: Optional[Callable] = None, client: Optional[httpx.Client] = None,
                 sleep_s: float = 0.35) -> dict:
    """Download (or read cached) and upsert one per-day dataset for every day in [start, end].
    Weekends are tried too: NSE holds special sessions; ordinary weekends simply 404."""
    s = DatasetSummary(dataset, start.isoformat(), end.isoformat())
    own = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=45, follow_redirects=True)
    days = _days(start, end)
    s.requested = len(days)
    try:
        for i, day in enumerate(days, 1):
            if dataset == "fo":
                urls = fo_urls(day)
            elif dataset == "participant_oi":
                urls = [participant_url(day)]
            elif dataset == "mtf":
                urls = [mtf_url(day)]
            else:
                raise ValueError(f"not a per-day dataset: {dataset}")
            blob, status = None, "missing"
            for url in urls:
                cache = cache_root / dataset / f"{day:%Y}" / url.rsplit("/", 1)[-1]
                blob, status = _cached_get(url, cache, client)
                if blob is not None:
                    break
                if status == "downloaded":
                    time.sleep(sleep_s)
            if blob is None:
                if status == "missing":
                    s.missing += 1
                else:
                    s.failures.append({"date": day.isoformat(), "error": status})
            else:
                try:
                    if dataset == "fo":
                        s.rows_written += store.upsert_fo_daily(aggregate_fo(parse_fo_bhavcopy(blob, day)))
                    elif dataset == "participant_oi":
                        s.rows_written += store.upsert_participant_oi(parse_participant_oi(blob, day))
                    else:
                        table, totals = parse_mtf(blob, day)
                        s.rows_written += store.upsert_mtf(table, totals)
                    s.loaded += 1
                    s.cached += status == "cached"
                except Exception as exc:          # one bad file must not stop a backfill
                    s.failures.append({"date": day.isoformat(), "error": f"parse: {exc}"})
                if status == "downloaded":
                    time.sleep(sleep_s)
            if progress:
                progress(i, len(days))
    finally:
        if own:
            client.close()
    logger.info("NSE positions ingest", **{k: v for k, v in s.as_dict().items() if k != "failures"})
    return s.as_dict()


def ingest_deals(store, start: date, end: date, progress: Optional[Callable] = None,
                 client: Optional[httpx.Client] = None, sleep_s: float = 1.0) -> dict:
    """Bulk, block and short-selling records, fetched a calendar month at a time."""
    s = DatasetSummary("deals", start.isoformat(), end.isoformat())
    own = client is None
    client = client or httpx.Client(headers={**HEADERS, "Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"},
                                    timeout=60, follow_redirects=True)
    months = []
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        months.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    s.requested = len(months) * len(DEAL_OPTIONS)
    try:
        for i, (a, b) in enumerate(months, 1):
            for kind in DEAL_OPTIONS:
                try:
                    r = client.get(deals_url(kind, a, b))
                    r.raise_for_status()
                    df = parse_deals(r.content, kind)
                    s.rows_written += store.replace_deals(kind, a, b, df)
                    s.loaded += 1
                except Exception as exc:  # noqa: BLE001
                    s.failures.append({"kind": kind, "from": a.isoformat(), "error": str(exc)[:160]})
                time.sleep(sleep_s)
            if progress:
                progress(i, len(months))
    finally:
        if own:
            client.close()
    logger.info("NSE deals ingest", **{k: v for k, v in s.as_dict().items() if k != "failures"})
    return s.as_dict()


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Terminal v2 (PLAN 1.1 / 1.4 / Wave 0 0.5; builder B1-DATA): the verified-but-missing NSE evening files, every fetch
# through the allowlisted, paced ``shared.http_client.PacedClient`` and logged in ``ingest_log`` (sha256, Last-Modified,
# If-Modified-Since revisions). Parsers are pure (fixtures under tests/unit/fixtures/terminal_v2/). Nothing here feeds
# the Decision Desk, the S1 shadow, a directional alert or a ticket price.
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
import json as _json
import re as _re
from datetime import datetime as _datetime
from datetime import timezone as _timezone
from typing import Any as _Any

FOVOLT_URL = f"{ARCHIVE}/archives/nsccl/volt/FOVOLT_{{d:%d%m%Y}}.csv"
CONTRACT_DELTA_URL = f"{ARCHIVE}/content/nsccl/Contract_Delta_{{d:%d%m%Y}}.csv"
COMBINED_OI_DELEQ_URL = f"{ARCHIVE}/archives/nsccl/mwpl/combineoi_deleq_{{d:%d%m%Y}}.csv"
COMBINED_OI_ZIP_URL = f"{ARCHIVE}/archives/nsccl/mwpl/combineoi_{{d:%d%m%Y}}.zip"
INDEX_CLOSE_URL = f"{ARCHIVE}/content/indices/ind_close_all_{{d:%d%m%Y}}.csv"
PARTICIPANT_VOL_URL = f"{ARCHIVE}/content/nsccl/fao_participant_vol_{{d:%d%m%Y}}.csv"
FII_STATS_URL = f"{ARCHIVE}/content/fo/fii_stats_{{d:%d-%b-%Y}}.xls"
MWPL_CLI_URL = f"{ARCHIVE}/content/nsccl/mwpl_cli_{{d:%d%m%Y}}.xls"
SECBAN_URL = f"{ARCHIVE}/archives/fo/sec_ban/fo_secban_{{d:%d%m%Y}}.csv"
VIX_HISTORY_URL = f"{API}/historicalOR/vixhistory?from={{start:%d-%m-%Y}}&to={{end:%d-%m-%Y}}"

# Desk inputs (shared/momentum.py reads market_index_daily NIFTY50): never written from the NSE daily file unless the
# owner answers O-T9 ("DO NOT CHANGE without review"). index_ohlc_daily and vix_daily are separate tables and always written.
DESK_INDEX_SYMBOLS = frozenset({"NIFTY50", "INDIAVIX"})
INDEX_NAME_ALIASES = {"NIFTY 50": "NIFTY50", "INDIA VIX": "INDIAVIX"}

TERMINAL_FILE_COLUMNS: dict[str, list[str]] = {
    "nse_participant_vol": ["date", "client_type", *PARTICIPANT_COLS, "first_seen_at"],
    "nse_fii_stats": ["date", "instrument", "buy_contracts", "buy_cr", "sell_contracts", "sell_cr", "oi_contracts", "oi_cr", "first_seen_at"],
    "nse_mwpl_clients": ["date", "symbol", "client_rank", "pct_mwpl", "first_seen_at"],
}
TERMINAL_FILE_CASTS: dict[str, dict[str, str]] = {
    "nse_participant_vol": {"date": "DATE", "first_seen_at": "TIMESTAMP", **{c: "BIGINT" for c in PARTICIPANT_COLS}},
    "nse_fii_stats": {"date": "DATE", "first_seen_at": "TIMESTAMP", "buy_contracts": "BIGINT", "sell_contracts": "BIGINT", "oi_contracts": "BIGINT",
                      "buy_cr": "DOUBLE", "sell_cr": "DOUBLE", "oi_cr": "DOUBLE"},
    "nse_mwpl_clients": {"date": "DATE", "first_seen_at": "TIMESTAMP", "client_rank": "INTEGER", "pct_mwpl": "DOUBLE"},
}


def _clean_header(cols: list[str]) -> list[str]:
    return [_re.sub(r"\s+", " ", str(c)).strip() for c in cols]


def parse_fovolt(blob: bytes, day: date) -> pd.DataFrame:
    """FOVOLT_DDMMYYYY.csv → nse_fo_volt rows (positional: NSE's header carries the formulas as column names)."""
    df = pd.read_csv(io.BytesIO(blob), dtype=str, skipinitialspace=True)
    if df.shape[1] < 14:
        raise ValueError(f"FOVOLT layout changed: {df.shape[1]} columns")
    cols = list(df.columns)
    out = pd.DataFrame({
        "date": day, "symbol": df[cols[1]].str.strip(),
        "close": _num(df[cols[2]]), "prev_close": _num(df[cols[3]]), "log_return": _num(df[cols[4]]),
        "ewma_daily_vol": _num(df[cols[6]]), "ann_vol": _num(df[cols[7]]),
        "fut_vol": _num(df[cols[12]]), "fut_ann_vol": _num(df[cols[13]]),
        "applicable_ann_vol": _num(df[cols[15]]) if len(cols) > 15 else None,
    })
    return out.dropna(subset=["symbol"]).reset_index(drop=True)


def parse_contract_delta(blob: bytes, day: date) -> pd.DataFrame:
    """Contract_Delta_DDMMYYYY.csv → nse_contract_delta rows (options only; FF rows are futures with delta 1)."""
    df = pd.read_csv(io.BytesIO(blob), dtype=str)
    df.columns = _clean_header(list(df.columns))
    need = {"Symbol", "Expiry day", "Strike Price", "Option Type", "Delta Factor"}
    if not need <= set(df.columns):
        raise ValueError(f"Contract_Delta layout changed: {list(df.columns)[:6]}")
    opt = df["Option Type"].str.strip().isin(["CE", "PE"])
    d = df[opt]
    out = pd.DataFrame({
        "date": day, "symbol": d["Symbol"].str.strip(),
        "expiry": pd.to_datetime(d["Expiry day"].str.strip(), format="%d-%m-%Y", errors="coerce").dt.date,
        "strike": _num(d["Strike Price"]), "opt_type": d["Option Type"].str.strip(), "delta_factor": _num(d["Delta Factor"]),
    })
    return out.dropna(subset=["symbol", "expiry", "strike"]).reset_index(drop=True)


def parse_combined_oi_deleq(blob: bytes, day: date) -> pd.DataFrame:
    """combineoi_deleq_DDMMYYYY.csv → nse_combined_oi rows (notional OI + portfolio-wise futures-equivalent OI)."""
    df = pd.read_csv(io.BytesIO(blob), dtype=str)
    df.columns = _clean_header(list(df.columns))
    sym = next((c for c in df.columns if c.lower() in ("symbol", "nse symbol")), None)
    notional = next((c for c in df.columns if "notional" in c.lower()), None)
    deleq = next((c for c in df.columns if "futures equivalent" in c.lower() or "delta" in c.lower()), None)
    if sym is None or deleq is None:
        raise ValueError(f"combineoi_deleq layout changed: {list(df.columns)}")
    out = pd.DataFrame({"date": day, "symbol": df[sym].str.strip(), "isin": df["ISIN"].str.strip() if "ISIN" in df.columns else None,
                        "notional_oi": _num(df[notional]) if notional else None, "fut_equiv_oi": _num(df[deleq])})
    return out.dropna(subset=["symbol"]).reset_index(drop=True)


def parse_combined_oi_zip(blob: bytes, day: date) -> pd.DataFrame:
    """combineoi_DDMMYYYY.zip (MWPL, open interest, next-day limit) → nse_combined_oi columns mwpl / oi / limit_next_day."""
    df = pd.read_csv(io.BytesIO(_unzip_first(blob)), dtype=str)
    df.columns = _clean_header(list(df.columns))
    sym = next((c for c in df.columns if c.lower() in ("symbol", "nse symbol")), None)
    mwpl = next((c for c in df.columns if c.lower() == "mwpl"), None)
    oi = next((c for c in df.columns if c.lower() in ("open interest", "oi")), None)
    lim = next((c for c in df.columns if "limit" in c.lower()), None)
    if sym is None or mwpl is None:
        raise ValueError(f"combineoi layout changed: {list(df.columns)}")
    out = pd.DataFrame({"date": day, "symbol": df[sym].str.strip(), "isin": df["ISIN"].str.strip() if "ISIN" in df.columns else None,
                        "mwpl": _num(df[mwpl]), "oi": _num(df[oi]) if oi else None, "limit_next_day": _num(df[lim]) if lim else None})
    return out.dropna(subset=["symbol"]).reset_index(drop=True)


def index_symbol(name: str) -> str:
    """'Nifty 50' → NIFTY50, 'India VIX' → INDIAVIX, 'Nifty Bank' → NIFTYBANK (the market_index_daily spelling)."""
    up = _re.sub(r"\s+", " ", str(name)).strip().upper()
    return INDEX_NAME_ALIASES.get(up, up.replace(" ", "").replace("&", "").replace("-", ""))


def parse_index_close_all(blob: bytes, day: date) -> pd.DataFrame:
    """ind_close_all_DDMMYYYY.csv → one row per index: symbol (NSE name upper-cased), OHLC, pe, pb, dy."""
    df = pd.read_csv(io.BytesIO(blob), dtype=str)
    df.columns = _clean_header(list(df.columns))
    if "Index Name" not in df.columns or "Closing Index Value" not in df.columns:
        raise ValueError(f"ind_close_all layout changed: {list(df.columns)[:5]}")
    out = pd.DataFrame({
        "symbol": df["Index Name"].astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True), "date": day,
        "open": _num(df["Open Index Value"]), "high": _num(df["High Index Value"]), "low": _num(df["Low Index Value"]),
        "close": _num(df["Closing Index Value"]), "prev_close_pts": _num(df["Points Change"]) if "Points Change" in df.columns else None,
        "pe": _num(df["P/E"]) if "P/E" in df.columns else None, "pb": _num(df["P/B"]) if "P/B" in df.columns else None,
        "dy": _num(df["Div Yield"]) if "Div Yield" in df.columns else None,
    })
    out = out.dropna(subset=["close"]).reset_index(drop=True)
    file_day = pd.to_datetime(df["Index Date"].iloc[0].strip(), format="%d-%m-%Y", errors="coerce") if "Index Date" in df.columns and len(df) else None
    if file_day is not None and not pd.isna(file_day) and file_day.date() != day:
        raise ValueError(f"ind_close_all file is dated {file_day.date()}, expected {day}")
    return out


def parse_vix_history(blob: bytes) -> pd.DataFrame:
    """historicalOR/vixhistory JSON → vix_daily rows (source nse_vixhistory)."""
    payload = _json.loads(blob.decode("utf-8", "replace"))
    rows = payload.get("data") if isinstance(payload, dict) else payload
    out = []
    for r in rows or []:
        try:
            d = _datetime.strptime(str(r["EOD_TIMESTAMP"]).strip(), "%d-%b-%Y").date()  # noqa: DTZ007 — a calendar date
        except (KeyError, ValueError):
            continue
        out.append({"date": d, "open": r.get("EOD_OPEN_INDEX_VAL"), "high": r.get("EOD_HIGH_INDEX_VAL"), "low": r.get("EOD_LOW_INDEX_VAL"),
                    "close": r.get("EOD_CLOSE_INDEX_VAL"), "prev_close": r.get("EOD_PREV_CLOSE")})
    df = pd.DataFrame(out, columns=["date", "open", "high", "low", "close", "prev_close"])
    for c in ("open", "high", "low", "close", "prev_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"]).reset_index(drop=True)


def parse_participant_vol(blob: bytes, day: date) -> pd.DataFrame:
    """fao_participant_vol_DDMMYYYY.csv: same layout as the OI file (title line, then Client Type + 14 columns)."""
    return parse_participant_oi(blob, day)


def parse_fii_stats(blob: bytes, day: date) -> pd.DataFrame:
    """fii_stats_DD-Mon-YYYY.xls → one row per instrument line (INDEX FUTURES, NIFTY FUTURES, INDEX OPTIONS, …)."""
    import xlrd

    book = xlrd.open_workbook(file_contents=blob)
    sh = book.sheet_by_index(0)
    out = []
    for i in range(sh.nrows):
        vals = [sh.cell_value(i, c) for c in range(min(sh.ncols, 7))]
        name = str(vals[0]).strip()
        if not name or len(vals) < 7 or name.upper().startswith("FII DERIVATIVES"):
            continue
        nums = [_num(pd.Series([v])).iloc[0] for v in vals[1:7]]
        if all(pd.isna(x) for x in nums):
            continue
        out.append({"date": day, "instrument": name.upper(), "buy_contracts": nums[0], "buy_cr": nums[1], "sell_contracts": nums[2],
                    "sell_cr": nums[3], "oi_contracts": nums[4], "oi_cr": nums[5]})
    return pd.DataFrame(out, columns=TERMINAL_FILE_COLUMNS["nse_fii_stats"][:-1])


def parse_mwpl_clients(blob: bytes, day: date) -> pd.DataFrame:
    """mwpl_cli_DDMMYYYY.xls (positions ≥ 3 % of MWPL per client, T−1) → (date, symbol, client_rank, pct_mwpl) rows."""
    import xlrd

    book = xlrd.open_workbook(file_contents=blob)
    sh = book.sheet_by_index(0)
    out = []
    for i in range(sh.nrows):
        vals = [sh.cell_value(i, c) for c in range(sh.ncols)]
        if len(vals) < 3 or not isinstance(vals[0], float):
            continue
        symbol = str(vals[1]).strip()
        for rank, v in enumerate(vals[2:], 1):
            x = _num(pd.Series([v])).iloc[0]
            if not pd.isna(x):
                out.append({"date": day, "symbol": symbol, "client_rank": rank, "pct_mwpl": float(x)})
    return pd.DataFrame(out, columns=TERMINAL_FILE_COLUMNS["nse_mwpl_clients"][:-1])


def parse_secban(blob: bytes) -> list[str]:
    """fo_secban_DDMMYYYY.csv (named for the next session) → the banned symbols."""
    out = []
    for line in blob.decode("utf-8", "replace").splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            out.append(parts[1])
    return out


# ── the ingest table: dataset → (url, parser, writer) ─────────────────────────────────────────────────────────────

def _fo_iv_tables() -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    from fo_iv.schema import CASTS as C
    from fo_iv.schema import COLUMNS as K
    return K, C


def _write_table(store: _Any, table: str, df: pd.DataFrame, now: _datetime) -> int:
    from data_health import db as tdb

    if df is None or df.empty:
        return 0
    cols_fo, casts_fo = _fo_iv_tables()
    cols = cols_fo.get(table) or TERMINAL_FILE_COLUMNS[table]
    casts = casts_fo.get(table) or TERMINAL_FILE_CASTS.get(table, {})
    frame = df.copy()
    frame["first_seen_at"] = now
    return tdb.upsert(store, table, frame, cols, casts)


def write_index_close_all(store: _Any, parsed: pd.DataFrame, day: date, now: _datetime, *, include_desk_series: bool = False) -> dict[str, int]:
    """index_ohlc_daily (every index) + vix_daily (the India VIX row) + market_index_daily for every index EXCEPT the Desk's
    NIFTY50 / INDIAVIX rows (O-T9 unanswered → default: never touch a Desk input)."""
    from data_health import db as tdb

    ohlc = parsed[["symbol", "date", "open", "high", "low", "close"]].copy()
    ohlc["source"] = "nse_daily_file"
    n_ohlc = _write_table(store, "index_ohlc_daily", ohlc, now)
    vix_row = parsed[parsed["symbol"] == "INDIA VIX"]
    n_vix = 0
    if not vix_row.empty:
        v = vix_row.iloc[0]
        prev = float(v["close"]) - float(v["prev_close_pts"]) if v.get("prev_close_pts") is not None and not pd.isna(v.get("prev_close_pts")) else None
        n_vix = _write_table(store, "vix_daily", pd.DataFrame([{"date": day, "open": v["open"], "high": v["high"], "low": v["low"], "close": v["close"],
                                                                 "prev_close": prev, "source": "nse_daily_file"}]), now)
    mid = pd.DataFrame({"symbol": parsed["symbol"].map(index_symbol), "date": day, "close": parsed["close"], "source": "nse_daily_file"})
    if not include_desk_series:
        mid = mid[~mid["symbol"].isin(DESK_INDEX_SYMBOLS)]
    n_mid = tdb.upsert(store, "market_index_daily", mid, ["symbol", "date", "close", "source"], {"date": "DATE", "close": "DOUBLE"})
    return {"index_ohlc_daily": n_ohlc, "vix_daily": n_vix, "market_index_daily": n_mid}


TERMINAL_DATASETS: dict[str, dict[str, _Any]] = {
    "nse_fo_volt": {"url": FOVOLT_URL, "parse": parse_fovolt, "table": "nse_fo_volt", "folder": "fovolt"},
    "nse_contract_delta": {"url": CONTRACT_DELTA_URL, "parse": parse_contract_delta, "table": "nse_contract_delta", "folder": "contract_delta"},
    "nse_combined_oi": {"url": COMBINED_OI_DELEQ_URL, "parse": parse_combined_oi_deleq, "table": "nse_combined_oi", "folder": "combined_oi"},
    "nse_combined_oi_zip": {"url": COMBINED_OI_ZIP_URL, "parse": parse_combined_oi_zip, "table": "nse_combined_oi", "folder": "combined_oi"},
    "index_ohlc_daily": {"url": INDEX_CLOSE_URL, "parse": parse_index_close_all, "table": "__index_close_all__", "folder": "indices"},
    "nse_participant_vol": {"url": PARTICIPANT_VOL_URL, "parse": parse_participant_vol, "table": "nse_participant_vol", "folder": "participant_vol"},
    "nse_fii_stats": {"url": FII_STATS_URL, "parse": parse_fii_stats, "table": "nse_fii_stats", "folder": "fii_stats"},
    "nse_mwpl_clients": {"url": MWPL_CLI_URL, "parse": parse_mwpl_clients, "table": "nse_mwpl_clients", "folder": "mwpl_cli", "t_minus": 1},
}
TERMINAL_DATASET_NAMES = tuple(TERMINAL_DATASETS)


def ingest_file(store: _Any, http: _Any, dataset: str, day: date, cache_root: Path, *, revalidate: bool = False,
                now: Optional[_datetime] = None) -> dict:
    """Fetch (or revalidate) one dataset for one session through ingest_log, parse, upsert. Never raises on a bad file."""
    from data_health import db as tdb
    from data_health import ingest_log

    spec = TERMINAL_DATASETS[dataset]
    now = now or tdb.utcnow()
    url = spec["url"].format(d=day)
    f = ingest_log.fetch_logged(store, http, dataset, day, url, cache_root=cache_root / "nse_archive", cache_name=None, revalidate=revalidate, now=now)
    out: dict[str, _Any] = {"dataset": dataset, "date": day.isoformat(), "status": f.status, "revision": f.revision, "rows": 0}
    if not f.ok and not (f.status == "not_modified" and f.body is not None):
        return out
    if f.status == "not_modified":
        out["rows"] = 0
        return out
    try:
        parsed = spec["parse"](f.body, day)
        if spec["table"] == "__index_close_all__":
            written = write_index_close_all(store, parsed, day, now)
            out["rows"] = sum(written.values())
            out["tables"] = written
        else:
            out["rows"] = _write_table(store, spec["table"], parsed, now)
    except Exception as exc:  # noqa: BLE001 — one bad file never stops the pass
        out["status"] = "parse_error"
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        logger.warning("nse_files.parse_failed", dataset=dataset, date=day.isoformat(), error=out["error"])
    return out


def prev_weekdays(d: date, n: int) -> date:
    """``d`` stepped back ``n`` weekdays (weekends skipped). A T−1 file (``mwpl_cli``, named for the session it describes and
    published the next day) requested on Monday is FRIDAY's, never Sunday's — the calendar-day step left every Friday's
    file unfetched. An NSE holiday in between is a cheap 404 (``missing``), never a wrong file."""
    out = d
    for _ in range(max(0, n)):
        out -= timedelta(days=1)
        while out.weekday() >= 5:
            out -= timedelta(days=1)
    return out


def ingest_files(store: _Any, http: _Any, datasets: list[str], start: date, end: date, cache_root: Path, *, revalidate: bool = False,
                 progress: Optional[Callable] = None, now: Optional[_datetime] = None, skip_weekends: bool = True) -> dict:
    """Every dataset for every day in [start, end]; weekends skipped unless asked (special sessions are rare and 404 cheaply)."""
    days = [d for d in _days(start, end) if not skip_weekends or d.weekday() < 5]
    out: dict[str, _Any] = {"from": start.isoformat(), "to": end.isoformat(), "datasets": {}, "rows_total": 0}
    total = len(days) * len(datasets)
    i = 0
    for ds in datasets:
        if ds not in TERMINAL_DATASETS:
            out["datasets"][ds] = {"status": "unknown"}
            continue
        res = []
        for d in days:
            file_day = prev_weekdays(d, int(TERMINAL_DATASETS[ds].get("t_minus", 0)))
            r = ingest_file(store, http, ds, file_day, cache_root, revalidate=revalidate, now=now)
            res.append(r)
            out["rows_total"] += int(r.get("rows") or 0)
            i += 1
            if progress:
                progress(i, total)
        out["datasets"][ds] = {"days": len(res), "rows": sum(int(r.get("rows") or 0) for r in res),
                               "statuses": {s: sum(1 for r in res if r["status"] == s) for s in {r["status"] for r in res}},
                               "errors": [r for r in res if r.get("error")][:10]}
    return out


def revise_bhavcopy(store: _Any, http: _Any, day: date, cache_root: Path, *, now: _datetime | None = None) -> dict:
    """The 22:45 pass (Wave 0 0.5; PLAN §0.3 as amended 5 Nov 2026): re-fetch the equity bhavcopy with If-Modified-Since
    (from the 18:30 sighting's ``ingest_log`` row, written by ``bhavcopy.stamp_first_sighting``). ``cache_root`` is the
    18:30 ingest's own cache (``data/nse_bhavcopy``). NSE's 22:05 re-publication (a new sha256) is

    * archived BESIDE the first copy as ``sec_bhavdata_full_YYYYMMDD.rN.csv.gz`` — the first copy is never overwritten;
    * re-upserted into ``nse_bhavcopy`` (the table holds the latest publication) with ``release_at`` = the publisher's
      ``Last-Modified`` (RFC 1123 GMT → UTC, stored UTC-naive like every ``*_at``) and ``first_seen_at`` = the FIRST sighting
      kept (the upsert replaces whole rows, so it is restored, never re-stamped with the revision's fetch time);
    * a revision row in ``ingest_log`` (revision + 1).

    304 / same sha256 / the same bytes as the cached copy cost nothing (``not_modified``). A day the 18:30 ingest never
    stored (an outage) is a first sighting here: the body becomes the first copy on disk and both stamps are set. A file
    carrying another session's rows is refused (``date_mismatch``), as the 18:30 ingest refuses it."""
    import gzip as _gzip
    import hashlib as _hashlib

    import bhavcopy as bc
    from data_health import db as tdb
    from data_health import ingest_log

    now = now or tdb.utcnow()
    url = bc.url_for(day)
    first = bc.cache_path(cache_root, day)
    prior = tdb.scalar(store, "SELECT MIN(first_seen_at) FROM nse_bhavcopy WHERE date = ?", [day])
    prior_seen = None if prior is None or pd.isna(prior) else pd.Timestamp(prior).to_pydatetime()
    f = ingest_log.fetch_logged(store, http, "nse_bhavcopy", day, url, cache_root=None, revalidate=True, now=now)
    out: dict[str, _Any] = {"date": day.isoformat(), "status": f.status, "revision": f.revision, "rows": 0}
    blob = f.body
    if blob is None or f.status not in ("revised", "downloaded"):
        return out
    text = blob.decode("utf-8", "replace") if blob[:2] != b"PK" else (bc._old_zip_to_csv(blob) or "")
    if not text.strip():
        out["status"] = "parse_error"
        return out
    try:
        df = bc.parse_bhavcopy(text)
    except Exception as exc:  # noqa: BLE001
        out["status"] = "parse_error"
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    file_days = {d for d in df["date"].dropna().unique()}
    if file_days and file_days != {day}:
        out["status"] = "date_mismatch"
        out["file_dates"] = sorted(str(d) for d in file_days)[:3]
        return out
    release = bc.utc_naive(bc.parse_http_date(f.last_modified))
    out["release_at_source"] = "last_modified" if release is not None else "fetch_time"
    encoded = text.encode("utf-8")
    if first.exists():
        cached = _gzip.decompress(bc.latest_cached_path(cache_root, day).read_bytes())
        first_seen = prior_seen or _datetime.fromtimestamp(first.stat().st_mtime, tz=_timezone.utc).replace(tzinfo=None, microsecond=0)
        if cached == encoded or _hashlib.sha256(cached).hexdigest() == f.sha256:
            # the copy we already hold (a day stored before the 18:30 sighting was logged): not a revision
            tdb.execute(store, "UPDATE nse_bhavcopy SET first_seen_at = COALESCE(first_seen_at, ?), release_at = COALESCE(release_at, ?) "
                               "WHERE date = ?", [first_seen, release, day])
            out["status"] = "not_modified"
            return out
        rev_n = max(int(f.revision), len(bc.revision_paths(cache_root, day)) + 1)
        target = bc.revision_path(cache_root, day, rev_n)
        out["status"], out["revision"] = "revised", rev_n
    else:
        first_seen = prior_seen or now
        target = first
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(_gzip.compress(encoded))
    tmp.replace(target)
    out["archived"] = str(target.relative_to(cache_root))
    try:
        out["rows"] = int(store.upsert_bhavcopy(df))
        tdb.execute(store, "UPDATE nse_bhavcopy SET first_seen_at = ?, release_at = ? WHERE date = ?", [first_seen, release or now, day])
    except Exception as exc:  # noqa: BLE001
        out["status"] = "parse_error"
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def ingest_vix_history(store: _Any, http: _Any, start: date, end: date, *, now: Optional[_datetime] = None, sleep_s: float = 2.0) -> dict:
    """One-off backfill of vix_daily from NSE's vixhistory API (≤ 1 year per call, paced 2 s; cookie-primed browser session).
    Rows from the daily file (source nse_daily_file) are never overwritten: the API fills only the days that are missing."""
    from data_health import db as tdb

    now = now or tdb.utcnow()
    out: dict[str, _Any] = {"calls": 0, "rows": 0, "errors": []}
    cur = start
    try:
        http.get(f"{API.rsplit('/api', 1)[0]}/", headers={"Accept": "text/html,application/xhtml+xml"})   # cookie prime on www.nseindia.com
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"prime: {type(exc).__name__}")
    while cur <= end:
        nxt = min(end, cur + timedelta(days=360))
        url = VIX_HISTORY_URL.format(start=cur, end=nxt)
        try:
            r = http.get(url, headers={"Accept": "application/json", "Referer": "https://www.nseindia.com/reports-indices-historical-vix"})
            out["calls"] += 1
            if r.status_code != 200:
                out["errors"].append(f"{cur}: HTTP {r.status_code}")
                break
            df = parse_vix_history(r.content)
            have = tdb.query_df(store, "SELECT date FROM vix_daily WHERE date >= ? AND date <= ?", [cur, nxt])
            had = {tdb.to_date(v) for v in have["date"]}
            df = df[~df["date"].isin(had)]
            df["source"] = "nse_vixhistory"
            out["rows"] += _write_table(store, "vix_daily", df, now)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{cur}: {type(exc).__name__}: {str(exc)[:120]}")
            break
        cur = nxt + timedelta(days=1)
        if cur <= end:
            time.sleep(sleep_s)
    return out
