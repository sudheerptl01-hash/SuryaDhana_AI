"""``ingest_log`` (Wave 0 0.5): one row per file fetch with ``url``, ``Last-Modified``, ``ETag``, ``sha256``, row count and
status; a conditional re-fetch that returns a changed body writes a *revision* row (``revision + 1``), an unchanged body
(304, or 200 with the same sha256) writes ``not_modified`` and costs nothing downstream.

``fetch_logged`` is the one helper every new file ingest uses (``nse_positions.py`` FOVOLT / Contract_Delta / combined OI /
index file, ``index_drivers.ingest`` top-10 / constituents): cache on disk under ``cache_root``, ``If-Modified-Since`` from
the last logged ``Last-Modified``, the sha256 dedupe, the log row. It never decides *what* to parse — callers do.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_health import db
from data_health.schema import CASTS, COLUMNS

STATUSES = ("downloaded", "cached", "not_modified", "revised", "missing", "error")


@dataclass
class Fetched:
    dataset: str
    day: date
    url: str
    status: str                       # one of STATUSES
    body: bytes | None
    sha256: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    revision: int = 0
    note: str | None = None
    cached_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.body is not None and self.status in ("downloaded", "cached", "revised")


def sha256_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def latest(store: Any, dataset: str, day: date) -> dict[str, Any] | None:
    """The most recent log row for (dataset, day), or None."""
    df = db.query_df(store, """SELECT dataset, date, url, fetched_at, last_modified, etag, sha256, bytes, rows, status, revision, note
                               FROM ingest_log WHERE dataset = ? AND date = ? ORDER BY fetched_at DESC LIMIT 1""", [dataset, day])
    if df.empty:
        return None
    rec = df.iloc[0].to_dict()
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in rec.items()}


def latest_success(store: Any, dataset: str, day: date) -> dict[str, Any] | None:
    df = db.query_df(store, """SELECT sha256, last_modified, etag, revision, fetched_at FROM ingest_log
                               WHERE dataset = ? AND date = ? AND status IN ('downloaded', 'cached', 'revised')
                               ORDER BY fetched_at DESC LIMIT 1""", [dataset, day])
    if df.empty:
        return None
    rec = df.iloc[0].to_dict()
    return {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in rec.items()}


def record(store: Any, dataset: str, day: date, url: str, *, status: str, sha256: str | None = None, nbytes: int | None = None,
           rows: int | None = None, last_modified: str | None = None, etag: str | None = None, revision: int = 0,
           note: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Write one log row; ``fetched_at`` is bumped by a second when a row for the same instant already exists."""
    assert status in STATUSES, status
    at = now or db.utcnow()
    while db.scalar(store, "SELECT COUNT(*) FROM ingest_log WHERE dataset = ? AND date = ? AND fetched_at = ?", [dataset, day, at]):
        at = at.replace(microsecond=0) + pd.Timedelta(seconds=1).to_pytimedelta()
    row = {"dataset": dataset, "date": day, "url": url, "fetched_at": at, "last_modified": last_modified, "etag": etag,
           "sha256": sha256, "bytes": nbytes, "rows": rows, "status": status, "revision": revision, "note": note}
    db.upsert(store, "ingest_log", pd.DataFrame([row]), COLUMNS["ingest_log"], CASTS["ingest_log"])
    return row


def set_rows(store: Any, dataset: str, day: date, fetched_at: datetime, rows: int) -> None:
    db.execute(store, "UPDATE ingest_log SET rows = ? WHERE dataset = ? AND date = ? AND fetched_at = ?", [rows, dataset, day, fetched_at])


def fetch_logged(store: Any, http: Any, dataset: str, day: date, url: str, *, cache_root: Path | None = None,
                 cache_name: str | None = None, revalidate: bool = False, now: datetime | None = None,
                 headers: dict[str, str] | None = None, timeout_s: float | None = None) -> Fetched:
    """Fetch ``url`` for (dataset, day) with the cache, the conditional GET and the log row.

    * cached on disk and ``revalidate`` is False → ``cached`` (no request, logged once per process state: a cached row is
      written only when no success row exists yet, so a backfill re-run adds nothing).
    * ``revalidate`` (the 22:45 pass, Wave 0 0.5) → ``If-Modified-Since`` from the last success row's ``Last-Modified``;
      304 → ``not_modified``; 200 with the same sha256 → ``not_modified``; 200 with a new sha256 → ``revised`` (revision + 1)
      and the cache file is replaced.
    * HTTP 404 → ``missing``; anything else / a transport error → ``error`` (the message in ``note``).
    """
    cache = (cache_root / dataset / f"{day:%Y}" / (cache_name or url.rsplit("/", 1)[-1])) if cache_root else None
    prev = latest_success(store, dataset, day)
    if cache is not None and cache.exists() and not revalidate:
        body = cache.read_bytes()
        digest = sha256_of(body)
        if prev is None:
            record(store, dataset, day, url, status="cached", sha256=digest, nbytes=len(body), last_modified=None, now=now)
        return Fetched(dataset, day, url, "cached", body, digest, prev.get("last_modified") if prev else None, None,
                       int(prev["revision"]) if prev else 0, cached_path=cache)
    hdrs = dict(headers or {})
    if revalidate and prev and prev.get("last_modified"):
        hdrs["If-Modified-Since"] = str(prev["last_modified"])
    try:
        resp = http.get(url, headers=hdrs, timeout_s=timeout_s) if timeout_s else http.get(url, headers=hdrs)
    except Exception as exc:  # noqa: BLE001 — a transport failure is a logged outcome, not a crash
        note = f"{type(exc).__name__}: {str(exc)[:160]}"
        record(store, dataset, day, url, status="error", note=note, now=now)
        return Fetched(dataset, day, url, "error", None, note=note)
    status = int(resp.status_code)
    lm = resp.headers.get("last-modified") if hasattr(resp, "headers") else None
    etag = resp.headers.get("etag") if hasattr(resp, "headers") else None
    if status == 304:
        record(store, dataset, day, url, status="not_modified", last_modified=lm or (prev or {}).get("last_modified"), etag=etag,
               revision=int(prev["revision"]) if prev else 0, now=now)
        cached_body = cache.read_bytes() if cache is not None and cache.exists() else None
        return Fetched(dataset, day, url, "not_modified", cached_body, (prev or {}).get("sha256"), lm, etag, int(prev["revision"]) if prev else 0,
                       cached_path=cache)
    if status == 404:
        record(store, dataset, day, url, status="missing", now=now)
        return Fetched(dataset, day, url, "missing", None)
    body = resp.content
    if status != 200 or not body or body.lstrip()[:1] == b"<":
        note = f"HTTP {status}" if status != 200 else "html body (bot wall or empty)"
        record(store, dataset, day, url, status="error", note=note, now=now)
        return Fetched(dataset, day, url, "error", None, note=note)
    digest = sha256_of(body)
    if prev and prev.get("sha256") == digest:
        record(store, dataset, day, url, status="not_modified", sha256=digest, nbytes=len(body), last_modified=lm, etag=etag,
               revision=int(prev["revision"]), now=now)
        return Fetched(dataset, day, url, "not_modified", body, digest, lm, etag, int(prev["revision"]), cached_path=cache)
    revision = int(prev["revision"]) + 1 if prev else 0
    st = "revised" if prev else "downloaded"
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(cache.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(cache)
    record(store, dataset, day, url, status=st, sha256=digest, nbytes=len(body), last_modified=lm, etag=etag, revision=revision, now=now)
    return Fetched(dataset, day, url, st, body, digest, lm, etag, revision, cached_path=cache)


def recent(store: Any, *, days: int = 7, dataset: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    where = "fetched_at >= CURRENT_TIMESTAMP - INTERVAL (?) DAY" + (" AND dataset = ?" if dataset else "")
    params: list[Any] = [days] + ([dataset] if dataset else [])
    df = db.query_df(store, f"""SELECT dataset, date, url, fetched_at, last_modified, sha256, bytes, rows, status, revision, note
                                FROM ingest_log WHERE {where} ORDER BY fetched_at DESC LIMIT {int(limit)}""", params)
    return db.records(df, ("date",))


def last_fetch_by_dataset(store: Any) -> dict[str, dict[str, Any]]:
    """{dataset: {date, fetched_at, status, revision}} of the newest log row per dataset."""
    df = db.query_df(store, """SELECT dataset, date, fetched_at, status, revision, last_modified FROM ingest_log
                               QUALIFY ROW_NUMBER() OVER (PARTITION BY dataset ORDER BY fetched_at DESC) = 1""")
    return {str(r["dataset"]): r for r in db.records(df, ("date",))}
