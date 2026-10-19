#!/usr/bin/env python3
"""Resume-safe downloader for the P3 external-data stream.

One worker thread per file type (fo, indices, participant), each with exactly
one request in flight; a random 1.0-2.0 s pause between requests of the same
type; on HTTP 403/429/5xx, a connection error or an HTML/garbled 200 body the
worker sleeps 60 s and halves its request rate (the pause range doubles, up to
16x); after 200 consecutive successes the rate is restored by one step.
Files already on disk and valid are skipped; a 404 is recorded in the type's
``_status.jsonl`` and not retried unless ``--retry-missing`` is given.

Usage (from the repo root; nothing is executed from the download folders)::

    python3 -I ml/extdata/download.py --window main
    python3 -I ml/extdata/download.py --window hist      # 2016-10..2021-09
    python3 -I ml/extdata/download.py --lists-only
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import threading
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests  # noqa: E402

from ml.extdata import common as C  # noqa: E402

RETRY_CODES = {403, 429, 500, 502, 503, 504}
MAX_TRIES = 6
BACKOFF_S = 60.0
MAX_MULT = 16.0
RESTORE_AFTER = 200


# --------------------------------------------------------------------------- #
# body validation
# --------------------------------------------------------------------------- #

def _valid_zip(body: bytes) -> bool:
    if not body.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                return False
            with zf.open(names[0]) as fh:
                head = fh.read(400).decode("latin-1", "replace")
        return ("INSTRUMENT" in head) or ("TradDt" in head)
    except zipfile.BadZipFile:
        return False


def _valid_idx(body: bytes) -> bool:
    head = body[:300].decode("latin-1", "replace").lstrip("﻿ \r\n")
    return head.lower().startswith("index name")


def _valid_part(body: bytes) -> bool:
    txt = body[:2000].decode("latin-1", "replace")
    return ("Client Type" in txt) and ("FII" in txt) and ("<html" not in txt.lower())


def _valid_list(body: bytes) -> bool:
    txt = body[:500].decode("latin-1", "replace")
    return ("Symbol" in txt or "SYMBOL" in txt) and ("<html" not in txt.lower())


VALIDATORS = {"fo": _valid_zip, "indices": _valid_idx, "participant": _valid_part,
              "lists": _valid_list}


def valid_file(kind: str, path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 50:
            return False
        return VALIDATORS[kind](path.read_bytes())
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# status bookkeeping
# --------------------------------------------------------------------------- #

def status_path(kind: str) -> Path:
    return {"fo": C.RAW_FO, "indices": C.RAW_IDX, "participant": C.RAW_PART,
            "lists": C.RAW_LISTS}[kind] / "_status.jsonl"


def load_status(kind: str) -> dict[str, dict]:
    p = status_path(kind)
    out: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[rec["file"]] = rec
    return out


_status_lock = threading.Lock()


def append_status(kind: str, rec: dict) -> None:
    rec = dict(rec, ts=datetime.now().isoformat(timespec="seconds"))
    with _status_lock:
        with status_path(kind).open("a") as fh:
            fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------- #
# worker
# --------------------------------------------------------------------------- #

class Worker(threading.Thread):
    def __init__(self, kind: str, jobs: list[tuple[str, str, Path, str]],
                 retry_missing: bool, log):
        super().__init__(name=f"dl-{kind}", daemon=False)
        self.kind, self.jobs, self.retry_missing, self.log = kind, jobs, retry_missing, log
        self.mult = 1.0
        self.streak = 0
        self.sess = requests.Session()
        self.sess.headers.update({"User-Agent": C.USER_AGENT,
                                  "Accept": "*/*",
                                  "Accept-Language": "en-US,en;q=0.9",
                                  "Referer": "https://www.nseindia.com/"})
        self.counts = {"skipped_on_disk": 0, "skipped_404_known": 0, "ok": 0,
                       "404": 0, "failed": 0}

    def _pause(self) -> None:
        time.sleep(random.uniform(1.0, 2.0) * self.mult)

    def _slow_down(self, why: str) -> None:
        self.mult = min(self.mult * 2.0, MAX_MULT)
        self.streak = 0
        self.log.warning("%s: %s -> sleeping %.0f s, pause multiplier now %.0fx",
                         self.kind, why, BACKOFF_S, self.mult)
        time.sleep(BACKOFF_S)

    def fetch(self, d_iso: str, url: str, dest: Path, fmt: str) -> str:
        for attempt in range(1, MAX_TRIES + 1):
            self._pause()
            try:
                r = self.sess.get(url, timeout=60)
                code, body = r.status_code, r.content
            except requests.RequestException as exc:
                self._slow_down(f"{dest.name} connection error {type(exc).__name__}")
                continue
            if code == 404:
                append_status(self.kind, {"date": d_iso, "file": dest.name, "url": url,
                                          "status": "404", "http": 404, "format": fmt})
                self.log.info("%s %s 404", self.kind, dest.name)
                return "404"
            if code in RETRY_CODES:
                self._slow_down(f"{dest.name} HTTP {code} (try {attempt})")
                continue
            if code != 200:
                append_status(self.kind, {"date": d_iso, "file": dest.name, "url": url,
                                          "status": f"http_{code}", "http": code,
                                          "format": fmt})
                self.log.warning("%s %s unexpected HTTP %s", self.kind, dest.name, code)
                return "failed"
            if not VALIDATORS[self.kind](body):
                self._slow_down(f"{dest.name} 200 with invalid body ({len(body)} B, "
                                f"try {attempt})")
                continue
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(body)
            tmp.replace(dest)
            append_status(self.kind, {"date": d_iso, "file": dest.name, "url": url,
                                      "status": "ok", "http": 200, "bytes": len(body),
                                      "format": fmt})
            self.streak += 1
            if self.streak >= RESTORE_AFTER and self.mult > 1.0:
                self.mult = max(1.0, self.mult / 2.0)
                self.streak = 0
                self.log.info("%s: %d clean requests, pause multiplier restored to %.0fx",
                              self.kind, RESTORE_AFTER, self.mult)
            return "ok"
        append_status(self.kind, {"date": d_iso, "file": dest.name, "url": url,
                                  "status": "failed_after_retries", "format": fmt})
        self.log.error("%s %s failed after %d tries", self.kind, dest.name, MAX_TRIES)
        return "failed"

    def run(self) -> None:
        known = load_status(self.kind)
        n = len(self.jobs)
        self.log.info("%s worker start: %d jobs", self.kind, n)
        for i, (d_iso, url, dest, fmt) in enumerate(self.jobs, 1):
            if valid_file(self.kind, dest):
                self.counts["skipped_on_disk"] += 1
                continue
            rec = known.get(dest.name)
            if rec and rec.get("status") == "404" and not self.retry_missing:
                self.counts["skipped_404_known"] += 1
                continue
            res = self.fetch(d_iso, url, dest, fmt)
            self.counts[res if res in self.counts else "failed"] += 1
            if i % 50 == 0:
                self.log.info("%s progress %d/%d %s", self.kind, i, n, self.counts)
        self.log.info("%s worker done: %s", self.kind, self.counts)


# --------------------------------------------------------------------------- #
# job lists
# --------------------------------------------------------------------------- #

def _ordered(days: list[date], stride: int = 25) -> list[date]:
    """A strided first pass (every 25th day: early coverage of both F&O formats
    and all years for parser tests), then the remaining days in order."""
    first = days[::stride]
    seen = set(first)
    return first + [d for d in days if d not in seen]


def build_jobs(days: list[date]) -> dict[str, list]:
    jobs = {"fo": [], "indices": [], "participant": []}
    for d in _ordered(days):
        iso = d.isoformat()
        url, name, fmt = C.fo_url(d)
        jobs["fo"].append((iso, url, C.RAW_FO / name, fmt))
        url, name = C.idx_url(d)
        jobs["indices"].append((iso, url, C.RAW_IDX / name, "csv"))
        url, name = C.part_url(d)
        jobs["participant"].append((iso, url, C.RAW_PART / name, "csv"))
    return jobs


def download_lists(log, force: bool = False) -> dict:
    w = Worker("lists", [], False, log)
    out = {}
    for name, url in C.LIST_FILES.items():
        dest = C.RAW_LISTS / name
        if valid_file("lists", dest) and not force:
            out[name] = "on_disk"
            continue
        out[name] = w.fetch("", url, dest, "csv")
    log.info("lists: %s", out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", choices=["main", "hist"], default="main")
    ap.add_argument("--kinds", default="fo,indices,participant")
    ap.add_argument("--retry-missing", action="store_true")
    ap.add_argument("--lists-only", action="store_true")
    a = ap.parse_args()
    C.ensure_dirs()
    log = C.get_logger("extdata.download")
    random.seed(C.SEED)
    if a.lists_only:
        download_lists(log)
        return
    if a.window == "main":
        download_lists(log)
        days = C.main_sessions()
    else:
        days = C.hist_candidate_days()
    log.info("window=%s days=%d (%s..%s)", a.window, len(days), days[0], days[-1])
    jobs = build_jobs(days)
    workers = [Worker(k, jobs[k], a.retry_missing, log)
               for k in a.kinds.split(",") if k in jobs]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    log.info("window=%s all workers done: %s", a.window,
             {w.kind: w.counts for w in workers})


if __name__ == "__main__":
    main()
