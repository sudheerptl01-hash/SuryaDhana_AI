"""
NSE full bhavcopy ingestion: the official end-of-day record of EVERY security traded
on NSE that day, including ones delisted later, plus deliverable quantity / delivery %.

Why (docs/PRODUCT_STRATEGY.md, Phase A):
  * survivorship-free universe: the Yahoo history only covers today's listed names,
    which overstates momentum/value backtests;
  * delivery % (DELIV_PER): accumulation vs speculative churn, unavailable from Yahoo;
  * PREV_CLOSE on an ex-date is NSE's corporate-action-adjusted previous close, so
    split/bonus factors can be derived even for delisted names (research step).

Source: https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
(published ~16:00–16:30 IST; archive from late 2019). Raw files are cached as gzip
under <data>/nse_bhavcopy/YYYY/ so a re-ingest never re-downloads. Prices are raw
(unadjusted), exactly as NSE published them.

Point-in-time (Terminal v2 PLAN §0.3 as amended 5 Nov 2026, Wave 0 0.5): the first sighting of a day stamps
``first_seen_at`` (our fetch time, UTC-naive like every ``*_at`` column in the store) and ``release_at`` (the publisher's
``Last-Modified``, RFC 1123 GMT → UTC) on its rows and writes an ``ingest_log`` row (url, sha256, Last-Modified), so the
22:45 If-Modified-Since pass (``nse_positions.revise_bhavcopy``) can tell NSE's 22:05 re-publication from the 18:30 copy.
A revision is archived BESIDE the first copy as ``sec_bhavdata_full_YYYYMMDD.rN.csv.gz`` (the first copy is never
overwritten); the table holds the latest publication and a re-ingest from cache reads the newest revision.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import pandas as pd

from shared.logging import get_logger

logger = get_logger(__name__)

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv"
# Before the full bhavcopy existed NSE published the classic CM bhavcopy (zipped, no delivery
# columns). It is converted to the full-bhavcopy layout so everything downstream is identical.
OLD_URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{d:%Y}/{mon}/cm{d:%d}{mon}{d:%Y}bhav.csv.zip"
FULL_FORMAT_START = date(2019, 10, 1)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "text/csv,*/*",
}
ARCHIVE_START = date(2010, 1, 1)
PUBLISH_READY_HOUR_IST = 17          # don't treat today's file as missing before this

COLUMNS = {
    "SYMBOL": "symbol", "SERIES": "series", "DATE1": "date", "PREV_CLOSE": "prev_close",
    "OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low", "LAST_PRICE": "last",
    "CLOSE_PRICE": "close", "AVG_PRICE": "avg_price", "TTL_TRD_QNTY": "volume",
    "TURNOVER_LACS": "turnover_lacs", "NO_OF_TRADES": "trades", "DELIV_QTY": "deliv_qty",
    "DELIV_PER": "deliv_pct",
}


def cache_path(root: Path, day: date) -> Path:
    """The FIRST copy of a day (the 18:30 download); never overwritten by a revision."""
    return root / f"{day:%Y}" / f"sec_bhavdata_full_{day:%Y%m%d}.csv.gz"


_REV = re.compile(r"\.r(\d+)\.csv\.gz$")


def revision_path(root: Path, day: date, revision: int) -> Path:
    """Revision ``revision`` (≥ 1) of a day, archived beside the first copy."""
    return root / f"{day:%Y}" / f"sec_bhavdata_full_{day:%Y%m%d}.r{int(revision)}.csv.gz"


def revision_paths(root: Path, day: date) -> list[Path]:
    """Every archived revision of a day, oldest first."""
    folder = root / f"{day:%Y}"
    found = [(int(m.group(1)), p) for p in folder.glob(f"sec_bhavdata_full_{day:%Y%m%d}.r*.csv.gz") if (m := _REV.search(p.name))]
    return [p for _, p in sorted(found)]


def latest_cached_path(root: Path, day: date) -> Path:
    """The newest copy on disk: the last revision when one exists, else the first copy (which may not exist)."""
    revs = revision_paths(root, day)
    return revs[-1] if revs else cache_path(root, day)


def parse_http_date(value: str | None) -> datetime | None:
    """An HTTP date (``Last-Modified``: RFC 1123, always GMT) → an AWARE UTC datetime; None when absent or unparsable."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(str(value).strip())
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:                     # "-0000" / no zone: RFC 7231 says GMT
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_naive(dt: datetime | None) -> datetime | None:
    """Aware → UTC-naive, the store's convention for every ``*_at`` TIMESTAMP column (never the session's local zone)."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt is not None else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_bhavcopy(text: str) -> pd.DataFrame:
    """NSE CSV → normalised frame. Headers and values carry stray spaces; delivery
    columns are '-' for series without delivery (e.g. intraday-only)."""
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True, dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"unexpected bhavcopy layout, missing {sorted(missing)}")
    df = df[list(COLUMNS)].rename(columns=COLUMNS)
    for c in df.columns:
        df[c] = df[c].str.strip()
    parsed = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    if parsed.isna().any():                   # .xlsx variant stores real dates
        parsed = parsed.fillna(pd.to_datetime(df["date"], errors="coerce"))
    df["date"] = parsed.dt.date
    num = [c for c in df.columns if c not in ("symbol", "series", "date")]
    for c in num:
        df[c] = pd.to_numeric(df[c].replace({"-": None, "": None}), errors="coerce")
    df = df.dropna(subset=["symbol", "series", "close"])
    return df.drop_duplicates(subset=["symbol", "series", "date"], keep="last").reset_index(drop=True)


def _old_zip_to_csv(content: bytes) -> Optional[str]:
    """Classic CM bhavcopy (zip) → full-bhavcopy CSV layout (delivery columns '-')."""
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
    except (zipfile.BadZipFile, IndexError):
        return None
    df = pd.read_csv(io.StringIO(raw), skipinitialspace=True, dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    if not {"SYMBOL", "SERIES", "CLOSE", "PREVCLOSE", "TOTTRDQTY", "TOTTRDVAL", "TIMESTAMP"} <= set(df.columns):
        return None
    qty = pd.to_numeric(df["TOTTRDQTY"], errors="coerce")
    val = pd.to_numeric(df["TOTTRDVAL"], errors="coerce")
    out = pd.DataFrame({
        "SYMBOL": df["SYMBOL"], "SERIES": df["SERIES"], "DATE1": df["TIMESTAMP"].str.strip().str.title(),
        "PREV_CLOSE": df["PREVCLOSE"], "OPEN_PRICE": df["OPEN"], "HIGH_PRICE": df["HIGH"],
        "LOW_PRICE": df["LOW"], "LAST_PRICE": df["LAST"], "CLOSE_PRICE": df["CLOSE"],
        "AVG_PRICE": (val / qty).round(4), "TTL_TRD_QNTY": df["TOTTRDQTY"],
        "TURNOVER_LACS": (val / 1e5).round(4),
        "NO_OF_TRADES": df["TOTALTRADES"] if "TOTALTRADES" in df.columns else "-",
        "DELIV_QTY": "-", "DELIV_PER": "-",
    })
    return out.to_csv(index=False)


def url_for(day: date) -> str:
    if day >= FULL_FORMAT_START:
        return URL.format(d=day)
    return OLD_URL.format(d=day, mon=day.strftime("%b").upper())


def _xlsx_to_csv(content: bytes) -> Optional[str]:
    try:
        df = pd.read_excel(io.BytesIO(content), dtype=str)
    except Exception as exc:                  # openpyxl missing or not a bhavcopy workbook
        logger.warning("bhavcopy xlsx fallback failed", error=str(exc))
        return None
    if "SYMBOL" not in [str(c).strip().upper() for c in df.columns]:
        return None
    return df.to_csv(index=False)


def download_day(day: date, cache_root: Path, client: httpx.Client, retries: int = 3,
                 backoff_s: float = 2.0, meta: dict[str, Any] | None = None) -> tuple[Optional[str], str]:  # noqa: UP045 — legacy return
    """(csv text or None, status) — status: cached | downloaded | missing | error:<msg>.
    'missing' = NSE has no file for the day (holiday / weekend). A cached day reads the newest copy (the last archived
    revision, else the first). ``meta`` (optional, filled in place) receives what the point-in-time stamp needs: url,
    sha256 / bytes of the published body, the publisher's Last-Modified / ETag, or the cached copy's first-sighting time."""
    path = cache_path(cache_root, day)
    if path.exists():
        newest = latest_cached_path(cache_root, day)
        raw = gzip.decompress(newest.read_bytes())
        if meta is not None:
            meta.update(url=url_for(day), status="cached", sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), path=str(newest),
                        first_seen=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(tzinfo=None, microsecond=0))
        return raw.decode("utf-8", "replace"), "cached"
    last_err = ""
    for attempt in range(retries):
        try:
            r = client.get(url_for(day))
            if r.status_code == 404:
                return None, "missing"
            text = None
            if day < FULL_FORMAT_START:
                text = _old_zip_to_csv(r.content) if r.status_code == 200 else None
            elif r.status_code == 200 and r.text.lstrip().upper().startswith("SYMBOL"):
                text = r.text
            elif r.status_code == 200 and r.content[:2] == b"PK":
                text = _xlsx_to_csv(r.content)            # NSE occasionally serves .xlsx under .csv
            if text is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(gzip.compress(text.encode("utf-8")))
                tmp.replace(path)
                if meta is not None:
                    meta.update(url=url_for(day), status="downloaded", sha256=hashlib.sha256(r.content).hexdigest(), bytes=len(r.content),
                                last_modified=r.headers.get("last-modified"), etag=r.headers.get("etag"), path=str(path))
                return text, "downloaded"
            last_err = f"HTTP {r.status_code} (not a bhavcopy CSV)"
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(backoff_s * (2 ** attempt))
    return None, f"error:{last_err}"


@dataclass
class IngestSummary:
    start: str
    end: str
    days_requested: int = 0
    days_loaded: int = 0
    days_cached: int = 0
    days_missing: int = 0          # holidays
    rows_written: int = 0
    failures: list[dict] = field(default_factory=list)
    # days whose file carried ANOTHER session's rows (dropped, cache purged; counted in days_missing)
    date_mismatches: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["failures"] = self.failures[:50]
        d["failure_count"] = len(self.failures)
        return d


def stamp_first_sighting(store: Any, day: date, meta: dict[str, Any], rows: int, *, now: datetime | None = None) -> None:
    """The 18:30 ingest's point-in-time stamp for a day it just wrote: ``first_seen_at`` (kept when already set),
    ``release_at`` = the publisher's Last-Modified (kept when already set; a revision sets its own), and the first
    ``ingest_log`` row (status downloaded / cached, sha256, Last-Modified) unless one exists. Never raises into the ingest."""
    from data_health import db as tdb
    from data_health import ingest_log

    now = now or _utcnow()
    seen = meta.get("first_seen") or now
    release = utc_naive(parse_http_date(meta.get("last_modified")))
    tdb.execute(store, "UPDATE nse_bhavcopy SET first_seen_at = COALESCE(first_seen_at, ?), release_at = COALESCE(release_at, ?) "
                       "WHERE date = ?", [seen, release, day])
    if ingest_log.latest_success(store, "nse_bhavcopy", day) is None:
        ingest_log.record(store, "nse_bhavcopy", day, str(meta.get("url") or url_for(day)), status=str(meta.get("status") or "downloaded"),
                          sha256=meta.get("sha256"), nbytes=meta.get("bytes"), rows=rows, last_modified=meta.get("last_modified"),
                          etag=meta.get("etag"), now=seen if meta.get("status") == "cached" else now)


def ingest_range(store, start: date, end: date, cache_root: Path, progress: Optional[Callable] = None,
                 sleep_s: float = 0.35, client: Optional[httpx.Client] = None,
                 days_filter: str = "all", stamp_pit: bool = True) -> dict:
    """Download (or read from cache) and upsert every day in [start, end].

    Weekends are included by default: NSE holds real weekend sessions (Budget days,
    special/DR sessions, some Muhurat sessions) and the next session's PREV_CLOSE
    refers to them. Ordinary weekends simply 404 ("missing").
    days_filter: "all" | "weekdays" | "weekends" (the last one backfills only weekends).
    stamp_pit: stamp first_seen_at / release_at and the first ingest_log row for every day written
    (``stamp_first_sighting``; a failure there is logged, never fatal to the ingest)."""
    days = [start + timedelta(n) for n in range((end - start).days + 1)]
    if days_filter == "weekdays":
        days = [d for d in days if d.weekday() < 5]
    elif days_filter == "weekends":
        days = [d for d in days if d.weekday() >= 5]
    summary = IngestSummary(start=start.isoformat(), end=end.isoformat(), days_requested=len(days))
    own = client is None
    client = client or httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    try:
        for i, day in enumerate(days, 1):
            meta: dict[str, Any] = {}
            text, status = download_day(day, cache_root, client, meta=meta)
            if status == "missing":
                summary.days_missing += 1
            elif text is None:
                summary.failures.append({"date": day.isoformat(), "error": status})
            else:
                try:
                    df = parse_bhavcopy(text)
                    file_days = {d for d in df["date"].dropna().unique()}
                    if file_days and file_days != {day}:
                        # NSE answered this date with ANOTHER session's file (seen 18 Oct 2026: the
                        # Sunday URL served Friday's rows). Cached under this date it poisons every
                        # later run — the table never advances past the real last session, and the
                        # cache short-circuits the download, so that day's true file is never fetched.
                        # Drop the copy and count the day as missing: a later run retries it.
                        cache_path(cache_root, day).unlink(missing_ok=True)
                        for rev in revision_paths(cache_root, day):
                            rev.unlink(missing_ok=True)
                        summary.days_missing += 1
                        summary.date_mismatches.append(
                            {"requested": day.isoformat(), "file_dates": sorted(str(d) for d in file_days)[:3]})
                        logger.warning("Bhavcopy file date mismatch — dropped", requested=day.isoformat(),
                                       file_dates=sorted(str(d) for d in file_days)[:3])
                    else:
                        written = store.upsert_bhavcopy(df)
                        summary.rows_written += written
                        summary.days_loaded += 1
                        summary.days_cached += status == "cached"
                        if stamp_pit:
                            try:
                                stamp_first_sighting(store, day, meta, int(written))
                            except Exception as exc:  # noqa: BLE001 — the PIT stamp never costs a day's data
                                logger.warning("bhavcopy.pit_stamp_failed", date=day.isoformat(), error=f"{type(exc).__name__}: {exc}")
                except Exception as exc:          # one bad file must not stop the backfill
                    summary.failures.append({"date": day.isoformat(), "error": f"parse: {exc}"})
            if status == "downloaded":
                time.sleep(sleep_s)                # be polite to nsearchives
            if progress:
                progress(i, len(days))
    finally:
        if own:
            client.close()
    logger.info("Bhavcopy ingest done", **{k: v for k, v in summary.as_dict().items() if k != "failures"})
    return summary.as_dict()
