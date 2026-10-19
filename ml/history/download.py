#!/usr/bin/env python3
"""Resume-safe fetcher for the legacy NSE archives (P4 history stream).

For every calendar day in the window it requests the legacy CM bhavcopy zip.
404 means no session. On a 200 that is a genuine session (valid zip, the CSV's
TIMESTAMP equals the requested date, bytes differ from the previous session) it
also fetches the MTO delivery file and the PR bundle for that day.

Politeness: one request in flight, browser User-Agent, random 1.0-2.0 s gap
between requests, 60 s back-off and a halved request rate on 403/429/5xx or a
network error (the rate steps back toward the base after 300 clean requests,
never above it). Files are written atomically, so anything on disk is complete;
every outcome (200 / 404 / echo / error) is appended to manifest.jsonl, which
makes a restart skip work already done.

Usage:  OMP_NUM_THREADS=2 python3 -I ml/history/download.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # noqa: E402

from ml.history.common import (  # noqa: E402
    MANIFEST, OVERLAP_DAYS, RAW_CM, RAW_MTO, RAW_PR, RESULTS, WINDOW_END, WINDOW_START,
    calendar_days, get_logger, local_path, read_manifest, url_for,
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/121.0.0.0 Safari/537.36")
STATUS_PATH = RESULTS / "download_status.json"
ECHO_DIR = RAW_CM / "echo"
log = get_logger("hist.download")


class Fetcher:
    def __init__(self, lo: float = 1.0, hi: float = 2.0):
        self.base = (lo, hi)
        self.lo, self.hi = lo, hi
        self.sess = requests.Session()
        self.sess.headers.update({
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })
        self.clean = 0
        self.n_req = 0
        self.n_backoff = 0
        self._last = 0.0

    def _pace(self) -> None:
        gap = random.uniform(self.lo, self.hi)
        dt = time.monotonic() - self._last
        if dt < gap:
            time.sleep(gap - dt)

    def _slow_down(self, why: str, url: str) -> None:
        self.clean = 0
        self.n_backoff += 1
        self.lo, self.hi = min(self.lo * 2, 16.0), min(self.hi * 2, 32.0)
        log.warning("back-off 60 s after %s on %s; gap now %.1f-%.1f s", why, url, self.lo, self.hi)
        time.sleep(60)

    def get(self, url: str, valid) -> tuple[int, bytes | None, str]:
        """Return (status, body, note). status -1 = gave up after retries."""
        note = ""
        for _attempt in range(1, 7):
            self._pace()
            try:
                r = self.sess.get(url, timeout=60)
                status, body = r.status_code, r.content
            except requests.RequestException as exc:
                status, body, note = -1, None, f"{type(exc).__name__}: {exc}"[:300]
            self._last = time.monotonic()
            self.n_req += 1
            if status == 200:
                ok, why = valid(body)
                if ok:
                    self._clean_step()
                    return 200, body, ""
                note = f"200 with invalid body ({why}, {len(body)} bytes)"
                self._slow_down(note, url)
                continue
            if status == 404 or (400 <= status < 500 and status not in (403, 429)):
                self._clean_step()
                return status, None, ""
            self._slow_down(note or f"HTTP {status}", url)
        return -1, None, note or f"HTTP {status}"

    def _clean_step(self) -> None:
        self.clean += 1
        if self.clean >= 300 and (self.lo, self.hi) != self.base:
            self.lo, self.hi = max(self.base[0], self.lo / 2), max(self.base[1], self.hi / 2)
            self.clean = 0
            log.info("300 clean requests; gap restored one step to %.1f-%.1f s", self.lo, self.hi)


def valid_zip(body: bytes) -> tuple[bool, str]:
    if not body or not body.startswith(b"PK"):
        return False, "not a zip"
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"corrupt member {bad}"
            if not zf.namelist():
                return False, "empty zip"
    except zipfile.BadZipFile as exc:
        return False, f"bad zip: {exc}"
    return True, ""


def valid_text(body: bytes) -> tuple[bool, str]:
    if not body or not body.strip():
        return False, "empty"
    if body.lstrip()[:1] == b"<":
        return False, "html body"
    return True, ""


def cm_timestamp(body: bytes) -> str | None:
    """TIMESTAMP of the first data row of the CM CSV (e.g. '02-JAN-2018')."""
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            with zf.open(name) as fh:
                head = fh.read(4096).decode("latin-1").splitlines()
        cols = [c.strip().upper() for c in head[0].split(",")]
        i = cols.index("TIMESTAMP")
        return head[1].split(",")[i].strip().upper()
    except Exception:  # noqa: BLE001
        return None


def parse_ts(ts: str | None) -> date | None:
    if not ts:
        return None
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(ts.title(), fmt).date()
        except ValueError:
            continue
    return None


def save_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)


def append_manifest(rec: dict) -> None:
    rec["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def run(days: list[date], overlap_first: list[date]) -> None:
    for p in (RAW_CM, RAW_MTO, RAW_PR, ECHO_DIR):
        p.mkdir(parents=True, exist_ok=True)
    man = read_manifest()
    f = Fetcher()
    t0 = time.monotonic()
    stats = {"days_done": 0, "sessions": 0, "no_session": 0, "echo": 0, "errors": 0,
             "mto_404": 0, "pr_404": 0}
    prev_sha: str | None = None
    prev_date: date | None = None
    order = overlap_first + [d for d in days if d not in overlap_first]
    n_total = len(order)
    log.info("download start: %d calendar days (%s .. %s, overlap days first: %s)",
             n_total, days[0], days[-1], [d.isoformat() for d in overlap_first])

    for i, d in enumerate(order, 1):
        iso = d.isoformat()
        chrono = d not in overlap_first
        # ---------------- CM ----------------
        p = local_path("cm", d)
        rec = man.get((iso, "cm"))
        body: bytes | None = None
        if p.exists():
            body = p.read_bytes()
            status = 200
        elif rec and rec.get("status") in (404, "echo", "misdated") or (rec and isinstance(rec.get("status"), int) and 400 <= rec["status"] < 500):
            status = rec["status"]
        else:
            status, body, note = f.get(url_for("cm", d), valid_zip)
            if status == 200:
                ts = cm_timestamp(body)
                tsd = parse_ts(ts)
                h = sha(body)
                if chrono and prev_sha is not None and h == prev_sha:
                    save_atomic(ECHO_DIR / p.name, body)
                    append_manifest({"date": iso, "kind": "cm", "status": "echo", "bytes": len(body),
                                     "sha256": h, "echo_of": prev_date.isoformat(), "csv_timestamp": ts})
                    log.warning("%s cm: byte-identical to %s (mirror echo); not a session", iso, prev_date)
                    status = "echo"
                elif tsd is not None and tsd != d:
                    save_atomic(ECHO_DIR / p.name, body)
                    append_manifest({"date": iso, "kind": "cm", "status": "misdated", "bytes": len(body),
                                     "sha256": h, "csv_timestamp": ts})
                    log.warning("%s cm: file carries TIMESTAMP %s; not a session for this date", iso, ts)
                    status = "misdated"
                else:
                    save_atomic(p, body)
                    append_manifest({"date": iso, "kind": "cm", "status": 200, "bytes": len(body),
                                     "sha256": h, "csv_timestamp": ts,
                                     "file": str(p.relative_to(p.parents[2]))})
            elif status == -1:
                append_manifest({"date": iso, "kind": "cm", "status": "error", "note": note})
                log.error("%s cm: gave up (%s); will retry on the next run", iso, note)
                stats["errors"] += 1
            else:
                append_manifest({"date": iso, "kind": "cm", "status": status})

        if status != 200:
            if status in ("echo", "misdated"):
                stats["echo"] += 1
            elif status != "error" and status != -1:
                stats["no_session"] += 1
            stats["days_done"] += 1
            _status(stats, f, i, n_total, d, t0)
            continue

        stats["sessions"] += 1
        if chrono:
            prev_sha, prev_date = sha(body), d

        # ---------------- MTO + PR ----------------
        for kind, validator in (("mto", valid_text), ("pr", valid_zip)):
            q = local_path(kind, d)
            r2 = man.get((iso, kind))
            if q.exists():
                continue
            if r2 and isinstance(r2.get("status"), int) and 400 <= r2["status"] < 500:
                stats[f"{kind}_404"] += 1
                continue
            st, b2, note = f.get(url_for(kind, d), validator)
            if st == 200:
                save_atomic(q, b2)
                append_manifest({"date": iso, "kind": kind, "status": 200, "bytes": len(b2),
                                 "sha256": sha(b2)})
            elif st == -1:
                append_manifest({"date": iso, "kind": kind, "status": "error", "note": note})
                log.error("%s %s: gave up (%s); will retry on the next run", iso, kind, note)
                stats["errors"] += 1
            else:
                append_manifest({"date": iso, "kind": kind, "status": st})
                stats[f"{kind}_404"] += 1
                log.warning("%s %s: HTTP %s on a session day", iso, kind, st)
        stats["days_done"] += 1
        _status(stats, f, i, n_total, d, t0)

    _status(stats, f, n_total, n_total, order[-1], t0, final=True)
    log.info("download complete: %s; %d requests, %d back-offs", stats, f.n_req, f.n_backoff)


def _status(stats: dict, f: Fetcher, i: int, n: int, d: date, t0: float, final: bool = False) -> None:
    el = time.monotonic() - t0
    if i % 25 == 0 or final:
        log.info("[%d/%d] %s sessions=%d no_session=%d echo=%d errors=%d req=%d gap=%.1f-%.1f elapsed=%.0fs",
                 i, n, d, stats["sessions"], stats["no_session"], stats["echo"], stats["errors"],
                 f.n_req, f.lo, f.hi, el)
    rate = el / max(f.n_req, 1)
    STATUS_PATH.write_text(json.dumps({
        **stats, "position": i, "of": n, "current_date": d.isoformat(), "requests": f.n_req,
        "backoffs": f.n_backoff, "gap_s": [f.lo, f.hi], "elapsed_s": round(el),
        "sec_per_request": round(rate, 2), "final": final,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=WINDOW_START.isoformat())
    ap.add_argument("--end", default=WINDOW_END.isoformat())
    ap.add_argument("--no-overlap", action="store_true", help="skip the overlap days")
    a = ap.parse_args(argv)
    days = calendar_days(date.fromisoformat(a.start), date.fromisoformat(a.end))
    run(days, [] if a.no_overlap else list(OVERLAP_DAYS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
