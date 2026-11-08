"""
SuryaDhana Master Controller — Autonomous IST Market Session Scheduler
Port: 8008  |  Timezone: Asia/Kolkata (IST = UTC+5:30)

Schedule (IST; job ids as registered in lifespan() and shown on SYS). Daily = every day incl. weekends.
  02:15 daily        db_backup_daily          Verified nightly DuckDB + settings-store backup (7 daily + 4 Sundays,
                                              data/backups/duckdb); a missed night is re-run once at start-up; plus the
                                              sha256-verified off-machine copy when OFFSITE_BACKUP_DIR is set (M32)
  08:00 Mon–Fri      icici_session_refresh    ICICI Breeze login (TOTP, unattended); also once at start-up on a
                                              trading morning
  08:30 daily        pre_market_sync          Incremental bar refresh (Yahoo, quality-gated) + freshness check
  08:45 Mon–Fri      gold_preopen_snapshot    MCX gold fair open before the 09:00 open (accuracy log)
  08:50 Mon–Fri      morning_note             Pre-market note (Telegram + Mac notification)
  09:09:30 Mon–Fri   preopen_capture          NSE final pre-open book (F&O and all stocks) → data/nse_archive/preopen
  09:10 Mon–Fri      gold_open_capture        Actual MCX gold open from ICICI (if a session is live)
  09:00–15:45 /15m   intraday_inference       XGBoost → RL cycle (market-hours gate; AUTOPILOT only — dormant)
  09:00–15:59 /1m    price_alerts_check       Price alerts + the typed alert rules (W2-ALERTS' POST /api/alerts/run?dispatch=1;
                                              after each EOD step the stored-series rules again, scope=eod) (Mon–Fri)
  09:00–15:58 /2m    internals_sample         Market internals sample: breadth (Mon–Fri)
  09:00–15:55 /5m    move_alerts              Holdings ±5/10 %, NIFTY vs 200-DMA (Mon–Fri)
  08:00–22:55 /5m    filing_alerts            NSE filings for your stocks (Mon–Sat)
  15:15 daily        eod_rebalancing          Square-off / rebalance (AUTOPILOT only — dormant)
  15:40 Mon–Fri      close_note               Closing note
  18:30 Mon–Fri      eod_data_pipeline        Settled bars + ML dataset build + NSE equity bhavcopy (equity-only since
                                              Terminal v2 0.5: the F&O files land 20:10, the 20:30 pass fetches them)
  19:15 Mon–Fri      index_valuation_daily    Index P/E, P/B, dividend yield history (NSE daily index file)
  19:20 Mon–Fri      shared_snapshot_build    One shared evening DuckDB snapshot for the 19:45/19:50 jobs + backup
  19:30 Mon–Fri      desk_daily               Decision Desk (paper): fills at the open, NAV, month-end brief
  19:45 Mon–Fri      news_track_record_daily  News-scanner track record (reports/news_scanner); WARNING on failure
  19:50 Mon–Fri      alpha_shadow_daily       S1/S1H paper shadow (alpha_lab replay engine; Telegram fills + Friday NAV)
  20:10 Fri          weekly_journal           Week's decision journal → reports/journal/<YYYY-WW>.md + Telegram digest
  20:30 Mon–Fri      nse_positions_catchup    the evening pass: F&O OI, participant OI, deals, MTF files; FII/DII cash;
                                              the NSE evening files (participant volumes, FII stats, MWPL clients); the
                                              20:35 drivers retry when the top-10 file was missing; iv_eod LAST
  20:45 Mon–Fri      results_capture_daily    Results release times (last 3 days)
  21:00 Mon–Fri      daily_wrap               Market wrap → reports/daily_wrap/<date>.md
  23:00 daily        overnight_rl_retrain     RL agent retraining (AUTOPILOT only — dormant)
  Sat 09:00          nse_filings_weekly       Insider trades + shareholding patterns (one request per company)
  Sat 10:00          financials_sweep         FA / RV financials cache
Terminal v2 (reports/terminal_v2/PLAN.md Wave 0 0.5 / 0.9, Wave 1.1 / 1.2 / 1.4 jobs; every one a data-service fetch +
compute or a read of ui-api's /api/data/health, never a restart; TERMINAL_JOBS_ENABLED=0 opts out):
  08:35 Mon–Fri      morning_sweep            anything still missing from last night (amber / red rows of /api/data/health,
                                              light NSE fetches only, ≤ 6) + the DATA digest (one Telegram info line)
  09:20–15:30 /15m   iv_intraday              Breeze chain snapshots through the budget ledger (data-service); skipped
                                              without a live session, past the budget, on holidays; quiet
  19:25 Mon–Fri      index_drivers_daily      NIFTY 50 / NIFTY BANK PIT weights, contributions, fit, driver state (stored
                                              data + 3 small GETs; retry 20:35 in the 20:30 pass if no top-10 file)
  22:45 Mon–Fri      nse_evening_pass         MTF T−1 (22:12), bhavcopy re-publication (22:05, If-Modified-Since →
                                              revision row), evening-file revisions, FII/DII 2nd attempt, results,
                                              iv_eod retry (a miss of its 21:30 SLO = one Telegram info line)
  Sat 03:00          iv_weekly                252-session IV rank / percentile recompute + dataset_catalog check
  hourly :10         data_health_check        /api/data/health transitions → one Telegram line per dataset that moved
  every 60 s         controller_heartbeat     data/.controller_heartbeat.json (downtime detection at the next start)
GOLD program (reports/gold_program/PLAN.md §c.3; every job = data-service POST /jobs/ingest-gold, a fetch into
market.duckdb, never a restart; heavy ones defer past a freeze window they would land in; GOLD_JOBS_ENABLED=0 opts out):
  03:10 Mon–Sat      gold_overnight           Treasury real yields, Yahoo daily bars, CME final VOI, FRED, US calendar
  every 5 min        gold_intraday_bars       COMEX 1-minute bars while Globex trades (DST-aware; maintenance hour skipped)
  06:40 Mon–Sat      gold_morning             ETF holdings, Fed path, GPR (Mon), monthly series that are due
  07:35 / 08:35 M–F  gold_mcx_master          ICICI MCX master (conditional GET) + Zerodha margins → gold_curve, gold_margins
  08:40 Mon–Fri      gold_health_snapshot     gold_health_daily from ui-api /api/gold/health
  09:05 daily        gold_brief_ingest        the automated gold brief (schema-validated, sha256 dedupe)
  09:00–23:00 hourly gold_calendar_refresh    US calendar this week (ForexFactory JSON)
  13:45 Mon–Fri      gold_india_midday        IBJA AM, RBI reference rate
  15:45 / 17:15 M–Sa gold_cme_daily           CME FTP daily volume/OI + product reference
  16:10 Mon–Fri      gold_asia_close          SGE daily + benchmark, SHFE
  18:10 Mon–Fri      gold_india_pm            IBJA PM + the derived India ladder (before the 18:30 window)
  21:30 daily        gold_fred_daily          FRED daily, LBMA/WGC prices, CME EFRP, derived global series
  Sat 02:30→06:30 /h gold_cot_weekly          CFTC COT (four datasets); Mon + Tue 06:30 catch-up for holiday-delayed
                                              releases; Saturday Telegram digest line (context, no direction)
  Mon 12:00 · Fri 18:00 · Sat 10:30 gold_weekly  WGC ETF flows, RBI WSS, LBMA turnover, WGC premiums, FRED weekly
  Sun 04:00          gold_cme_calendar        CME expiry calendar (38 MB, iterparse)
  23:58 Mon–Fri      gold_mcx_close           MCX settlement proxy (Breeze last-30-min VWAP per live contract) + India ladder;
                                              no after-midnight retry (ICICI sessions expire at midnight IST); after
                                              downtime re-run by the start-up catch-up only while a Breeze session is live
  17:10 Mon–Fri      gold_open_capture_evening  the MCX open on morning-closure days (evening session opens 17:00)
  09:35 Mon–Fri      gold_breeze_daily        MCX gold futures daily OHLC / volume / OI per live expiry from Breeze (O-8,
                                              6 Nov 2026) → gold_mcx_daily: the previous session's complete bars; after
                                              downtime re-run by the catch-up only while a Breeze session is live
  dormant (O-8)      gold_mcx_bhavcopy, gold_mcx_category — not registered (GOLD_DORMANT_JOBS)
  The 08:45 gold_preopen_snapshot and 09:10 gold_open_capture skip full and morning-closure MCX holidays (shared/mcx_specs).
One-off at start-up: icici_session_refresh_startup, <job>_catchup (pre-open book, morning note, wrap, the terminal
jobs missed today), startup_catchup (data catch-up after downtime, extended in Terminal v2 0.9 to results release times
with a window of the days down + 3, index valuation, the IV store and drivers with backfill_from, the explicit gap rows
for session-bound captures, the Desk mark and the S1 shadow, and the gold key jobs incl. the Asia-close / morning /
India / health ones; inside the 18:20–21:15 window, since 6 Nov, the EVENING_REPLAY of every evening job whose slot
passed: pipeline, index valuation, snapshot, Desk, S1 shadow, news track record, Friday journal), db_backup_catchup
(today's 02:15 backup missing; never inside the 07:45–09:20 / 18:30–21:15 freeze windows). Each job's last run, status
(error | skipped | no new data | done — M33: "no new data" when its catalogued datasets did not move) and duration
persist in data/.scheduler_history.json, so SYS keeps them across restarts.
One-off PM command (never scheduled): `python scripts/master_controller.py backfill-outage [--execute]` (M31).

Thread-safety model:
  - APScheduler max_instances=1 prevents scheduler-level job overlap
  - asyncio.Lock per job as application-level misfire guard (belt+suspenders)
  - LogRingBuffer and LatencyTracker use threading.Lock for cross-coroutine safety
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time as _time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx
import psutil
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Bootstrap env ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
# shared/ (repo root locally, /app in Docker). Appended so no scripts/ module can be shadowed.
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))
from shared import mcx_specs
from shared.http_guard import install_http_guard
from shared.metrics import install_observability, observe_job

for _candidate in [_ROOT / ".env", Path("/app/.env")]:
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
        break

# ── Constants ──────────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN  = time(9, 15)
MARKET_CLOSE = time(15, 30)

DATA_SVC         = os.getenv("DATA_SERVICE_URL",      "http://data-service:8001")
ML_SVC           = os.getenv("ML_SERVICE_URL",        "http://ml-service:8003")
RL_SVC           = os.getenv("RL_SERVICE_URL",        "http://rl-service:8004")
EXECUTION_SVC    = os.getenv("EXECUTION_SERVICE_URL", "http://execution-service:8006")
UI_API           = os.getenv("UI_API_URL",            "http://ui-api:8000")
RL_TRAINER_PATH  = os.getenv("RL_TRAINER_PATH",       str(_ROOT / "scripts" / "rl_trainer.py"))
PYTHON_BIN       = os.getenv("PYTHON_BIN",            "python")

TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Autopilot state ────────────────────────────────────────────────────────────
class _AutopilotState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Startup state of the TRADING jobs (inference, EOD square-off, RL retrain).
        # Default "on" preserves Docker behaviour; start-local.sh sets AUTOPILOT_DEFAULT=off
        # so a dev machine only runs the data jobs unless autopilot is enabled explicitly.
        self._on = os.getenv("AUTOPILOT_DEFAULT", "on").strip().lower() not in ("0", "off", "false", "no")
        self._toggled_at: str = datetime.now(IST).isoformat()

    @property
    def on(self) -> bool:
        with self._lock:
            return self._on

    def set(self, enabled: bool) -> None:
        with self._lock:
            self._on = enabled
            self._toggled_at = datetime.now(IST).isoformat()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {"enabled": self._on, "toggled_at": self._toggled_at}


_autopilot = _AutopilotState()


# ── Latency tracker ────────────────────────────────────────────────────────────
class LatencyTracker:
    """Per-job execution latency ring-buffer. Thread-safe."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, job_id: str, latency_ms: float, status: str) -> None:
        with self._lock:
            self._records.append({
                "job_id": job_id,
                "latency_ms": round(latency_ms, 2),
                "status": status,
                "ts": datetime.now(IST).isoformat(),
            })

    def stats(self, job_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            records = [r for r in self._records if job_id is None or r["job_id"] == job_id]
        grouped: dict[str, list[float]] = {}
        last_status: dict[str, str] = {}
        last_latency: dict[str, float] = {}
        last_ts: dict[str, str] = {}
        for r in records:
            jid = r["job_id"]
            grouped.setdefault(jid, []).append(r["latency_ms"])
            last_status[jid] = r["status"]
            last_latency[jid] = r["latency_ms"]
            last_ts[jid] = r["ts"]
        return {
            jid: {
                "avg_ms": round(sum(lats) / len(lats), 2),
                "min_ms": round(min(lats), 2),
                "max_ms": round(max(lats), 2),
                "last_ms": last_latency[jid],
                "samples": len(lats),
                "last_status": last_status[jid],
                "last_ts": last_ts[jid],
            }
            for jid, lats in grouped.items()
        }


_latency = LatencyTracker()


# ── Persistent job history (P14: SYS lost every job's last result on each restart) ─────────
SCHEDULER_HISTORY_FILE = _ROOT / "data" / ".scheduler_history.json"


class JobHistory:
    """Last run per job — {job_id: {last_run_ts, last_status, last_ms, runs}} — kept in a small JSON file so
    /api/scheduler/status (SYS) still shows each job's last result after a controller restart.

    Writes are atomic (temp file + os.replace, so a crash never leaves a half-written file) and happen only once
    load() has armed the store at controller start: importing this module (the tests) never touches the real file.
    The file is a few KB (one row per job), so the write on each job finish costs well under a millisecond."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._armed = False
        self._warned = False

    def load(self) -> int:
        """Read the file (absent or unreadable → empty history) and arm saving. Returns the number of jobs."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            jobs = raw.get("jobs") if isinstance(raw, dict) else None
            loaded = {str(k): dict(v) for k, v in (jobs or {}).items() if isinstance(v, dict)}
        except (OSError, ValueError, TypeError, AttributeError):
            loaded = {}
        with self._lock:
            self._jobs = {**loaded, **self._jobs}       # a run recorded before load() (none in practice) wins
            self._armed = True
            return len(self._jobs)

    def record(self, job_id: str, status: str, latency_ms: float, ts: str | None = None) -> None:
        with self._lock:
            try:
                runs = int(self._jobs.get(job_id, {}).get("runs") or 0) + 1
            except (TypeError, ValueError):           # a hand-edited or half-corrupt row: the count starts over
                runs = 1
            self._jobs[job_id] = {"last_run_ts": ts or datetime.now(IST).isoformat(), "last_status": status,
                                  "last_ms": round(latency_ms, 2), "runs": runs}
            if self._armed:
                self._save_locked()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._jobs.get(job_id)
            return dict(row) if row else None

    def _save_locked(self) -> None:
        tmp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"version": 1, "saved_at": datetime.now(IST).isoformat(timespec="seconds"),
                                       "jobs": self._jobs}, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
            self._warned = False
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass                                      # the directory itself is unusable: nothing to clean
            if not self._warned:                          # once per failure streak, not on every job finish
                self._warned = True
                print(f"[WARN]  [scheduler] job history not saved to {self.path}: {exc}", flush=True)


_history = JobHistory(SCHEDULER_HISTORY_FILE)


# ── Log ring buffer with SSE fan-out ──────────────────────────────────────────
class LogRingBuffer:
    """Thread-safe log ring-buffer with asyncio.Queue fan-out for SSE."""

    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._subscribers: list[asyncio.Queue[str]] = []
        self._sub_lock = threading.Lock()

    def _write(self, level: str, job: str, message: str, **extra: Any) -> None:
        payload = {
            "ts": datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S IST"),
            "level": level,
            "job": job,
            "msg": message,
        }
        payload.update({k: str(v) for k, v in extra.items()})
        line = json.dumps(payload)
        with self._lock:
            self._lines.append(line)
        with self._sub_lock:
            dead: list[asyncio.Queue[str]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(line)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def info(self, job: str, msg: str, **extra: Any) -> None:
        self._write("INFO", job, msg, **extra)
        print(f"[INFO]  [{job}] {msg}", flush=True)

    def warning(self, job: str, msg: str, **extra: Any) -> None:
        self._write("WARN", job, msg, **extra)
        print(f"[WARN]  [{job}] {msg}", flush=True)

    def error(self, job: str, msg: str, **extra: Any) -> None:
        self._write("ERROR", job, msg, **extra)
        print(f"[ERROR] [{job}] {msg}", flush=True)

    def tail(self, n: int = 100) -> list[str]:
        with self._lock:
            return list(self._lines)[-n:]

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


_log = LogRingBuffer()


# ── Alert dispatcher (Telegram + Discord) ──────────────────────────────────────
class AlertDispatcher:
    async def _telegram(self, text: str) -> None:
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"})
                # Markdown rejects a stray "_" or "*" (job names, some tickers): resend as plain text rather than lose it
                if r.status_code == 400 and "parse" in r.text.lower():
                    r = await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text.replace("*", "")})
                if r.status_code != 200:
                    _log.error("alerts", f"Telegram rejected the message: HTTP {r.status_code} {r.text[:200]}")
        except Exception as exc:
            _log.error("alerts", f"Telegram failed: {exc}")

    async def _discord(self, text: str) -> None:
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(DISCORD_WEBHOOK_URL, json={"content": text})
        except Exception as exc:
            _log.error("alerts", f"Discord failed: {exc}")

    async def critical(self, title: str, body: str) -> None:
        text = f"🔴 *[CRITICAL]* {title}\n{body}"
        _log.error("alerts", title, body=body)
        await asyncio.gather(self._telegram(text), self._discord(text), return_exceptions=True)

    async def warning(self, title: str, body: str) -> None:
        text = f"🟡 *[WARNING]* {title}\n{body}"
        _log.warning("alerts", title, body=body)
        await asyncio.gather(self._telegram(text), self._discord(text), return_exceptions=True)

    async def info(self, title: str, body: str) -> None:
        text = f"🟢 *[INFO]* {title}\n{body}"
        _log.info("alerts", title, body=body)
        await asyncio.gather(self._telegram(text), self._discord(text), return_exceptions=True)

    async def trade_fill(self, ticker: str, side: str, qty: int, price: float, pnl_pct: Optional[float] = None) -> None:
        body = f"Ticker: {ticker} | {side} {qty} @ ₹{price:.2f}"
        if pnl_pct is not None:
            body += f" | PnL: {pnl_pct:+.2%}"
        await self.info(f"Trade Fill: {ticker}", body)


_alerts = AlertDispatcher()


# ── Per-job asyncio locks (application-level misfire guard) ───────────────────
_job_locks: dict[str, asyncio.Lock] = {}


_HOLIDAYS: dict = {"at": 0.0, "days": {}}


async def _nse_holiday(day: Optional[datetime] = None) -> Optional[str]:
    """Name of today's NSE equity holiday (data-service /db/market-holidays, NSE's holiday master), else None.
    Cached 12 h. If the list can't be read the market is assumed open, so a job never silently stops."""
    if _time.time() - _HOLIDAYS["at"] > 12 * 3600:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(f"{DATA_SVC}/db/market-holidays")
            if r.status_code == 200:
                _HOLIDAYS.update(at=_time.time(), days={h["date"]: h["description"] for h in r.json().get("holidays") or []})
        except Exception:  # noqa: BLE001
            pass
    return _HOLIDAYS["days"].get((day or datetime.now(IST)).date().isoformat())


_HOLIDAY_LOGGED: set[tuple[str, str]] = set()


async def _closed_today(job: str) -> bool:
    """True when NSE is shut today (session jobs would report the last session as today's); logged once per job/day."""
    name = await _nse_holiday()
    if name:
        key = (job, datetime.now(IST).date().isoformat())
        if key not in _HOLIDAY_LOGGED:
            _HOLIDAY_LOGGED.add(key)
            _log.info(job, f"skipped: NSE closed today ({name})")
    return bool(name)


def _get_lock(job_id: str) -> asyncio.Lock:
    if job_id not in _job_locks:
        _job_locks[job_id] = asyncio.Lock()
    return _job_locks[job_id]


# ── Latency context manager ────────────────────────────────────────────────────
# Jobs that catch their own failure (log + alert, no raise) call _mark_failed(JOB) so SYS and the persisted
# history say "error" instead of "done" for that run.
_soft_failed: set[str] = set()
# A run that did nothing on purpose (the dormant legacy engine with AUTOPILOT off) says so instead of "done" (5 Nov review
# m111: "Overnight RL Retraining 0 ms DONE" read as "a model is retrained nightly").
STATUS_SKIPPED = "skipped"
# M33 (5 Nov review): a job that ran but whose catalogued datasets did not move ("gold_preopen_snapshot done at 08:45" while
# gold_preopen_log had been a gap since 30 Oct) reports this, not "done". Judged from data-service's /db/data-health
# (B1: the stored as-of of every catalogued dataset + its last ingest_log fetch) before and after the run.
STATUS_NO_NEW_DATA = "no new data"
_status_marks: dict[str, str] = {}


def _mark_failed(job_id: str) -> None:
    _soft_failed.add(job_id)


def _mark_status(job_id: str, status: str) -> None:
    """This run's status instead of "done" (STATUS_SKIPPED); an error (_mark_failed, an exception) still wins."""
    _status_marks[job_id] = status


JOB_DATASET_CHECK = os.getenv("JOB_DATASET_CHECK", "1") == "1"     # 0: every completed run is "done" again
DATASET_HEALTH_PATH = "/db/data-health"
DATASET_CHECK_TIMEOUT_S = 4.0          # a busy DuckDB (writer in flight) must not hold a job up: no answer = no evidence
DATASET_JOBS_TTL_S = 3600.0            # the set of job ids that own a catalogued dataset, re-read hourly
# armed by lifespan() only: importing this module (the tests, the backfill CLI) never GETs data-service from _track
_DATASET_CHECK: dict[str, Any] = {"armed": False, "at": 0.0, "ids": None}
_RUNNING: dict[str, str] = {}          # job id → start (ISO, IST) while a run is in flight (m113: SYS › DATA said 30 Oct)
_CATCHUP_PLAN: dict[str, str] = {}     # job id → when a pending one-off re-runs it (M30: SYS states only what will run)


def dataset_fingerprints(payload: Any, job_id: str) -> dict[str, tuple[Any, ...]] | None:
    """{dataset id: fingerprint} for the catalogued datasets whose ingest job is `job_id` and that can be judged (a stored
    as-of, or an ingest_log fetch with a date / revision / sha256 / Last-Modified); the fetch time is left out (a re-fetch
    of the same file is not new data). None when the payload carries no rows (data-service down or without B1)."""
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    out: dict[str, tuple[Any, ...]] = {}
    for r in rows:
        if not isinstance(r, dict) or str(r.get("job_id") or "") != job_id:
            continue
        raw_lf = r.get("last_fetch")
        lf: dict[str, Any] = raw_lf if isinstance(raw_lf, dict) else {}
        if r.get("as_of") is None and not lf:
            continue                                   # an endpoint-kind row: nothing stored to compare
        out[str(r.get("id"))] = (r.get("as_of"), lf.get("date"), lf.get("revision"), lf.get("sha256"), lf.get("last_modified"))
    return out


def dataset_outcome(before: dict[str, tuple[Any, ...]] | None, after: dict[str, tuple[Any, ...]] | None) -> str | None:
    """STATUS_NO_NEW_DATA when the job's datasets were judged before AND after the run and none of them moved; None (keep
    the run's own status) without evidence: no judgeable dataset, or data-service did not answer one of the two reads."""
    if not before or after is None:
        return None
    if set(after) != set(before) or any(after[k] != v for k, v in before.items()):
        return None
    return STATUS_NO_NEW_DATA


async def _dataset_snapshot(job_id: str) -> dict[str, tuple[Any, ...]] | None:
    """The job's dataset fingerprints now, or None (check off / not armed / the job owns no catalogued dataset / no
    answer within DATASET_CHECK_TIMEOUT_S). One local GET; skipped without a request for jobs known to own nothing."""
    st = _DATASET_CHECK
    if not (JOB_DATASET_CHECK and st["armed"]):
        return None
    ids = st["ids"]
    if ids is not None and job_id not in ids and _time.time() - st["at"] < DATASET_JOBS_TTL_S:
        return None
    try:
        async with httpx.AsyncClient(timeout=DATASET_CHECK_TIMEOUT_S) as client:
            r = await client.get(f"{DATA_SVC}{DATASET_HEALTH_PATH}")
        payload = r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001 — no evidence, never a failure of the job
        return None
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if isinstance(rows, list):
        st["at"], st["ids"] = _time.time(), {str(x.get("job_id")) for x in rows if isinstance(x, dict) and x.get("job_id")}
    return dataset_fingerprints(payload, job_id)


@asynccontextmanager
async def _track(job_id: str, quiet: bool = False) -> AsyncIterator[None]:
    """Record the run for SYS (latency + persisted history). `quiet` (a job firing every few minutes) keeps the result
    for SYS but writes no "Finished" line: 288 lines a day would push every other job out of the 500-line log ring.

    Status: "error" (an exception, or _mark_failed) > a mark (_mark_status: "skipped") > "no new data" (M33: the job's
    catalogued datasets did not move; not judged for quiet jobs) > "done". The dataset reads are not part of the latency."""
    _soft_failed.discard(job_id)
    _status_marks.pop(job_id, None)
    before = None if quiet else await _dataset_snapshot(job_id)
    _RUNNING[job_id] = datetime.now(IST).isoformat(timespec="seconds")
    t0 = _time.perf_counter()
    status, completed = "done", False
    try:
        yield
        completed = True
    except Exception:
        status = "error"
        raise
    finally:
        ms = (_time.perf_counter() - t0) * 1000
        _RUNNING.pop(job_id, None)
        _CATCHUP_PLAN.pop(job_id, None)               # it ran: the pending catch-up is spent (or superseded)
        mark = _status_marks.pop(job_id, None)
        if job_id in _soft_failed:
            _soft_failed.discard(job_id)
            status = "error"
        elif status == "done" and mark:
            status = mark
        elif status == "done" and completed and before:
            status = dataset_outcome(before, await _dataset_snapshot(job_id)) or status
        _latency.record(job_id, ms, status)
        _history.record(job_id, status, ms)
        try:                                          # M38: sd_job_seconds{job, status} on /metrics (0 callers before)
            observe_job(job_id, ms / 1000.0, status)
        except Exception:  # noqa: BLE001, S110 — a metric never fails a job
            pass
        if not quiet:
            _log.info(job_id, f"Finished in {ms:.1f}ms", latency_ms=f"{ms:.1f}", status=status)


# ── Market hours gate ─────────────────────────────────────────────────────────
def _is_market_hours() -> bool:
    return MARKET_OPEN <= datetime.now(IST).time() <= MARKET_CLOSE


# ══════════════════════════════════════════════════════════════════════════════
# Scheduled Jobs
# ══════════════════════════════════════════════════════════════════════════════

DATA_JOB_POLL_SECS = 15
# the first polls come sooner (m111: a dozen jobs showed ≈ 15,0xx ms on SYS, the poll cadence, not their work): a short
# job is timed to ±1 s, a long one costs ≤ 6 extra local GETs; then every DATA_JOB_POLL_SECS
DATA_JOB_POLL_STEPS: tuple[float, ...] = (1, 1, 2, 3, 5, 8)


def data_job_poll_delay(i: int) -> float:
    """Seconds before the i-th status poll of a data-service job (never above DATA_JOB_POLL_SECS)."""
    step = DATA_JOB_POLL_STEPS[i] if i < len(DATA_JOB_POLL_STEPS) else DATA_JOB_POLL_SECS
    return min(step, DATA_JOB_POLL_SECS)


DATA_JOB_TIMEOUT_SECS = int(os.getenv("DATA_JOB_TIMEOUT_SECS", "5400"))
# Data upkeep is not trading: it runs even when AUTOPILOT is off, so features are
# never silently stale when autopilot is switched back on. Opt out with 0.
DATA_JOBS_ENABLED = os.getenv("DATA_JOBS_ENABLED", "1") == "1"
# Terminal v2 Wave 0 0.5: the 18:30 pipeline is equity-only. NSE's F&O / participant-OI files land at 20:10 (measured
# 4 Nov 2026, R-DATA §4), so the 18:30 attempt only ever logged a miss; the 20:30 pass is the real path and now carries
# iv_eod. B1's /jobs/daily-pipeline honours `skip_steps` (patch request in the B2 result); until it does, the key is
# ignored by its request model and the step still runs — nothing breaks either way.
EOD_PIPELINE_BODY: dict[str, Any] = {"mode": "incremental", "skip_steps": ["nse_positions"]}


class DataJobHTTPError(RuntimeError):
    """data-service refused to start a job (non-200 on the POST); the status is kept for callers that treat a 404 — the
    endpoint is not deployed there yet — differently from a failure. The message is the one callers always saw."""

    def __init__(self, status: int, path: str, text: str) -> None:
        super().__init__(f"POST {path} → HTTP {status}: {text[:300]}")
        self.status = status


async def _run_data_job(job: str, path: str, body: dict | None = None, quiet: bool = False) -> dict:
    """Start a data-service job, poll it to completion, raise on any failure.

    Every HTTP status is checked — the old sync posted to a non-existent endpoint,
    got a 404 and still reported "Pre-Market Sync OK". `quiet` (a job firing every few
    minutes, e.g. the gold 1-minute bars) writes no "started" line: 288 a day would push
    every other job out of the log ring.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{DATA_SVC}{path}", json=body or {})
        if resp.status_code != 200:
            raise DataJobHTTPError(resp.status_code, path, resp.text)
        started = resp.json()
        job_id = started["job_id"]
        if started.get("already_running"):
            # data-service runs one job per kind: it handed back the job already in flight, so this call's body (e.g. a
            # backfill_from) was NOT applied — the caller polls that run instead. The gold jobs serialise on a per-job
            # lock so this is rare for them; the line makes it visible when it happens.
            _log.warning(job, f"data-service already runs this job: attached to {job_id} ({path})")
        elif not quiet:
            _log.info(job, f"data-service job started: {path}", job_id=job_id)

        deadline = _time.monotonic() + DATA_JOB_TIMEOUT_SECS
        polls = 0
        while _time.monotonic() < deadline:
            await asyncio.sleep(data_job_poll_delay(polls))
            polls += 1
            st = await client.get(f"{DATA_SVC}/jobs/{job_id}")
            if st.status_code != 200:
                raise RuntimeError(f"GET /jobs/{job_id} → HTTP {st.status_code}")
            info = st.json()
            if info["status"] == "done":
                return info.get("result") or {}
            if info["status"] == "error":
                raise RuntimeError(f"data-service job {job_id} failed: {info.get('error')}")
        raise TimeoutError(f"data-service job {job_id} still running after {DATA_JOB_TIMEOUT_SECS}s")


def _refresh_digest(summary: dict) -> str:
    counts = summary.get("counts", {})
    return (f"tickers={summary.get('total')} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            + f" quarantined={summary.get('bars_quarantined', 0)}")


async def pre_market_sync() -> None:
    """08:30 IST — incremental bar refresh (Yahoo, quality-gated) + freshness check."""
    JOB = "pre_market_sync"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "Still running from previous trigger — skipped")
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            _log.info(JOB, "DATA_JOBS_ENABLED=0 — skipped")
            return
        _log.info(JOB, "Pre-market sync starting", time_ist=datetime.now(IST).strftime("%H:%M"))
        try:
            summary = await _run_data_job(JOB, "/jobs/refresh-universe", {"mode": "incremental"})
            async with httpx.AsyncClient(timeout=30) as client:
                fr = await client.get(f"{DATA_SVC}/db/freshness")
                fr.raise_for_status()
                fresh = fr.json()
            digest = _refresh_digest(summary)
            _log.info(JOB, f"Refresh complete: {digest}", **{k: fresh.get(k) for k in
                      ("latest_bar_date", "eligible_stale", "ml_features_latest_date")})
            if not fresh.get("features_fresh"):
                await _alerts.critical(
                    "Features STALE before market open",
                    f"ml_features latest={fresh.get('ml_features_latest_date')} "
                    f"vs bars={fresh.get('latest_bar_date')} — last EOD pipeline did not complete",
                )
            await _alerts.info("Pre-Market Sync OK", f"{digest} at {datetime.now(IST).strftime('%H:%M IST')}")
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("Pre-Market Sync FAILED", str(exc))
            raise


async def eod_data_pipeline() -> None:
    """18:30 IST Mon–Fri — refresh today's settled bars, then rebuild ML features/labels."""
    JOB = "eod_data_pipeline"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "Still running from previous trigger — skipped")
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            _log.info(JOB, "DATA_JOBS_ENABLED=0 — skipped")
            return
        try:
            result = await _run_data_job(JOB, "/jobs/daily-pipeline", dict(EOD_PIPELINE_BODY))
            build = result.get("build", {})
            msg = (f"{_refresh_digest(result.get('refresh', {}))} | features={build.get('feature_rows')} "
                   f"labels={build.get('label_rows')} through {build.get('feature_date_range', ['?', '?'])[1]}")
            _log.info(JOB, f"EOD data pipeline complete: {msg}")
            # Non-fatal step failures (eod_steps.py, 15 Oct incident): the job finished and the market
            # data landed, but a step such as the ML rebuild or the NSE bhavcopy failed — say so loudly.
            soft = {k: v["error"] for k, v in result.items() if isinstance(v, dict) and v.get("error")}
            if soft:
                await _alerts.warning("EOD pipeline finished with failed steps",
                                      "\n".join(f"{k}: {str(e)[:300]}" for k, e in soft.items()))
            else:
                await _alerts.info("EOD Data Pipeline OK", msg)
            await _check_dataset_freshness(JOB)
            _alerts_after_soon(JOB)             # the stored-series alert rules see tonight's bhavcopy (PLAN 2.3)
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("EOD Data Pipeline FAILED", str(exc))
            raise


async def intraday_inference_cycle() -> None:
    """Every 15 min 09:00–15:59 IST — XGBoost inference → RL act (market hours gated)."""
    JOB = "intraday_inference"
    if not _is_market_hours():
        _log.info(JOB, f"Outside market hours ({datetime.now(IST).strftime('%H:%M IST')}) — skip")
        return
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "Previous 15-min cycle still running — misfire guarded")
        return
    async with lock, _track(JOB):
        if not _autopilot.on:
            _mark_status(JOB, STATUS_SKIPPED)       # dormant legacy engine: SYS says "skipped", not "done" (m111)
            _log.info(JOB, "AUTOPILOT OFF — skipped")
            return
        now_str = datetime.now(IST).strftime("%H:%M IST")
        _log.info(JOB, f"Inference cycle starting at {now_str}")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # XGBoost batch inference across full stock universe
                t_xgb = _time.perf_counter()
                xgb_resp = await client.post(f"{ML_SVC}/batch-predict", json={})
                xgb_ms = (_time.perf_counter() - t_xgb) * 1000
                if xgb_resp.status_code != 200:
                    raise RuntimeError(f"batch-predict HTTP {xgb_resp.status_code}: {xgb_resp.text[:200]}")
                batch_result = xgb_resp.json()
                signals = batch_result.get("signals", [])
                _log.info(
                    JOB,
                    f"XGBoost Inference Time: {xgb_ms:.0f}ms",
                    signals=len(signals),
                    tickers=batch_result.get("ticker_count", 0),
                )

                # Stream high-confidence signals to RL portfolio optimizer
                t_rl = _time.perf_counter()
                rl_resp = await client.post(
                    f"{RL_SVC}/optimize/portfolio",
                    json={"signals": signals},
                )
                rl_ms = (_time.perf_counter() - t_rl) * 1000
                if rl_resp.status_code == 200:
                    allocations = rl_resp.json().get("allocations", {})
                    _log.info(
                        JOB,
                        f"RL Portfolio Optimize Time: {rl_ms:.0f}ms",
                        allocations=len(allocations),
                        method=rl_resp.json().get("method", "unknown"),
                    )
                else:
                    _log.warning(
                        JOB,
                        f"RL optimize degraded (HTTP {rl_resp.status_code}) — signals logged, skipping allocation",
                    )

        except Exception as exc:
            _log.error(JOB, f"Inference cycle FAILED at {now_str}: {exc}")
            await _alerts.critical("Intraday Inference FAILED", f"At {now_str}: {exc}")
            raise


async def eod_rebalancing() -> None:
    """15:15 IST — Square off intraday trades + portfolio rebalance."""
    JOB = "eod_rebalancing"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "EOD rebalancing already running — skip")
        return
    async with lock, _track(JOB):
        if not _autopilot.on:
            _mark_status(JOB, STATUS_SKIPPED)       # dormant legacy engine: SYS says "skipped", not "done" (m111)
            _log.info(JOB, "AUTOPILOT OFF — skipped")
            return
        _log.info(JOB, "EOD rebalancing + square-off starting")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{EXECUTION_SVC}/square-off",
                    json={"reason": "eod_rebalancing"},
                )
                _log.info(JOB, f"Square-off → HTTP {resp.status_code}")
            await _alerts.info(
                "EOD Rebalancing Complete",
                f"Intraday positions closed at {datetime.now(IST).strftime('%H:%M IST')}",
            )
        except Exception as exc:
            _log.error(JOB, f"EOD rebalancing FAILED: {exc}")
            await _alerts.critical("EOD Rebalancing FAILED — MANUAL ACTION REQUIRED", str(exc))
            raise


async def overnight_rl_retrain() -> None:
    """23:00 IST — Retrain RL agent on the day's accumulated data."""
    JOB = "overnight_rl_retrain"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "RL retraining already running — skip tonight")
        return
    async with lock, _track(JOB):
        if not _autopilot.on:
            _mark_status(JOB, STATUS_SKIPPED)       # dormant legacy engine: SYS says "skipped", not "done" (m111)
            _log.info(JOB, "AUTOPILOT OFF — skipped")
            return
        _log.info(JOB, f"Overnight RL retraining starting via {RL_TRAINER_PATH}")
        try:
            cmd = [PYTHON_BIN, RL_TRAINER_PATH, "--total-timesteps", "50000", "--n-candidates", "15"]
            result: subprocess.CompletedProcess[str] = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, text=True, timeout=3600
            )
            if result.returncode == 0:
                _log.info(JOB, "RL retraining finished successfully")
                await _alerts.info("RL Retraining Complete", f"Model updated at {datetime.now(IST).strftime('%H:%M IST')}")
            else:
                _log.error(JOB, "RL retraining exit non-zero", stderr=result.stderr[:400])
                await _alerts.critical("RL Retraining FAILED", result.stderr[:500])
        except subprocess.TimeoutExpired:
            _log.error(JOB, "RL retraining killed — exceeded 60 min timeout")
            await _alerts.critical("RL Retraining Timeout", "Process killed after 60-min limit")
        except Exception as exc:
            _log.error(JOB, f"Unexpected exception: {exc}")
            await _alerts.critical("RL Retraining Exception", str(exc))
            raise


# ══════════════════════════════════════════════════════════════════════════════
# Decision Desk: paper trading of the approved monthly momentum strategy.
# Not gated by autopilot (it never sends a broker order). Opt out: DESK_ENABLED=0.
# ══════════════════════════════════════════════════════════════════════════════

DESK_ENABLED = os.getenv("DESK_ENABLED", "1") == "1"


async def desk_daily() -> None:
    """19:30 IST Mon–Fri: after the EOD pipeline has loaded today's bhavcopy."""
    JOB = "desk_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "Still running from previous trigger — skipped")
        return
    async with lock, _track(JOB):
        if not DESK_ENABLED:
            _mark_status(JOB, STATUS_SKIPPED)       # nothing was marked: SYS and the catch-up report must not say "done"
            _log.info(JOB, "DESK_ENABLED=0 — skipped")
            return
        try:
            async with httpx.AsyncClient(timeout=1800) as client:
                resp = await client.post(f"{UI_API}/api/desk/daily")
            if resp.status_code != 200:
                raise RuntimeError(f"POST /api/desk/daily → HTTP {resp.status_code}: {resp.text[:300]}")
            res = resp.json()
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("Decision Desk cycle FAILED", str(exc))
            raise
        _log.info(JOB, f"marked {res['sessions_marked']} session(s), {len(res['executions'])} execution(s)")
        for ex in res["executions"]:
            fills = ", ".join(f"{side} {sym} {int(q)}@₹{px:,.2f}" for side, sym, q, px in ex["fills"]) or "none"
            await _alerts.info(f"PAPER fills ({ex['plan_id']})", fills[:3500])
        if res.get("emergency"):
            await _alerts.critical("Decision Desk EMERGENCY STOP",
                                   "Portfolio drawdown hit the limit: selling everything at the next open. "
                                   "Re-enable manually after review (POST /api/desk/reenable).")
        plan = res.get("plan")
        if plan:
            if not plan["risk_on"]:
                body = (f"Crash filter ON: NIFTY {plan['nifty']:,.0f} < 200-DMA {plan['nifty_200dma']:,.0f}. "
                        f"Stay in the liquid fund. {plan['trades']} sell order(s).")
            else:
                body = (f"{plan['trades']} trade(s), est. cost ₹{plan['est_costs']:,.0f}, "
                        f"~₹{plan['per_name_target']:,.0f} per new stock. Executes at the next open.")
            await _alerts.info(f"Decision Brief {plan['plan_id']}", body)


async def nse_positions_catchup() -> None:
    """20:30 IST Mon–Fri — the evening pass: F&O OI / participant OI / deals / MTF files NSE publishes after 18:30 (each
    dataset resumes after its last stored day), FII/DII cash (NSE serves only the latest day), then — Terminal v2 — the
    other verified NSE evening files (PLAN 1.4: participant volumes, FII derivative stats, MWPL clients ≥ 3 %), the 20:35
    retry of index_drivers_daily when the 19:25 run found no top-10 file, and LAST, once the day's F&O file is stored,
    iv_eod (PLAN 1.1: the file lands 20:10, so R-IV's 19:35 was too early; the 22:45 pass retries a miss). Inside the
    evening window by design: fetches only (PLAN §0.10), nothing restarts."""
    JOB = "nse_positions_catchup"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        try:
            result = await _run_data_job(JOB, "/jobs/ingest-nse-positions", {})
            tables = result.get("tables", {})
            _log.info(JOB, "positions up to " + ", ".join(f"{k.replace('nse_', '')}={v.get('last')}" for k, v in tables.items()))
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("NSE positions catch-up FAILED", str(exc))
        try:                                    # NSE serves only the latest day: miss it and it is gone
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{DATA_SVC}/db/fii-dii-cash/refresh")
            _log.info(JOB, f"FII/DII cash: HTTP {r.status_code} {r.text[:120]}")
        except Exception as exc:
            _log.warning(JOB, f"FII/DII cash refresh failed: {exc}")
        if not TERMINAL_JOBS_ENABLED or await _closed_today(JOB):
            return
        try:
            res = await _terminal_job(JOB, NSE_FILES_PATH, {"datasets": list(NSE_EVENING_FILES)})
            _log.info(JOB, "evening files: " + revision_digest(res))
        except TerminalJobUnavailable as exc:
            _log.warning(JOB, str(exc))
            return                              # the same 404 would meet the drivers and iv_eod: said once, paused an hour
        except Exception as exc:  # noqa: BLE001 — one file set never stops the pass
            _log.warning(JOB, f"evening files failed: {type(exc).__name__}: {str(exc)[:160]}")
        today = datetime.now(IST).date().isoformat()
        if _DRIVERS_STATE.get("date") != today or _DRIVERS_STATE.get("top10_missing"):
            await index_drivers_run(JOB, today, retry=True)
        await iv_eod_step(JOB, today)
        _alerts_after_soon(JOB)                 # the IV / OI / basis / ban / FII rules on tonight's stored rows


# ══════════════════════════════════════════════════════════════════════════════
# GOLD program (reports/gold_program/PLAN.md §c.3, builder B2). Every gold job is a FETCH into data/market.duckdb through
# data-service POST /jobs/ingest-gold (idempotent groups; a group skips when it is not due; one series failing never
# fails the group), never a restart. Heavy jobs are scheduled outside the 07:45–09:20 / 18:30–21:15 freeze windows and a
# late run of one (misfire after a late boot, start-up catch-up) moves itself to the minute after the window. The few
# small fetches PLAN §c.3 places inside a window (the 08:35 master retry, 08:40 health, 09:05 brief, the hourly calendar,
# the 1-minute bars) are marked `light`. Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or
# the paper ticket (PLAN §0.1 #7): the only Telegram lines are the 08:45 fair-open note and the Saturday COT digest,
# both worded as context. Memory discipline (15 Oct OOM): the controller only starts jobs; data-service streams.
# ══════════════════════════════════════════════════════════════════════════════
GOLD_LOG_ENABLED = os.getenv("GOLD_LOG_ENABLED", "1") == "1"
GOLD_JOBS_ENABLED = os.getenv("GOLD_JOBS_ENABLED", "1") == "1"
GOLD_INGEST_PATH = "/jobs/ingest-gold"                 # data-service (B1): ?job=<id> + {"job", "groups", "backfill_from"?}
GOLD_DESK_API = "/api/commodity/gold-preopen"          # ui-api pre-open desk; alias of /api/gold/* for one release (PLAN §d)
GOLD_INVALIDATE_PATH = "/api/gold/invalidate"          # ui-api stored-read cache, cleared after an ingest (PLAN §d); optional
GOLD_INGEST_PAUSE_S = 3600                             # a 404 (data-service without the gold package yet) pauses gold jobs 1 h
GOLD_CHASE_LIMIT_INR = 300                             # the desk's house rule — a heuristic with a measured miss, PLAN §a.2
NY = pytz.timezone("America/New_York")


def comex_globex_open(now: datetime) -> bool:
    """COMEX gold trades on Globex Sun 18:00 → Fri 17:00 ET with a 17:00–18:00 ET maintenance hour (02:30–03:30 IST in
    US daylight time, 03:30–04:30 IST otherwise): the 1-minute-bar job fetches only then (PLAN §a.3; DST-aware)."""
    ny = now.astimezone(NY)
    wd, t = ny.weekday(), ny.time()
    if wd == 5:
        return False
    if wd == 6:
        return t >= time(18, 0)
    if wd == 4 and t >= time(17, 0):
        return False
    return not (time(17, 0) <= t < time(18, 0))


SH = pytz.timezone("Asia/Shanghai")


def sge_session_open(now: datetime) -> bool:
    """SGE trades 09:00–15:30 (day) and 20:00–02:30 (night) Beijing time, Mon–Fri trading days; the night session that
    starts on a Friday belongs to Monday and runs to Sat 02:30. In IST: 06:30–13:00 and 17:30–00:00. The 5-minute SGE
    intraday-quote job fetches only then (6 Nov 2026: the sge_quotes group existed but no job ran it, so DAILY read
    'No SGE bars stored for today yet' during SGE hours). Chinese holidays are not modelled: a closed day's fetch stores
    nothing new."""
    sh = now.astimezone(SH)
    wd, t = sh.weekday(), sh.time()
    if wd <= 4 and (time(9, 0) <= t <= time(15, 35) or t >= time(20, 0)):
        return True
    return 1 <= wd <= 5 and t <= time(2, 35)          # the tail of the previous evening's night session (Tue–Sat)


@dataclass(frozen=True)
class GoldJob:
    """One gold ingest job (PLAN §c.3): its data-service groups, IST trigger(s) and how it behaves around the windows."""
    groups: tuple[str, ...]
    crons: tuple[dict[str, Any], ...]      # CronTrigger kwargs; several → OrTrigger (one job id, as in the plan)
    name: str
    misfire_grace_s: int
    light: bool = False                    # a few small fetches that may run inside a freeze window; the rest defer
    quiet: bool = False                    # frequent: no "Finished" line per run, a failure logged once an hour, no Telegram
    gate: Callable[[datetime], bool] | None = None   # runs only when true (COMEX open for the 1-minute bars)
    key: bool = False                      # re-run after downtime with backfill_from (startup_catchup; PLAN §c.3 "Catch-up")


GOLD_JOBS: dict[str, GoldJob] = {
    # Schedule deviation from PLAN §c.3 ("03:10 daily, Tue–Sat; Mon for Friday's US session"), deliberate: Mon–Sat, i.e.
    # Sunday skipped and Monday included — see gold_job()'s docstring.
    "gold_overnight": GoldJob(("treasury", "yahoo_daily", "yahoo_curve", "cme_voi_final", "fred_daily", "calendar_us"),
                              ({"day_of_week": "mon-sat", "hour": 3, "minute": 10},),
                              "Gold overnight (Treasury, Yahoo daily, COMEX curve, CME final VOI, FRED, US calendar)", 6 * 3600, key=True),
    "gold_intraday_bars": GoldJob(("bars_1m",), ({"minute": "*/5"},), "Gold 1-minute bars (every 5 min while COMEX trades)",
                                  120, light=True, quiet=True, gate=comex_globex_open),
    # one small GET to SGE's delayed quotation line every 5 min during SGE hours (displayed with attribution, never
    # re-served: O-1); light, quiet, gated like the COMEX bars
    "gold_sge_quotes": GoldJob(("sge_quotes",), ({"minute": "2-59/5"},), "Gold SGE intraday quotes (every 5 min in SGE hours)",
                               120, light=True, quiet=True, gate=sge_session_open),
    "gold_morning": GoldJob(("etf", "fed_path", "gpr_daily", "monthly_due"),
                            ({"day_of_week": "mon-sat", "hour": 6, "minute": 40},),
                            "Gold morning (ETF holdings, Fed path, GPR, monthly series due)", 4 * 3600, key=True),
    "gold_mcx_master": GoldJob(("mcx_master", "margins"), ({"day_of_week": "mon-fri", "hour": "7-8", "minute": 35},),
                               "Gold MCX master + margins (07:35, retry 08:35)", 1800, light=True, key=True),
    "gold_health_snapshot": GoldJob(("health",), ({"day_of_week": "mon-fri", "hour": 8, "minute": 40},),
                                    "Gold health snapshot (gold_health_daily)", 600, light=True, key=True),
    "gold_brief_ingest": GoldJob(("brief",), ({"hour": 9, "minute": 5},), "Gold brief ingest", 3 * 3600, light=True),
    "gold_calendar_refresh": GoldJob(("calendar_us",), ({"hour": "9-23", "minute": 0},),
                                     "Gold US calendar refresh (hourly)", 600, light=True, quiet=True),
    "gold_india_midday": GoldJob(("ibja_am", "inr_ref"), ({"day_of_week": "mon-fri", "hour": 13, "minute": 45},),
                                 "Gold India midday (IBJA AM, RBI reference rate)", 2 * 3600, key=True),
    "gold_cme_daily": GoldJob(("cme_voi", "cme_prf"), ({"day_of_week": "mon-sat", "hour": 15, "minute": 45},
                                                       {"day_of_week": "mon-sat", "hour": 17, "minute": 15}),
                              "Gold CME daily volume/OI + product reference (15:45, retry 17:15)", 3600),
    "gold_asia_close": GoldJob(("sge_daily", "sge_benchmark", "shfe"), ({"day_of_week": "mon-fri", "hour": 16, "minute": 10},),
                               "Gold Asia close (SGE daily + benchmark, SHFE)", 2 * 3600, key=True),
    "gold_india_pm": GoldJob(("ibja_pm", "derive_india"), ({"day_of_week": "mon-fri", "hour": 18, "minute": 10},),
                             "Gold India PM (IBJA PM + the India ladder)", 900, key=True),
    "gold_fred_daily": GoldJob(("fred_daily", "lbma_wgc", "cme_efrp", "derive_global"), ({"hour": 21, "minute": 30},),
                               "Gold FRED daily, LBMA/WGC prices, CME EFRP, derived global", 4 * 3600),
    "gold_cot_weekly": GoldJob(("cot",), ({"day_of_week": "sat", "hour": "2-6", "minute": 30},
                                          {"day_of_week": "mon-tue", "hour": 6, "minute": 30}),
                               "Gold CFTC COT weekly (Sat 02:30, hourly to 06:30; Mon/Tue 06:30 catch-up)", 1800, key=True),
    "gold_weekly": GoldJob(("wgc_etf", "rbi_wss", "lbma_turnover", "wgc_premiums", "fred_weekly"),
                           ({"day_of_week": "mon", "hour": 12, "minute": 0}, {"day_of_week": "fri", "hour": 18, "minute": 0},
                            {"day_of_week": "sat", "hour": 10, "minute": 30}),
                           "Gold weekly (WGC ETF flows, RBI WSS, LBMA turnover, WGC premiums, FRED weekly)", 2 * 3600),
    "gold_cme_calendar": GoldJob(("cme_calendar",), ({"day_of_week": "sun", "hour": 4, "minute": 0},),
                                 "Gold CME expiry calendar (weekly)", 12 * 3600),
    # wave 1d (G-DATA): the MCX settlement proxy — last-30-min VWAP of Breeze 1-minute bars (data-service group
    # mcx_close_vwap30: ≤ 15 read-only calls through the budget ledger, a stored session costs 0) — then the India ladder,
    # so MCX_BASIS_PCT pairs each session's settlement with its own duty-paid landed price; key: re-run after downtime
    # 6 Nov (O-OPS): the round-2 00:15 Tue–Sat retry is gone — ICICI sessions expire at midnight IST, so a 00:15 run never
    # had a session to read Breeze's bars with. One 23:58 run; after downtime the start-up catch-up re-runs it (with
    # backfill_from) only while a Breeze session is live (gold_downtime_catchup)
    "gold_mcx_close": GoldJob(("mcx_close_vwap30", "derive_india"), ({"day_of_week": "mon-fri", "hour": 23, "minute": 58},),
                              "Gold MCX settlement proxy (Breeze last-30-min VWAP, 23:58) + India ladder", 6 * 3600,
                              key=True),
    # O-8 (6 Nov 2026, the owner authorised this one only): Breeze daily OHLC / volume / OI per LIVE MCX gold expiry →
    # gold_mcx_daily (data-service group breeze_daily: ≤ 15 read-only calls through the budget ledger, 1.2 s apart). 09:35
    # is after the ≈08:00 ICICI login and outside the 07:45–09:20 freeze window; it stores the previous session's complete
    # bars (today's partial bar is skipped). Needs a live session, so the downtime catch-up re-runs it only while one is live
    "gold_breeze_daily": GoldJob(("breeze_daily",), ({"day_of_week": "mon-fri", "hour": 9, "minute": 35},),
                                 "Gold MCX daily history (Breeze, 09:35: the previous session's complete bars)", 3600, key=True),
}
# PLAN §c.3 / owner action O-8: the schema and a panel placeholder exist; no collector runs until the owner decides
# (6 Nov 2026: gold_breeze_daily authorised and moved to GOLD_JOBS; the two MCX-site collectors stay here).
GOLD_DORMANT_JOBS: dict[str, str] = {
    "gold_mcx_bhavcopy": "MCX official bhavcopy needs a browser-session collector the owner has not authorised (O-8)",
    "gold_mcx_category": "MCX category-wise OI workbook needs the same collector (O-8)",
}
# key=True: re-run after downtime with backfill_from (PLAN §c.3; Terminal v2 0.9 added the Asia-close, morning, India
# and health-snapshot jobs — B1 writes their back-dated rows with backfilled=true)
GOLD_KEY_JOBS: tuple[str, ...] = tuple(j for j, s in GOLD_JOBS.items() if s.key)
# key jobs that read Breeze (ICICI) and so are re-run after downtime only while a session is live (6 Nov, O-OPS)
GOLD_SESSION_JOBS: tuple[str, ...] = ("gold_mcx_close", "gold_breeze_daily")
GOLD_MAX_AGE_DAYS = {"gold_cot": 11, "gold_curve": 4, "gold_daily_bars": 4, "gold_etf_holdings": 5, "gold_cme_daily_voi": 4}
GOLD_STATUS_TABLES = (("gold_cot", "COT"), ("gold_cme_daily_voi", "COMEX OI"), ("gold_curve", "MCX curve"),
                      ("gold_daily_bars", "bars"), ("gold_etf_holdings", "ETF"))
# PLAN §c.3 asks for some groups on certain weekdays only: job id → (group, weekdays it is asked for). A multi-day catch-up
# (gold_groups(..., backfill=True)) asks for them regardless, since the outage may have covered that weekday.
GOLD_DAY_GROUPS: dict[str, tuple[str, tuple[int, ...]]] = {
    "gold_overnight": ("fred_weekly", (1, 4)),      # H.10 on Tue 03:10; H.4.1 / TGA on Fri 03:10
    "gold_morning": ("gpr_daily", (0,)),            # the weekly GPR file on Mondays
}
# PLAN §0.1 / §f and owner action O-14: no gold alert implies a direction. Strings relayed from ui-api (who_did, the driver
# label, a session label) pass this guard before they reach Telegram; a fragment that fails it is dropped, not quoted.
GOLD_DIRECTION_WORDS = re.compile(r"\b(bullish|bearish|buy|sell|go long|go short|long gold|short gold|target|forecast\w*)\b",
                                  re.IGNORECASE)


def gold_groups(job_id: str, now: datetime, backfill: bool = False) -> tuple[str, ...]:
    """The groups a run asks data-service for (B1 resolves the controller's names through its ALIASES; every name here
    is pinned to resolve in scripts/tests). The day-conditional group (GOLD_DAY_GROUPS) is included on its weekdays
    only — always for a multi-day backfill, whose outage may have covered that weekday."""
    groups = GOLD_JOBS[job_id].groups
    extra = GOLD_DAY_GROUPS.get(job_id)
    if extra is None:
        return groups
    group, days = extra
    wanted = backfill or now.weekday() in days
    if wanted and group not in groups:
        return (*groups, group)
    if not wanted and group in groups:
        return tuple(g for g in groups if g != group)
    return groups


def _context_only(job: str, text: Any) -> str:
    """A relayed string for a Telegram line, or '' (and one WARNING) when it carries a direction word — the line is
    description, never a call (PLAN §f). The controller's own wording is fixed and never passes through here."""
    s = str(text or "").strip()
    if s and GOLD_DIRECTION_WORDS.search(s):
        _gold_warn_once(job, f"dropped a relayed fragment with a direction word: {s[:80]!r}", every_s=600)
        return ""
    return s


def gold_runner(job_id: str) -> tuple[Callable[..., Any], list[Any]]:
    """The coroutine function and args to schedule for a gold job id (the COT job has its own runner)."""
    return (gold_cot_weekly, []) if job_id == "gold_cot_weekly" else (gold_job, [job_id])


def register_gold_jobs(sched: Any) -> list[str]:
    """Register every GOLD_JOBS entry with its IST trigger(s); dormant jobs (O-8) are not registered. Returns the ids."""
    ids: list[str] = []
    for job_id, spec in GOLD_JOBS.items():
        crons = [CronTrigger(timezone=IST, **c) for c in spec.crons]
        trigger: Any = crons[0] if len(crons) == 1 else OrTrigger(crons)
        func, args = gold_runner(job_id)
        sched.add_job(func, trigger=trigger, args=args, id=job_id, name=spec.name, max_instances=1, coalesce=True,
                      misfire_grace_time=spec.misfire_grace_s)
        ids.append(job_id)
    return ids


class GoldIngestUnavailable(RuntimeError):
    """data-service answered 404 for /jobs/ingest-gold: the gold package is not deployed there (yet)."""


_GOLD_PAUSED_UNTIL = 0.0
_GOLD_LAST_WARNED: dict[str, float] = {}
_GOLD_ALERTED_DAY: dict[str, str] = {}


def _gold_warn_once(job: str, msg: str, every_s: float = GOLD_INGEST_PAUSE_S) -> None:
    """One WARNING per job per `every_s` (a 5-minute job must not repeat the same line 288 times a day)."""
    now = _time.time()
    if now - _GOLD_LAST_WARNED.get(job, 0.0) >= every_s:
        _GOLD_LAST_WARNED[job] = now
        _log.warning(job, msg)


def _gold_group_failed(row: Any) -> bool:
    """B1's run_group contract (gold/jobs.py): a group that did not deliver carries `error`, or a status of error /
    unknown (a name data-service does not know) / degraded (every leg failed) / http_<code>; `skipped`, `dormant` and
    `not_modified` (the MCX master's 304) are outcomes, not failures."""
    if not isinstance(row, dict):
        return False
    st = str(row.get("status") or "")
    return bool(row.get("error")) or st in ("error", "unknown", "degraded") or st.startswith("http_")


def gold_result_digest(result: Any) -> str:
    """One log line from B1's ingest result (`groups` {controller name: {status, inserted?, error?, reason?}}, `rows_total`,
    `tables` {table: {last}}; the helpers tolerate any shape): the outcome counts, the groups that did not deliver, the
    rows stored and the newest date per table."""
    if not isinstance(result, dict) or not result:
        return "done (no result body)"
    parts: list[str] = []
    groups = result.get("groups")
    if isinstance(groups, dict) and groups:
        counts: dict[str, int] = {}
        for g in groups.values():
            row = g if isinstance(g, dict) else {}
            st = row.get("status") or ("error" if row.get("error") else "ok")
            counts[str(st)] = counts.get(str(st), 0) + 1
        parts.append("groups " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        failed = [k for k, g in groups.items() if _gold_group_failed(g)]
        if failed:
            parts.append("failed: " + ", ".join(failed))
    if isinstance(result.get("rows_total"), int) and not isinstance(result["rows_total"], bool):
        parts.append(f"rows +{result['rows_total']}")
    tables = result.get("tables")
    if isinstance(tables, dict) and tables:
        parts.append("through " + ", ".join(f"{k.replace('gold_', '')}={str(v.get('last'))[:10]}" for k, v in tables.items()
                                            if isinstance(v, dict) and v.get("last")))
    return "; ".join(parts) or "done: " + ", ".join(str(k) for k in list(result)[:8])


def gold_result_all_failed(result: Any) -> bool:
    """True when the result names groups and every one of them failed (the run stored nothing it was asked for)."""
    groups = result.get("groups") if isinstance(result, dict) else None
    return bool(groups) and isinstance(groups, dict) and all(_gold_group_failed(g) for g in groups.values())


def gold_result_rows(result: Any) -> int:
    """Rows an ingest result says it stored: B1's `rows_total` when present (the sum of every leaf `inserted`, counted
    once), else new_rows / rows_added / inserted / upserted at any depth ≤ 3 — never a plain `rows`, which is a table
    size in this codebase (B1's `tables` block carries one per table); 0 when it says nothing."""
    if isinstance(result, dict) and isinstance(result.get("rows_total"), int) and not isinstance(result["rows_total"], bool):
        return int(result["rows_total"])
    keys = ("new_rows", "rows_added", "inserted", "upserted")

    def walk(node: Any, depth: int) -> int:
        if depth > 3 or not isinstance(node, dict):
            return 0
        n = 0
        for k, v in node.items():
            if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool):
                n += int(v)
            elif isinstance(v, dict):
                n += walk(v, depth + 1)
        return n
    return walk(result, 0)


async def _gold_invalidate_ui_cache(job: str) -> None:
    """After an ingest, ask ui-api to drop its stored-read cache (PLAN §d); a 404 (B3 not deployed) is nothing."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{UI_API}{GOLD_INVALIDATE_PATH}", json={"job": job})
        if r.status_code not in (200, 404):
            _gold_warn_once("gold_invalidate", f"{GOLD_INVALIDATE_PATH} → HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001 — the cache refreshes itself within 120 s anyway
        _gold_warn_once("gold_invalidate", f"{GOLD_INVALIDATE_PATH} unreachable: {type(exc).__name__}")


async def _gold_ingest(job: str, groups: Sequence[str], backfill_from: str | None = None, quiet: bool = False) -> dict:
    """POST /jobs/ingest-gold on data-service (B1's contract: `job` in the query and the body, `groups`, optional
    `backfill_from`) and poll it to completion; then clear ui-api's stored-read cache. A 404 pauses every gold job for
    an hour (data-service without the gold package, e.g. mid-rollout) instead of an error every five minutes. The
    request carries no Origin header (httpx sends none), so the services' Host/Origin guard admits it as a local peer."""
    global _GOLD_PAUSED_UNTIL
    body: dict[str, Any] = {"job": job, "groups": list(groups)}
    if backfill_from:
        body["backfill_from"] = backfill_from
    try:
        result = await _run_data_job(job, f"{GOLD_INGEST_PATH}?job={job}", body, quiet=quiet)
    except DataJobHTTPError as exc:
        if exc.status == 404:
            _GOLD_PAUSED_UNTIL = _time.time() + GOLD_INGEST_PAUSE_S
            raise GoldIngestUnavailable("data-service has no /jobs/ingest-gold (gold package not deployed): "
                                        "gold jobs paused for an hour") from exc
        raise
    await _gold_invalidate_ui_cache(job)
    return result


def _gold_defer(job_id: str, slot: datetime) -> None:
    """A heavy gold job that would run inside a freeze window (late boot, misfire catch-up) runs once at the window's end."""
    func, args = gold_runner(job_id)
    if scheduler is not None:
        scheduler.add_job(func, trigger="date", run_date=slot, args=args, id=f"{job_id}_deferred",
                          name=f"{GOLD_JOBS[job_id].name} (after the freeze window)", replace_existing=True,
                          misfire_grace_time=3600, coalesce=True)
    _log.info(job_id, f"freeze window: deferred to {slot:%H:%M}")


async def _gold_failure(job_id: str, spec: GoldJob, exc: Exception) -> None:
    """Log a failed fetch; the daily jobs also tell Telegram once a day (the `info` channel, PLAN §c.6); quiet jobs
    log at most once an hour and never alert. The GOLD page keeps showing the last stored value with STALE."""
    _mark_failed(job_id)
    msg = f"FAILED: {type(exc).__name__}: {str(exc)[:300]}"
    if spec.quiet:
        _gold_warn_once(job_id, msg)
        return
    _log.error(job_id, msg)
    day = datetime.now(IST).date().isoformat()
    if _GOLD_ALERTED_DAY.get(job_id) != day:
        _GOLD_ALERTED_DAY[job_id] = day
        await _alerts.info(f"Gold data job {job_id} failed",
                           f"{str(exc)[:200]}\nThe GOLD page shows the last stored values with STALE; next run per schedule.")


async def gold_job(job_id: str) -> None:
    """One scheduled run of a GOLD_JOBS entry: the enable/gate/pause checks, the freeze-window deferral for heavy jobs,
    the data-service call, one log line (quiet jobs: none).

    Schedule deviation from PLAN §c.3, deliberate (B2, wave 1): the plan writes `gold_overnight` as "03:10 daily
    (Tue–Sat; Mon for Friday's US session)" — a Tue–Sat run for the prior US session plus a Monday pass for files
    Saturday's run can miss (the CME final VOI, FRED's late Friday prints). The controller registers ONE Mon–Sat 03:10
    cron with the same group list every day instead of two triggers with different groups: Sunday (no US session on
    Saturday) is the only day skipped, Monday asks for everything again. The groups are idempotent and skip when
    nothing new is due, so the Monday pass costs one request. `gold_morning` and `gold_cme_daily` follow the same
    Mon–Sat rule (their Saturday run carries Friday's files)."""
    spec = GOLD_JOBS[job_id]
    if not (GOLD_JOBS_ENABLED and DATA_JOBS_ENABLED):
        return
    now = datetime.now(IST)
    if spec.gate is not None and not spec.gate(now):
        return
    if _time.time() < _GOLD_PAUSED_UNTIL:
        return                                     # data-service without the gold ingest: said once when the pause began
    if not spec.light and (slot := freeze_slot(now)) > now:
        _gold_defer(job_id, slot)
        return
    lock = _get_lock(job_id)
    if lock.locked():
        return
    async with lock, _track(job_id, quiet=spec.quiet):
        try:
            result = await _gold_ingest(job_id, gold_groups(job_id, now), quiet=spec.quiet)
        except GoldIngestUnavailable as exc:
            _mark_failed(job_id)
            _gold_warn_once("gold", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — a failed fetch is logged (and told once a day), never raised into the scheduler
            await _gold_failure(job_id, spec, exc)
            return
        if not spec.quiet:
            _log.info(job_id, gold_result_digest(result))


# ── COT: the weekly "who is long, who is short" ingest and the Saturday digest line ──────────────────────────
def cot_expected_report_date(now: datetime) -> date:
    """The Tuesday whose COT report has been released by `now`: the CFTC publishes Tuesday positions on Friday 15:30 ET
    (Sat 01:00 / 02:00 IST), so a Tuesday's report is expected from the Saturday after it (holiday-delayed Monday
    releases make the Sat run find nothing; the Mon/Tue 06:30 retries catch them)."""
    d = now.date()
    tue = d - timedelta(days=(d.weekday() - 1) % 7)       # the most recent Tuesday (today, if Tuesday)
    if (d - tue).days < 4:                                 # its report comes out on Saturday: last week's is current
        tue -= timedelta(days=7)
    return tue


def cot_report_date(cot: dict | None) -> str | None:
    """`latest.report_date` (YYYY-MM-DD) of a /api/gold/cot payload, else None."""
    latest = (cot or {}).get("latest")
    rd = latest.get("report_date") if isinstance(latest, dict) else None
    return str(rd)[:10] if rd else None


def _signed(v: float, unit: str = "", scale: float = 1.0, digits: int = 0) -> str:
    """+1,234 / −1,234 (U+2212, the terminal's convention) with an optional k-scale: _signed(104206, 'k', 1e3, 1) → +104.2k."""
    x = v / scale
    body = f"{abs(x):,.{digits}f}{unit}"
    return ("+" if x > 0 else "−" if x < 0 else "") + body


def _fmt_day(s: Any, with_weekday: bool = False) -> str:
    """'2026-10-20' / an ISO timestamp → '20 Oct' ('Tue 20 Oct' with the weekday); anything unparsable is shown as is."""
    try:
        d = date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return str(s)
    return f"{d:%a %d %b}" if with_weekday else f"{d:%d %b}"


def compose_cot_digest(cot: dict) -> str:
    """The Saturday Telegram line from ui-api's /api/gold/cot payload (PLAN §d shape): the funds' net and what they did
    this week, the fund-driver label, OI, the next release, and — only when positioning is at a historical extreme — a
    context note. Description only (G-STUDY: no forecasting power); no buy/sell words, no direction."""
    def block(key: str) -> dict[str, Any]:
        v = cot.get(key)
        return v if isinstance(v, dict) else {}

    latest, oi, crowd = block("latest"), block("open_interest"), block("crowd")
    groups = [g for g in (cot.get("groups") or []) if isinstance(g, dict)]
    mm: dict[str, Any] = next((g for g in groups if str(g.get("key", "")).lower() in ("mm", "managed_money")
                               or "managed" in str(g.get("label", "")).lower()), {})
    head = f"COT {_fmt_day(latest.get('report_date'))} (Tue positions"
    if latest.get("release_at"):
        head += f", released {_fmt_day(latest['release_at'], with_weekday=True)}"
    parts = [head + ")"]
    if mm.get("net") is not None:
        funds = f"funds net {_signed(float(mm['net']), 'k', 1e3, 1)}"
        if mm.get("chg_net") is not None:
            funds += f" ({_signed(float(mm['chg_net']), 'k', 1e3, 1)} w/w)"
        who = [s for w in (mm.get("who_did") or []) if w and (s := _context_only("gold_cot_weekly", w))]
        if who:
            funds += " — " + ", ".join(who)
        parts.append(funds)
    if driver := _context_only("gold_cot_weekly", cot.get("driver_label")):
        parts.append(driver)
    if oi.get("total") is not None:
        parts.append(f"OI {int(oi['total']):,}" + (f" ({_signed(float(oi['chg']))})" if oi.get("chg") is not None else ""))
    idx, z = crowd.get("cot_index_52"), crowd.get("z156")
    extreme = (idx is not None and (float(idx) >= 90 or float(idx) <= 10)) or (z is not None and abs(float(z)) >= 2)
    if extreme:
        where = "crowded" if (float(idx) if idx is not None else 50 + float(z or 0)) >= 50 else "washed-out"
        note = f"52-w COT index {float(idx):.0f}" if idx is not None else "positioning"
        if z is not None:
            note += f", z156 {float(z):+.1f}"
        parts.append(f"{note} — historically {where}; context only: no forecasting power 2006–2026 (G-STUDY)")
    if latest.get("next_release_ist"):
        parts.append(f"next {latest['next_release_ist']}")
    parts.append("explains the week — does not forecast")
    return " · ".join(parts)


async def _gold_cot_latest() -> dict | None:
    """ui-api GET /api/gold/cot?weeks=4 (PLAN §d) or None when it is not served (B3 not deployed) or unreachable."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{UI_API}/api/gold/cot", params={"weeks": 4})
    except Exception as exc:  # noqa: BLE001 — the ingest still runs; only the digest needs this
        _gold_warn_once("gold_cot_weekly", f"/api/gold/cot unreachable: {type(exc).__name__}", every_s=600)
        return None
    if r.status_code != 200:
        if r.status_code != 404:
            _gold_warn_once("gold_cot_weekly", f"/api/gold/cot → HTTP {r.status_code}", every_s=600)
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("latest"), dict) else None


async def gold_cot_weekly() -> None:
    """Sat 02:30 IST (hourly to 06:30) + Mon/Tue 06:30 — fetch the CFTC COT release (data-service group `cot`, which
    reads `report_date > max(report_date)` for the four datasets and stops when all carry the same new Tuesday). Skips
    when the expected Tuesday is already stored; sends the Saturday digest line once, when the week lands."""
    JOB = "gold_cot_weekly"
    spec = GOLD_JOBS[JOB]
    if not (GOLD_JOBS_ENABLED and DATA_JOBS_ENABLED):
        return
    now = datetime.now(IST)
    if _time.time() < _GOLD_PAUSED_UNTIL:
        return
    if (slot := freeze_slot(now)) > now:
        _gold_defer(JOB, slot)
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        expected = cot_expected_report_date(now).isoformat()
        before = cot_report_date(await _gold_cot_latest())
        if before is not None and before >= expected:
            _log.info(JOB, f"report of Tue {_fmt_day(expected)} already stored — nothing to fetch")
            return
        try:
            result = await _gold_ingest(JOB, spec.groups)
        except GoldIngestUnavailable as exc:
            _mark_failed(JOB)
            _gold_warn_once("gold", str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — logged + one Telegram line a day; the next retry is scheduled anyway
            await _gold_failure(JOB, spec, exc)
            return
        after_payload = await _gold_cot_latest()
        after = cot_report_date(after_payload)
        if after_payload is not None and after is not None and after >= expected:
            line = compose_cot_digest(after_payload)
            _log.info(JOB, line)
            await _alerts.info("COT weekly (context)", line)
        elif (n := gold_result_rows(result)) > 0:
            # rows landed but ui-api cannot show the week yet: B3's router not deployed (404) or still serving the
            # older week (its stored-read cache refreshes within 120 s) — the line says so instead of inventing numbers
            why = ("not served yet" if after_payload is None else f"still serving the {_fmt_day(after)} week")
            line = (f"COT: {n} new row(s) stored; the week is on GOLD › POSITIONING "
                    f"(ui-api /api/gold/cot {why}, so no digest numbers) · explains the week — does not forecast")
            _log.info(JOB, line)
            await _alerts.info("COT weekly (context)", line)
        else:
            _log.info(JOB, f"report of Tue {_fmt_day(expected)} not published yet "
                           f"({gold_result_digest(result)}); CFTC releases Fri 15:30 ET — retries per schedule")


# ── Downtime / start-up catch-up for the key gold jobs ─────────────────────────────────────────────────────
GOLD_TODAY_SLOTS: dict[str, tuple[tuple[int, ...], time]] = {     # job id → (weekdays it runs, IST slot) for "missed today?"
    "gold_overnight": ((0, 1, 2, 3, 4, 5), time(3, 10)),
    "gold_mcx_master": ((0, 1, 2, 3, 4), time(7, 35)),
}
GOLD_COT_SLOT = time(2, 30)                                           # Saturday


def _ist_naive(t: datetime) -> datetime:
    return (t.astimezone(IST) if t.tzinfo is not None else t).replace(tzinfo=None)


def _last_run_before(history: dict[str, dict[str, Any]], job: str, slot: datetime) -> bool:
    """True when the history shows no run of `job` at or after `slot` (never ran, unparsable, or older)."""
    row = history.get(job)
    if not row:
        return True
    try:
        last = _ist_naive(datetime.fromisoformat(str(row.get("last_run_ts"))))
    except (TypeError, ValueError):
        return True
    return last < slot


def read_job_history(root: Path) -> dict[str, dict[str, Any]] | None:
    """data/.scheduler_history.json's jobs, or None when the file is absent/unreadable (a first start: no evidence)."""
    try:
        raw = json.loads((root / "data" / SCHEDULER_HISTORY_FILE.name).read_text(encoding="utf-8"))
        jobs = raw.get("jobs") if isinstance(raw, dict) else None
        return {str(k): dict(v) for k, v in (jobs or {}).items() if isinstance(v, dict)}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def gold_missed_jobs(now: datetime, history: dict[str, dict[str, Any]] | None) -> list[str]:
    """The key gold jobs whose slot today (gold_overnight 03:10 Mon–Sat, gold_mcx_master 07:35 Mon–Fri) or this weekend
    (gold_cot_weekly Sat 02:30, checked Sat–Mon) has passed with no run since, per the persisted job history. No history
    (first ever start) → no evidence → nothing; a job the history never saw → never ran → listed. The ingest groups are
    idempotent, so a re-run that finds everything stored costs one request."""
    if history is None:
        return []
    t = _ist_naive(now)
    out = [job for job, (days, slot) in GOLD_TODAY_SLOTS.items()
           if t.weekday() in days and t.time() >= slot and _last_run_before(history, job, datetime.combine(t.date(), slot))]
    wd = t.weekday()
    if wd in (5, 6, 0):
        sat = datetime.combine(t.date() - timedelta(days=(wd - 5) % 7), GOLD_COT_SLOT)
        if t >= sat and _last_run_before(history, "gold_cot_weekly", sat):
            out.append("gold_cot_weekly")
    return out


async def gold_downtime_catchup(job_ids: list[str], backfill_from: str) -> str:
    """Re-run the key gold jobs missed during downtime with `backfill_from` (PLAN §c.3 catch-up). Each run is recorded
    in SYS and the persisted history like a scheduled one (_track: the next start must not list the job as missed
    again) and asks for every day-conditional group (gold_groups(..., backfill=True): the outage may have covered that
    weekday). A job whose lock is held (its scheduled run in flight) is WAITED for, never skipped — the run carrying
    backfill_from is the one that must happen. The COT job runs itself (it fetches everything after the last stored
    week and sends the digest). One summary line for the 'Stack was down' report."""
    JOB = "gold_downtime_catchup"
    parts: list[str] = []
    for job_id in job_ids:
        if not (GOLD_JOBS_ENABLED and DATA_JOBS_ENABLED):
            parts.append("gold jobs disabled")
            break
        if job_id == "gold_cot_weekly":
            await gold_cot_weekly()
            parts.append("gold_cot_weekly: ran (its own log line has the result)")
            continue
        if job_id in GOLD_SESSION_JOBS and not await _breeze_session_live():
            parts.append(f"{job_id}: not re-run (no live ICICI session now: sessions expire at midnight IST; the missed "
                         "settlement windows wait for a catch-up while a session is live)")
            continue
        async with _get_lock(job_id), _track(job_id):
            groups = gold_groups(job_id, datetime.now(IST), backfill=True)
            try:
                result = await _gold_ingest(job_id, groups, backfill_from=backfill_from)
                parts.append(f"{job_id}: ok ({gold_result_digest(result)})")
            except GoldIngestUnavailable as exc:
                _mark_failed(job_id)
                parts.append(f"{job_id}: {exc}")
                break
            except Exception as exc:  # noqa: BLE001 — the report must still go out
                _mark_failed(job_id)
                parts.append(f"{job_id}: FAILED {str(exc)[:120]}")
    # this catch-up is over: a job it skipped (gold_mcx_close without a live session) or never reached (disabled, data-
    # service without the gold package) has no catch-up pending any more; the ones it ran were cleared by _track
    _spend_catchups(set(job_ids))
    line = f"gold catch-up from {backfill_from}: " + "; ".join(parts)
    _log.info(JOB, line)
    return line


# ── The pre-open desk's two jobs (holiday-aware since the GOLD program) and the 08:45 wording ───────────────
def mcx_day_plan(day: date) -> dict[str, Any]:
    """How the MCX day shapes the desk's two jobs (shared/mcx_specs): the 08:45 snapshot needs a 09:00 open; the open is
    captured at 09:10, or at 17:10 on a morning-closure day (evening session only); nothing on full closures/weekends."""
    win = mcx_specs.trading_window(day)
    hol = mcx_specs.holiday_on(day)
    name, closure = hol if hol else (None, None)
    if win is None:
        return {"open": False, "holiday": name, "closure": closure or ("weekend" if day.weekday() >= 5 else "full"),
                "snapshot": False, "capture_at": None}
    morning = win[0].time() == mcx_specs.MORNING_OPEN
    return {"open": True, "holiday": name, "closure": closure, "snapshot": morning,
            "capture_at": "09:10" if morning else "17:10"}


def _gold_holiday_skip(job: str, plan: dict[str, Any], now: datetime) -> None:
    """Log the MCX-holiday skip once per job and day."""
    key = (job, now.date().isoformat())
    if key in _HOLIDAY_LOGGED:
        return
    _HOLIDAY_LOGGED.add(key)
    what = (f"MCX closed today ({plan['holiday']})" if not plan["open"]
            else f"MCX evening session only today ({plan['holiday']}): opens 17:00")
    _log.info(job, f"skipped: {what}")


def compose_gold_preopen_alert(row: dict[str, Any], stats: dict[str, Any] | None) -> str:
    """The 08:45 Telegram text: the fair open vs the settlement (labelled by its session when the desk says which), the
    house chase limit (the desk's `threshold` when the snapshot carries one, else the ₹300 default) named as the
    heuristic it is, and the model's measured miss so far — context, not a direction (PLAN §b, owner action O-14)."""
    fair = float(row["fair_open"])
    text = f"{row.get('contract') or 'GOLD'}: fair open ₹{fair:,.0f}"
    base = row.get("baseline")
    if base:
        label = _context_only("gold_preopen_snapshot", row.get("baseline_session_label"))
        if not label and row.get("baseline_session"):
            label = f"{_fmt_day(row['baseline_session'], with_weekday=True)} settlement"
        text += f" ({_signed(fair - float(base))} vs {label or 'settlement'} ₹{float(base):,.0f})"
    limit = float(row.get("threshold") or GOLD_CHASE_LIMIT_INR)
    text += f". Don't chase more than ₹{limit:,.0f} above it (house rule, heuristic: unproven)."
    if row.get("baseline_older_than_expected"):      # wave 1e M-D: e.g. Mon 9 Nov with no VWAP for the Sun 8 Nov Muhurat session
        note = str(row.get("baseline_note") or "baseline session older than expected")
        text += f" ⚠ {note[:1].upper()}{note[1:]}."
    st: dict[str, Any] = stats or {}
    days = int(st.get("days") or 0)
    if days and st.get("median_abs_error") is not None:
        med = float(st["median_abs_error"])
        p90 = st.get("p90_abs_error")
        text += (f" Model miss so far: median ₹{med:,.0f} over {days} day{'s' if days != 1 else ''}"
                 + (f" (p90 ₹{float(p90):,.0f})" if p90 is not None else "")
                 + " — describes past calls, not today's direction.")
    else:
        text += " No measured miss yet: the accuracy log has no completed day."
    return text


async def _gold_post(job: str, path: str) -> dict | None:
    """POST to the gold desk; a 4xx/5xx is logged (not alerted): the broker is often simply not connected."""
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(f"{UI_API}{GOLD_DESK_API}/{path}")
    if resp.status_code != 200:
        _log.warning(job, f"{path} → HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    return resp.json()


async def _gold_desk_stats(job: str) -> dict[str, Any] | None:
    """The accuracy log's stats block (median/mean/p90 miss, days) for the 08:45 line; None when unavailable."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{UI_API}{GOLD_DESK_API}/log", params={"days": 60})
        if r.status_code == 200:
            stats = r.json().get("stats")
            return stats if isinstance(stats, dict) else None
        _log.warning(job, f"log → HTTP {r.status_code}: no measured miss on the alert")
    except Exception as exc:  # noqa: BLE001 — the alert goes out without the miss
        _log.warning(job, f"log unavailable ({type(exc).__name__}): no measured miss on the alert")
    return None


async def gold_preopen_snapshot() -> None:
    """08:45 IST Mon–Fri — record the MCX GOLD fair open before the 09:00 open (accuracy log) and tell Telegram, with
    the measured miss so far. Skipped on full and morning-closure MCX holidays (no 09:00 open to call)."""
    JOB = "gold_preopen_snapshot"
    lock = _get_lock(JOB)
    if lock.locked() or not GOLD_LOG_ENABLED:
        return
    now = datetime.now(IST)
    plan = mcx_day_plan(now.date())
    if not plan["snapshot"]:
        _gold_holiday_skip(JOB, plan, now)
        return
    async with lock, _track(JOB):
        try:
            row = await _gold_post(JOB, "snapshot")
        except Exception as exc:  # noqa: BLE001 — ui-api down or the desk 503: logged, no alert (the desk shows it)
            _log.error(JOB, f"FAILED: {exc}")
            return
        if row:
            _log.info(JOB, f"fair_open={row['fair_open']} baseline={row.get('baseline')}")
            await _alerts.info("Gold pre-open", compose_gold_preopen_alert(row, await _gold_desk_stats(JOB)))


async def gold_open_capture(evening: bool = False) -> None:
    """09:10 IST Mon–Fri — store the actual MCX GOLD open from ICICI Breeze (if a session is live); the 17:10 run
    (`evening`) does it on morning-closure days, when the evening session is the day's first. Nothing on full closures."""
    JOB = "gold_open_capture_evening" if evening else "gold_open_capture"
    lock = _get_lock(JOB)
    if lock.locked() or not GOLD_LOG_ENABLED:
        return
    now = datetime.now(IST)
    plan = mcx_day_plan(now.date())
    if plan["capture_at"] != ("17:10" if evening else "09:10"):
        if not evening:
            _gold_holiday_skip(JOB, plan, now)
        return
    async with lock, _track(JOB):
        try:
            row = await _gold_post(JOB, "capture-open")
        except Exception as exc:  # noqa: BLE001 — Breeze not connected is the usual cause; the desk accepts a manual open
            _log.error(JOB, f"FAILED: {exc}")
            return
        if row and row.get("error") is not None:
            _log.info(JOB, f"open={row['actual_open']} fair={row.get('fair_open')} error={row['error']:+}")


# ══════════════════════════════════════════════════════════════════════════════
# Terminal v2 (reports/terminal_v2/PLAN.md Wave 0 0.5 / 0.9 and the Wave 1 jobs; builder B2). Every job here is a
# data-service fetch + compute behind B1's endpoints (/jobs/iv-eod, /jobs/iv-intraday, /jobs/index-drivers,
# /jobs/ingest-nse-files, /jobs/data-health) or a read of ui-api's /api/data/health (B3) — never a restart, never a call to
# a publisher from this process. Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket
# (PLAN §0.8): the only Telegram lines are data-health wording (a missed SLO, a state transition, the 08:35 digest).
# Freeze windows (PLAN §0.10): inside 07:45–09:20 / 18:30–21:15 only the light stored-data jobs run — the 19:25 drivers
# (stored data + 3 small GETs), the 20:30 pass's steps, the 08:35 sweep's few small GETs, the hourly health GET.
# A 404 from data-service (the packages not deployed there yet) pauses these jobs for an hour, said once.
# TERMINAL_JOBS_ENABLED=0 opts out of all of them (the existing 20:30 positions / FII-DII steps keep running).
# ══════════════════════════════════════════════════════════════════════════════
TERMINAL_JOBS_ENABLED = os.getenv("TERMINAL_JOBS_ENABLED", "1") == "1"
IV_EOD_PATH = "/jobs/iv-eod"                 # B1 fo_iv/api.py: ?job=iv_eod|iv_weekly|iv_backfill|vix_backfill + {date?,
                                             #   backfill_from?}
IV_INTRADAY_PATH = "/jobs/iv-intraday"       # B1: ?job=iv_intraday → {status: ok|skipped, reason?, calls, rows}
INDEX_DRIVERS_PATH = "/jobs/index-drivers"   # B1 index_drivers/api.py: ?job=index_drivers_daily + {date?}; result.top10.status
NSE_FILES_PATH = "/jobs/ingest-nse-files"    # B1: {datasets, from?, to?, revalidate} — If-Modified-Since → revision rows
DATA_HEALTH_JOB_PATH = "/jobs/data-health"   # B1 data_health/api.py: {since?, sessions, reason} → the explicit gap rows
DATA_HEALTH_API = "/api/data/health"         # B3 ui-api: rows[{id, state: live|fresh|amber|red|gap|unknown, as_of, job_id, note, …}]
TERMINAL_PAUSE_S = 3600
IV_EOD_SLO = time(21, 30)                    # PLAN 1.1: iv_eod stored by 21:30; a miss is one Telegram info line at 22:45
IV_INTRADAY_WINDOW = (time(9, 15), time(15, 30))
DATA_HEALTH_STATE_FILE = _ROOT / "data" / ".data_health_state.json"
HEALTH_RANK = {"live": 0, "fresh": 0, "amber": 1, "red": 2, "gap": 3}
# B1's fo_iv.jobs.EOD_FILES (the files iv_eod itself ingests) and the other verified evening files PLAN 1.4 puts in the
# 20:30 pass (nse_positions.TERMINAL_DATASETS); both lists are pinned against the data-service source in scripts/tests.
NSE_IV_FILES: tuple[str, ...] = ("index_ohlc_daily", "nse_fo_volt", "nse_contract_delta", "nse_combined_oi")
NSE_EVENING_FILES: tuple[str, ...] = ("nse_participant_vol", "nse_fii_stats", "nse_mwpl_clients")
# m112 (5 Nov review): the sweep's last run took 1,307,285 ms (21.8 min) for "≤ 6 light fetches". The log shows where:
# it was the 13:02 catch-up one-off after a restart (not the 08:35 slot), and ≈ 20 of the 21.8 minutes were
# /jobs/ingest-results (the 20:45 job's own work, 855 s that evening) — not a light fetch. So: the results step is left to
# the 20:45 capture whenever the sweep runs inside a freeze window (SWEEP_HEAVY_IN_WINDOW), and the controller stops
# WAITING after SWEEP_BUDGET_S (data-service finishes a running job on its own; the digest says so) and starts no further
# step; every step gets at least SWEEP_STEP_MIN_S of the budget.
SWEEP_BUDGET_S = float(os.getenv("SWEEP_BUDGET_S", "480"))
SWEEP_STEP_MIN_S = 30.0
SWEEP_HEAVY_IN_WINDOW: dict[str, str] = {"results": "left to the 20:45 capture (≈ 14 min: not a light fetch in the window)"}
SWEEP_MAX_JOBS = 6                           # the 08:35 sweep stays small: inside the morning window by design

_TERMINAL_PAUSED_UNTIL = 0.0
_IV_EOD_STATE: dict[str, Any] = {}           # {"date", "status", "reason", "at", "retry"} of the last iv_eod run
_DRIVERS_STATE: dict[str, Any] = {}          # {"date", "status", "top10_missing", "at"} of the last index_drivers_daily run
_IV_INTRADAY_DAY: dict[str, str] = {}        # the first stored tick of the day is logged once


class TerminalJobUnavailable(RuntimeError):
    """data-service answered 404: the Terminal v2 package behind that path is not deployed there (yet)."""


def _warn_hourly(job: str, kind: str, msg: str) -> None:
    """One WARNING per (job, reason) per hour under the job's own label: a 15-minute tick must not repeat itself, but a
    new reason (no session → budget refused) is still said once."""
    now = _time.time()
    key = f"{job}:{kind}"
    if now - _GOLD_LAST_WARNED.get(key, 0.0) >= 3600:
        _GOLD_LAST_WARNED[key] = now
        _log.warning(job, msg)


async def _terminal_job(job: str, path: str, body: dict | None = None, quiet: bool = False) -> dict:
    """POST a Terminal v2 data-service job and poll it to completion (B1's contract: `job` in the query and the body).
    A 404 pauses every terminal job for an hour (data-service mid-rollout) instead of an error every run."""
    global _TERMINAL_PAUSED_UNTIL
    if _time.time() < _TERMINAL_PAUSED_UNTIL:
        raise TerminalJobUnavailable(f"{path.split('?')[0]}: paused until the hour after data-service answered 404")
    try:
        return await _run_data_job(job, path, body or {}, quiet=quiet)
    except DataJobHTTPError as exc:
        if exc.status == 404:
            _TERMINAL_PAUSED_UNTIL = _time.time() + TERMINAL_PAUSE_S
            _gold_warn_once("terminal", f"data-service has no {path.split('?')[0]} (Terminal v2 package not deployed): "
                                        "the terminal jobs pause for an hour")
            raise TerminalJobUnavailable(f"data-service has no {path.split('?')[0]}") from exc
        raise


async def _data_health(job: str) -> dict[str, Any] | None:
    """ui-api's /api/data/health (B3; 60 s SWR over stored data, nothing fetched from a publisher), or None when it is not
    served yet / unreachable (said in the log, never an error into the scheduler)."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{UI_API}{DATA_HEALTH_API}")
        if r.status_code != 200:
            _log.warning(job, f"{DATA_HEALTH_API} → HTTP {r.status_code} (ui-api without the data-health view?)")
            return None
        d = r.json()
    except Exception as exc:  # noqa: BLE001
        _log.warning(job, f"{DATA_HEALTH_API} unreachable: {type(exc).__name__}: {exc}")
        return None
    return d if isinstance(d, dict) and isinstance(d.get("rows"), list) else None


def health_rows(health: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [r for r in ((health or {}).get("rows") or []) if isinstance(r, dict) and r.get("id")]


# ── iv_eod: the last step of the 20:30 pass, retried at 22:45, swept at 08:35 ───────────────────────────────
async def iv_eod_step(job: str, day: str, *, retry: bool = False) -> str:
    """POST /jobs/iv-eod?job=iv_eod for `day`: B1 parses the stored F&O file (≈ 3 s for all 224 underlyings), writes the
    three IV tables, VIX / index OHLC from the already-fetched ind_close_all, FOVOLT, Contract_Delta, the event ledger.
    Returns B1's status: `ok`, `not_yet` (the F&O file is not published yet — the 22:45 pass retries, then the 08:35
    sweep), `failed`, `unavailable` (404 pause) or `disabled`; never raises into the pass that called it."""
    if not TERMINAL_JOBS_ENABLED:
        return "disabled"
    res: dict[str, Any] = {}
    try:
        res = await _terminal_job(job, f"{IV_EOD_PATH}?job=iv_eod", {"job": "iv_eod", "date": day})
        status = str(res.get("status") or "ok")
        reason = str(res.get("reason") or "")
    except TerminalJobUnavailable as exc:
        status, reason = "unavailable", str(exc)
    except Exception as exc:  # noqa: BLE001 — the pass goes on; the retry and the SLO line carry the failure
        status, reason = "failed", f"{type(exc).__name__}: {str(exc)[:200]}"
    _IV_EOD_STATE.update(date=day, status=status, reason=reason, retry=retry,
                         at=datetime.now(IST).isoformat(timespec="seconds"))
    if status == "ok":
        iv: dict[str, Any] = res["iv"] if isinstance(res.get("iv"), dict) else {}
        _log.info(job, f"iv_eod {day}: expiry rows {iv.get('expiry_rows', '?')}, surface rows {iv.get('surface_rows', '?')}, "
                       f"summary rows {iv.get('summary_rows', '?')}" + (" (22:45 retry)" if retry else ""))
    else:
        _log.warning(job, f"iv_eod {day}: {status}" + (f" — {reason}" if reason else ""))
    return status


def iv_eod_missed(state: dict[str, Any], day: str) -> bool:
    """True when the IV store has no `ok` run for `day` (never ran today, `not_yet`, failed, paused)."""
    return state.get("date") != day or state.get("status") != "ok"


# ── index_drivers_daily: 19:25, the 20:35 retry when the top-10 file was not there ──────────────────────────
def top10_missing(result: Any) -> bool:
    """B1's result.top10.status (ingest_log.fetch_logged): `downloaded` / `cached` / `not_modified` / `revised` are there,
    `missing` / `error` / `parse_error` / `http_*` are not; no `top10` block at all → nothing to retry for."""
    top = result.get("top10") if isinstance(result, dict) else None
    if not isinstance(top, dict):
        return False
    st = str(top.get("status") or "")
    return st in ("missing", "error", "parse_error") or st.startswith("http_")


async def index_drivers_run(job: str, day: str, *, retry: bool = False) -> str:
    """POST /jobs/index-drivers?job=index_drivers_daily for `day`: the constituent lists (2 conditional GETs), the top-10
    weights file (1 GET; may not be published yet), then PIT weights, contributions, fit and driver state for NIFTY 50 and
    NIFTY BANK from stored data. Returns `ok` / `degraded` / `failed` / `unavailable`; the 20:35 retry re-runs the day when
    the top-10 file was missing."""
    if not TERMINAL_JOBS_ENABLED:
        return "disabled"
    res: dict[str, Any] = {}
    try:
        res = await _terminal_job(job, f"{INDEX_DRIVERS_PATH}?job=index_drivers_daily",
                                  {"job": "index_drivers_daily", "date": day})
        status = str(res.get("status") or "ok")
    except TerminalJobUnavailable as exc:
        status = "unavailable"
        _log.warning(job, f"index_drivers_daily {day}: {exc}")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        _log.error(job, f"index_drivers_daily {day} FAILED: {type(exc).__name__}: {str(exc)[:200]}")
    missing = top10_missing(res)
    _DRIVERS_STATE.update(date=day, status=status, top10_missing=missing, retry=retry,
                          at=datetime.now(IST).isoformat(timespec="seconds"))
    if status in ("ok", "degraded"):
        written = {ix: (v.get("written") or {}) for ix, v in (res.get("indices") or {}).items() if isinstance(v, dict)}
        top = (res.get("top10") or {}).get("status") if isinstance(res.get("top10"), dict) else "?"
        _log.info(job, f"index_drivers_daily {day}: {status}; top-10 file {top}"
                       + ("; the 20:35 retry re-runs the day" if missing and not retry else "")
                       + "; " + ", ".join(f"{ix} contributions +{w.get('contributions', 0)}" for ix, w in written.items()))
    return status


async def index_drivers_daily() -> None:
    """19:25 IST Mon–Fri (PLAN 1.2) — the day's index contributions. Inside the evening window by design: stored data plus
    three small conditional GETs, the same class as the 19:15 / 19:30 jobs. Retry at 20:35 inside nse_positions_catchup
    when NSE's top-10 file was not there yet."""
    JOB = "index_drivers_daily"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not (DATA_JOBS_ENABLED and TERMINAL_JOBS_ENABLED):
            return
        status = await index_drivers_run(JOB, datetime.now(IST).date().isoformat())
        if status in ("failed", "unavailable"):
            _mark_failed(JOB)
        _alerts_after_soon(JOB)                 # the driver / contribution rules (PLAN 2.3)


# ── the 22:45 pass (Wave 0 0.5) ───────────────────────────────────────────────────────────────────────────────
def revision_digest(result: Any) -> str:
    """One phrase from B1's /jobs/ingest-nse-files result: revised files, re-fetched files, misses."""
    if not isinstance(result, dict):
        return "no result"
    counts: dict[str, int] = {}
    files = result.get("files")
    rows: list[Any] = []
    if isinstance(files, dict):
        for v in files.values():
            rows += v if isinstance(v, list) else [v]
    elif isinstance(files, list):
        rows += files
    bh = result.get("nse_bhavcopy")
    if isinstance(bh, list):
        rows += bh
    for r in rows:
        if isinstance(r, dict):
            st = str(r.get("status") or "?")
            counts[st] = counts.get(st, 0) + 1
    return " ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to revalidate"


async def nse_evening_pass() -> None:
    """22:45 IST Mon–Fri (Wave 0 0.5; R-DATA §4's measured clock) — the late files: the MTF T−1 file (22:12), the equity
    bhavcopy re-publication (22:05; If-Modified-Since → a revision row, never an overwrite) and the evening files'
    revisions, a second FII/DII attempt (NSE serves one day), results release times, and the iv_eod retry when the 20:30
    pass found no F&O file. Outside both freeze windows. An iv_eod still missing its 21:30 SLO here is one Telegram
    info line (the 08:35 sweep tries again); nothing in this pass implies a direction."""
    JOB = "nse_evening_pass"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        lines: list[str] = []
        try:
            res = await _run_data_job(JOB, "/jobs/ingest-nse-positions", {})
            tables = res.get("tables", {})
            lines.append("positions " + ", ".join(f"{k.replace('nse_', '')}={v.get('last')}" for k, v in tables.items()
                                                  if isinstance(v, dict) and k in ("nse_mtf", "nse_fo_daily", "nse_deals")))
        except Exception as exc:  # noqa: BLE001
            _mark_failed(JOB)
            lines.append(f"positions FAILED {str(exc)[:160]}")
        today = datetime.now(IST).date().isoformat()
        closed = await _closed_today(JOB)        # an NSE holiday has no session files: no 'missing' rows for a non-session date
        if TERMINAL_JOBS_ENABLED and closed:
            lines.append("revisions: market closed today (no session files)")
        elif TERMINAL_JOBS_ENABLED:
            try:
                res = await _terminal_job(JOB, NSE_FILES_PATH, {"datasets": ["nse_bhavcopy", *NSE_IV_FILES, *NSE_EVENING_FILES],
                                                                "from": today, "to": today, "revalidate": True})
                lines.append("revisions " + revision_digest(res))
            except TerminalJobUnavailable as exc:
                lines.append(f"revisions: {exc}")
            except Exception as exc:  # noqa: BLE001
                _mark_failed(JOB)
                lines.append(f"revisions FAILED {str(exc)[:160]}")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(f"{DATA_SVC}/db/fii-dii-cash/refresh")
            lines.append(f"FII/DII HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"FII/DII failed {type(exc).__name__}")
        try:
            r2 = await _run_data_job(JOB, "/jobs/ingest-results", {"recent_events_days": 3, "max_age_days": 0})
            lines.append(f"results symbols={r2.get('symbols')} rows={r2.get('rows')}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"results FAILED {str(exc)[:160]}")
        try:                                     # review M10: rebuild this week's incomplete / missing wraps from what is stored now
            cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "daily_wrap.py"), "--base", UI_API, "--backfill-missing",
                   "--since", (datetime.now(IST).date() - timedelta(days=7)).isoformat(), "--until", today]
            wres = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=900, cwd=str(_ROOT),
                                           env={**os.environ, "PYTHONPATH": str(_ROOT)})
            last = (wres.stdout.strip().splitlines() or [""])[-1]       # (its own name: `res` above is a dict)
            rep = json.loads(last[7:]) if last.startswith("RESULT ") else {}
            lines.append(f"wraps rebuilt {len(rep.get('written') or [])}, still incomplete {len(rep.get('skipped') or {})}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"wraps FAILED {type(exc).__name__}")
        if not closed and TERMINAL_JOBS_ENABLED:
            if iv_eod_missed(_IV_EOD_STATE, today):
                status = await iv_eod_step(JOB, today, retry=True)
                lines.append(f"iv_eod retry {status}")
                if status != "ok":
                    reason = _IV_EOD_STATE.get("reason")
                    await _alerts.info("IV EOD missed its 21:30 SLO",
                                       f"{today}: {status}" + (f" — {reason}" if reason else "")
                                       + ". The 08:35 sweep tries again; OMON / DERV show the last stored day with STALE.")
            else:
                lines.append("iv_eod already ok")
        _log.info(JOB, "; ".join(lines))
        _alerts_after_soon(JOB)                 # FII/DII, results, a retried IV store: the stored-series rules


# ── the 08:35 sweep (Wave 0 0.5) and the data-health digest ───────────────────────────────────────────────
def _iso_plus(d: Any, days: int) -> str | None:
    try:
        return (date.fromisoformat(str(d)[:10]) + timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return None


def _span_body(job_id: str, row: dict[str, Any], multi: Any, last_session: str) -> dict[str, Any]:
    if multi:
        return {"job": job_id, "backfill_from": _iso_plus(row["as_of"], 1), "backfill_to": last_session}
    return {"job": job_id, "date": last_session}


NSE_FILE_DATASETS: frozenset[str] = frozenset((*NSE_IV_FILES, *NSE_EVENING_FILES))
NSE_FILES_MAX_SPAN_DAYS = 31                 # a catch-up span never asks NSE for more than a month of each file
SWEEP_FILES_MAX_SPAN_DAYS = 7                # the 08:35 sweep runs INSIDE the morning window: ≤ a week (≈ 5 sessions × ≤ 7 files,
                                             # ≈ 40 paced GETs); a longer hole is the start-up catch-up's (outside the windows)
# the sweep's execution order: fetch the files first, compute from them last (iv_eod / drivers read what the files wrote)
_SWEEP_ORDER = {"positions": 0, "bhavcopy": 1, "evening files": 2, "events": 3, "results": 4, "drivers": 5, "iv_eod": 6}


def plan_sweep(rows: list[dict[str, Any]], last_session: str) -> list[dict[str, Any]]:
    """The 08:35 sweep's work from the health rows (pure): one small data-service call per amber / red row whose ingest is
    a light NSE fetch, deduplicated, at most SWEEP_MAX_JOBS. Never the Yahoo refresh or the ML build (the 08:30 sync and
    tonight's 18:30 own those), never a gold job (its own catch-up), never a gap row (unrecoverable by definition), never a
    row that is not due yet (B3 keeps those `fresh`).

    The Wave 1.4 evening files and the IV input files (NSE_FILE_DATASETS: participant volumes, FII derivative stats, MWPL
    clients, combined OI, FOVOLT, Contract_Delta, the daily index file) are matched on the ROW ID, whatever job the
    catalog names for them (B1 lists nse_positions_catchup / iv_eod, whose own paths never fetch these files): ONE
    /jobs/ingest-nse-files step (B1's NseFilesRequest {datasets, from, to, revalidate}) for every such row, spanning
    from the day after the oldest stored as-of to the last session — so a missed night is re-fetched, not left as a
    permanent hole. `backfill_from` (iv_eod, drivers: B1's resumable backfill from the stored files) when more than one
    session is missing, else the last session's date. Steps run files-first, computations last."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    files: list[str] = []
    files_from: list[str] = []

    def add(label: str, path: str, body: dict[str, Any] | None = None, *, kind: str = "job") -> None:
        if path in seen or len(out) >= SWEEP_MAX_JOBS:
            return
        seen.add(path)
        out.append({"label": label, "path": path, "body": body or {}, "kind": kind})

    for r in rows:
        state, rid, job_id = str(r.get("state")), str(r.get("id")), str(r.get("job_id") or "")
        if state not in ("amber", "red") or rid.startswith("gold_") or r.get("unrecoverable"):
            continue
        lag = r.get("lag_sessions")
        multi = isinstance(lag, int) and lag > 1 and r.get("as_of")
        if rid in NSE_FILE_DATASETS:
            if rid not in files:
                files.append(rid)
            start = _iso_plus(r["as_of"], 1) if multi else last_session
            files_from.append(start or last_session)
            add("evening files", NSE_FILES_PATH)               # body filled below (one step for every file row)
        elif job_id == "nse_positions_catchup":
            add("positions", "/jobs/ingest-nse-positions")
        elif job_id == "results_capture_daily":
            add("results", "/jobs/ingest-results", {"recent_events_days": 3, "max_age_days": 0})
        elif job_id == "iv_eod":
            add("iv_eod", f"{IV_EOD_PATH}?job=iv_eod", _span_body("iv_eod", r, multi, last_session))
        elif job_id == "index_drivers_daily":
            add("drivers", f"{INDEX_DRIVERS_PATH}?job=index_drivers_daily",
                _span_body("index_drivers_daily", r, multi, last_session))
        elif job_id == "eod_data_pipeline" and rid == "nse_bhavcopy":
            add("bhavcopy", "/jobs/ingest-bhavcopy")
        elif job_id == "eod_data_pipeline" and rid == "nse_events":
            add("events", "/jobs/ingest-nse-events")
    for step in out:
        if step["path"] == NSE_FILES_PATH:
            floor = _iso_plus(last_session, -SWEEP_FILES_MAX_SPAN_DAYS) or last_session
            step["body"] = {"job": "nse_files", "datasets": files, "from": max(min(files_from), floor), "to": last_session,
                            "revalidate": False}
    out.sort(key=lambda st: _SWEEP_ORDER.get(st["label"], 9))
    return out


def health_digest(health: dict[str, Any]) -> str:
    """The 08:35 Telegram line: counts, then every row that is not green with its honest note (B3's wording: stored
    date · expected by · sessions behind). Description only — no direction, no score."""
    s: dict[str, Any] = health["summary"] if isinstance(health.get("summary"), dict) else {}
    rows = health_rows(health)
    unknown = f" · {s['unknown']} unknown" if s.get("unknown") else ""
    head = (f"{s.get('green', 0)} green · {s.get('amber', 0)} amber · {s.get('red', 0)} red · {s.get('gaps', 0)} gap{unknown}"
            f" of {s.get('rows', len(rows))} datasets (last session {health.get('last_session', '?')})")
    bad = [r for r in rows if r.get("state") in ("amber", "red", "gap")]
    bad.sort(key=lambda r: (-HEALTH_RANK.get(str(r.get("state")), 0), str(r.get("id"))))
    lines = [f"{r['state'].upper()} {r['id']}: {r.get('note') or ''}".rstrip(": ") for r in bad[:10]]
    if len(bad) > 10:
        lines.append(f"… and {len(bad) - 10} more on SYS › DATA")
    return "\n".join([head, *lines])


async def morning_sweep() -> None:
    """08:35 IST Mon–Fri (Wave 0 0.5) — anything still missing from last night, read from ui-api's /api/data/health (B3):
    each amber / red row whose ingest is a small NSE fetch is re-run once for the session it lacks (plan_sweep); then
    the day's data-health digest, one Telegram info line. Inside the 07:45–09:20 window by design: stored-data reads and
    at most SWEEP_MAX_JOBS small GET-only jobs, no restart, no Yahoo, no ML build, no gold."""
    JOB = "morning_sweep"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        health = await _data_health(JOB)
        if health is None:
            _log.warning(JOB, "no data-health view: nothing swept, no digest")
            return
        outcomes: list[str] = []
        plan = plan_sweep(health_rows(health), str(health.get("last_session") or datetime.now(IST).date().isoformat()))
        if in_freeze_window(datetime.now(IST)):
            outcomes += [f"{st['label']} {SWEEP_HEAVY_IN_WINDOW[st['label']]}" for st in plan if st["label"] in SWEEP_HEAVY_IN_WINDOW]
            plan = [st for st in plan if st["label"] not in SWEEP_HEAVY_IN_WINDOW]
        t0 = _time.monotonic()
        for step in plan:
            left = SWEEP_BUDGET_S - (_time.monotonic() - t0)
            if left <= 0:                         # m112: the sweep sits inside the 07:45–09:20 window; it stops waiting
                outcomes.append(f"{step['label']} not started (the {SWEEP_BUDGET_S // 60:.0f}-min sweep budget is spent; "
                                "the 20:30 pass fetches it)")
                continue
            try:
                terminal = step["path"].startswith(("/jobs/iv-", "/jobs/index-", NSE_FILES_PATH))
                coro = (_terminal_job(JOB, step["path"], step["body"]) if terminal
                        else _run_data_job(JOB, step["path"], step["body"]))
                res = await asyncio.wait_for(coro, timeout=max(SWEEP_STEP_MIN_S, left))
                st = str(res.get("status") or "ok") if isinstance(res, dict) else "ok"
                outcomes.append(f"{step['label']} {st}")
            except asyncio.TimeoutError:
                outcomes.append(f"{step['label']} still running in data-service after the sweep budget (not waited for)")
            except TerminalJobUnavailable as exc:
                outcomes.append(f"{step['label']} unavailable ({exc})")
            except Exception as exc:  # noqa: BLE001 — the digest still goes out
                _mark_failed(JOB)
                outcomes.append(f"{step['label']} FAILED {str(exc)[:120]}")
        if any(r.get("id") == "nse_fii_dii_cash" and r.get("state") in ("amber", "red") for r in health_rows(health)):
            try:                                      # NSE's API still serves yesterday's provisional figure this morning
                async with httpx.AsyncClient(timeout=60) as client:
                    r = await client.post(f"{DATA_SVC}/db/fii-dii-cash/refresh")
                outcomes.append(f"FII/DII HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                outcomes.append(f"FII/DII failed {type(exc).__name__}")
        if plan or outcomes:
            _log.info(JOB, "swept: " + "; ".join(outcomes))
            health = await _data_health(JOB) or health
        else:
            _log.info(JOB, "nothing missing from last night")
        body = health_digest(health) + ("\nSweep: " + "; ".join(outcomes) if outcomes else "")
        await _alerts.info("DATA 08:35 digest", body)


# ── the hourly data-health check: one Telegram line per transition ───────────────────────────────────────────
def read_health_state(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        states = raw.get("states") if isinstance(raw, dict) else None
        return {str(k): str(v) for k, v in (states or {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def write_health_state(path: Path, states: dict[str, str], now: datetime | None = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": (now or datetime.now(IST)).isoformat(timespec="seconds"), "states": states}, indent=0))
        tmp.replace(path)
    except OSError:
        pass


def health_transitions(prev: dict[str, str], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Every dataset whose state class moved since the last check (green ⇄ amber ⇄ red, or into / out of gap). A dataset
    seen for the first time is reported only when it is red or a gap (no flood of green lines at the first run)."""
    out: list[dict[str, str]] = []
    for r in rows:
        rid, new = str(r.get("id")), str(r.get("state") or "")
        if new not in HEALTH_RANK:
            continue
        old = prev.get(rid)
        if old is None:
            if HEALTH_RANK[new] >= HEALTH_RANK["red"]:
                out.append({"id": rid, "from": "new", "to": new, "note": str(r.get("note") or ""), "worse": "1"})
            continue
        if HEALTH_RANK.get(old, 0) == HEALTH_RANK[new]:
            continue
        out.append({"id": rid, "from": old, "to": new, "note": str(r.get("note") or ""),
                    "worse": "1" if HEALTH_RANK[new] > HEALTH_RANK.get(old, 0) else ""})
    return out


async def data_health_check() -> None:
    """Hourly (PLAN 1.4) — read ui-api's /api/data/health; one Telegram line per state transition since the last check
    (warning channel when a dataset worsened, info when it recovered), nothing when nothing moved. The state lives in
    data/.data_health_state.json so a restart does not repeat the lines. A GET of stored data: runs inside the windows.
    The dead-man ping stays the only alert that works when the Mac is off."""
    JOB = "data_health_check"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB, quiet=True):
        health = await _data_health(JOB)
        if health is None:
            return
        rows = health_rows(health)
        prev = read_health_state(DATA_HEALTH_STATE_FILE)
        moved = health_transitions(prev, rows)
        states = {**prev, **{str(r["id"]): str(r.get("state")) for r in rows if r.get("state") in HEALTH_RANK}}
        write_health_state(DATA_HEALTH_STATE_FILE, states)
        if moved and not (time(9, 15) <= datetime.now(IST).time() <= time(15, 30)):
            _alerts_after_soon(JOB)             # data_stale rules (in session the per-minute round covers them)
        if not moved:
            return
        lines = [f"{t['id']}: {t['from']} → {t['to']}" + (f" ({t['note']})" if t["note"] else "") for t in moved]
        _log.info(JOB, "transitions: " + "; ".join(lines))
        worse = [t for t in moved if t["worse"]]
        title = f"DATA: {len(moved)} dataset{'s' if len(moved) != 1 else ''} changed state"
        if worse:
            await _alerts.warning(title, "\n".join(lines) + "\nSYS › DATA has every row; catch-up per schedule.")
        else:
            await _alerts.info(title, "\n".join(lines))


# ── iv_intraday (pilot) and iv_weekly ─────────────────────────────────────────────────────────────────────────
def iv_intraday_due(now: datetime) -> bool:
    """Trading weekdays 09:20–15:30 IST (the cron fires 09:05 too: that tick is skipped here)."""
    return now.weekday() < 5 and IV_INTRADAY_WINDOW[0] <= now.time() <= IV_INTRADAY_WINDOW[1]


async def _breeze_session_live() -> bool:
    """data-service's ICICI provider holds a live session (the same flag the 08:00 login verifies); a cheap local GET."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{DATA_SVC}/provider/status")
        return bool(r.status_code == 200 and r.json().get("connected"))
    except Exception:  # noqa: BLE001
        return False


async def iv_intraday_tick() -> None:
    """Every 15 min 09:20–15:30 IST Mon–Fri (PLAN 1.1 pilot): one POST /jobs/iv-intraday — data-service takes the Breeze
    chain snapshots (NIFTY + BANKNIFTY near + next expiry, both sides, the F&O watchlist) through B3's budget ledger and
    never unmetered. Skipped here without a request outside the window, on an NSE holiday and when data-service holds no
    live Breeze session; data-service's own `skipped` (budget refused, no stored expiries) is logged at most once an hour
    and never reaches Telegram. Quiet: 25 runs a day write no Finished line."""
    JOB = "iv_intraday"
    if not (TERMINAL_JOBS_ENABLED and DATA_JOBS_ENABLED):
        return
    now = datetime.now(IST)
    if not iv_intraday_due(now):
        return
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB, quiet=True):
        if not await _breeze_session_live():
            _warn_hourly(JOB, "session", "skipped: data-service holds no live Breeze session (the 08:00 login did not land?)")
            return
        try:
            res = await _terminal_job(JOB, f"{IV_INTRADAY_PATH}?job=iv_intraday", {"job": "iv_intraday"}, quiet=True)
        except TerminalJobUnavailable:
            _mark_failed(JOB)
            return
        except Exception as exc:  # noqa: BLE001 — a failed tick is logged once an hour, never raised, never a Telegram line
            _mark_failed(JOB)
            _warn_hourly(JOB, "failed", f"FAILED: {type(exc).__name__}: {str(exc)[:200]}")
            return
        if str(res.get("status")) == "skipped":
            if res.get("quiet"):                          # nothing due at this tick (the tier cadence): not a warning
                return
            _warn_hourly(JOB, "skipped", f"skipped by data-service: {res.get('reason')}")
            return
        day = now.date().isoformat()
        if _IV_INTRADAY_DAY.get("day") != day:
            _IV_INTRADAY_DAY["day"] = day
            _log.info(JOB, f"first tick stored at {now:%H:%M}: calls={res.get('calls')} rows={res.get('rows')}")


async def iv_weekly() -> None:
    """Sat 03:00 IST (PLAN 1.1): recompute the 252-session IV rank / percentile windows after late corrections and run
    B1's dataset_catalog check. After the 02:15 backup's 20-minute limit, before the 03:10 gold overnight."""
    JOB = "iv_weekly"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not (DATA_JOBS_ENABLED and TERMINAL_JOBS_ENABLED):
            return
        try:
            res = await _terminal_job(JOB, f"{IV_EOD_PATH}?job=iv_weekly", {"job": "iv_weekly"})
            _log.info(JOB, f"ranks recomputed for {res.get('ranks_recomputed')} symbol-days; "
                           f"catalog rows {res.get('catalog_rows')}")
        except TerminalJobUnavailable as exc:
            _mark_failed(JOB)
            _log.warning(JOB, str(exc))
        except Exception as exc:  # noqa: BLE001
            _mark_failed(JOB)
            _log.error(JOB, f"FAILED: {type(exc).__name__}: {str(exc)[:300]}")
            await _alerts.info("IV weekly recompute failed",
                               f"{str(exc)[:200]}\nOMON / DERV keep last week's rank windows; next run Saturday 03:00.")


# ── "missed today?" for the terminal jobs (read at start-up like the gold ones) ───────────────────────────
TERMINAL_TODAY_SLOTS: dict[str, tuple[tuple[int, ...], time]] = {     # job id → (weekdays it runs, IST slot)
    "morning_sweep": ((0, 1, 2, 3, 4), time(8, 35)),
    "index_drivers_daily": ((0, 1, 2, 3, 4), time(19, 25)),
    "nse_positions_catchup": ((0, 1, 2, 3, 4), time(20, 30)),
    "results_capture_daily": ((0, 1, 2, 3, 4), time(20, 45)),
    "nse_evening_pass": ((0, 1, 2, 3, 4), time(22, 45)),
}
IV_WEEKLY_SLOT = time(3, 0)                                            # Saturday; checked Sat–Sun
# a missed 08:35 sweep is worth a one-off only until the evening window opens: from 18:30 the 20:30 / 22:45 passes re-fetch
# last night's files themselves, and a sweep there would race the EOD pipeline's own ingests (check:B2-CTRL; this also
# keeps the first deploy evening (≥ 21:30) from firing a sweep + DATA digest)
MORNING_SWEEP_LAST = time(18, 30)
# terminal one-offs that are fetch passes: moved out of a freeze window like the non-light gold jobs (freeze_slot)
TERMINAL_ONEOFF_DEFER: tuple[str, ...] = ("morning_sweep", "nse_positions_catchup")


def terminal_missed_jobs(now: datetime, history: dict[str, dict[str, Any]] | None) -> list[str]:
    """The terminal jobs whose slot today (TERMINAL_TODAY_SLOTS) or this weekend (iv_weekly Sat 03:00) has passed with no
    run since, per the persisted job history; no history → no evidence → nothing (as gold_missed_jobs)."""
    if history is None:
        return []
    t = _ist_naive(now)
    out = [job for job, (days, slot) in TERMINAL_TODAY_SLOTS.items()
           if t.weekday() in days and t.time() >= slot and _last_run_before(history, job, datetime.combine(t.date(), slot))
           and not (job == "morning_sweep" and t.time() >= MORNING_SWEEP_LAST)]
    if t.weekday() in (5, 6):
        sat = datetime.combine(t.date() - timedelta(days=t.weekday() - 5), IV_WEEKLY_SLOT)
        if t >= sat and _last_run_before(history, "iv_weekly", sat):
            out.append("iv_weekly")
    return out


def nse_files_span(since: str, now: datetime) -> tuple[str, str] | None:
    """[from, to] for the catch-up's /jobs/ingest-nse-files (pure): from the heartbeat's day (the first session the stack
    may have missed; capped at NSE_FILES_MAX_SPAN_DAYS back) to the last weekday whose evening files are out — today only
    once the 20:30 pass's slot has passed (the F&O-era files land by 20:10), else the previous weekday. None when the span
    is empty (down and up again inside one evening before its files)."""
    try:
        start = date.fromisoformat(since[:10])
    except ValueError:
        return None
    t = _ist_naive(now)
    end = t.date() if t.time() >= time(20, 30) else t.date() - timedelta(days=1)
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    start = max(start, end - timedelta(days=NSE_FILES_MAX_SPAN_DAYS))
    if start > end:
        return None
    return start.isoformat(), end.isoformat()


# the jobs the start-up data catch-up re-runs itself after downtime (0.9): their "missed today" one-offs are left to it
TERMINAL_CATCHUP_OWNED: tuple[str, ...] = ("nse_positions_catchup", "index_drivers_daily", "results_capture_daily")


async def _terminal_downtime_catchup(job: str, since: str, missed: dict[str, int], mode: str) -> list[str]:
    """Wave 0 0.9: after the data steps of the start-up catch-up (full / nse modes) — the positions files (the 18:30
    pipeline is equity-only now), results release times with a window of the days down + 3, the index valuation history,
    the NSE evening + IV input files and the equity bhavcopy revisions for every session of the outage
    (/jobs/ingest-nse-files over `nse_files_span`: the positions ingest caches only the legacy F&O / participant-OI /
    deals / MTF files, so without this the IV backfill would lack FOVOLT / Contract_Delta / the index file and the evening
    tables would keep a permanent hole), THEN the IV store and the drivers with `backfill_from` (B1 resumes from those
    stored files), the explicit gap rows for the sessions nothing captured (pre-open, internals, FII/DII, gold open —
    B1's data_gaps), then the Desk mark and the S1 shadow when their 19:30 / 19:50 runs were missed (both replay every
    missed session from stored closes; rules unchanged). One phrase per step for the 'Stack was down' report."""
    lines: list[str] = []
    now = datetime.now(IST)
    try:
        days_down = max(0, (now.date() - date.fromisoformat(since[:10])).days)
    except ValueError:
        days_down = 0
    if mode == "full":
        try:
            res = await _run_data_job(job, "/jobs/ingest-nse-positions", {})
            lines.append("NSE positions: ok through " + ", ".join(f"{k.replace('nse_', '')}={v.get('last')}" for k, v in
                                                                 (res.get("tables") or {}).items() if isinstance(v, dict))[:160])
        except Exception as exc:  # noqa: BLE001
            lines.append(f"NSE positions: FAILED {str(exc)[:120]}")
    if missed.get("results_capture_daily"):
        try:
            res = await _run_data_job(job, "/jobs/ingest-results", {"recent_events_days": days_down + 3, "max_age_days": 0})
            lines.append(f"results release times ({days_down + 3}-day window): symbols={res.get('symbols')} "
                         f"rows={res.get('rows')}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"results release times: FAILED {str(exc)[:120]}")
    if missed.get("index_valuation_daily"):
        await index_valuation_daily(recent=max(10, days_down + 5))
        lines.append("index valuation: re-run")
    if TERMINAL_JOBS_ENABLED:
        span = nse_files_span(since, now)
        steps: list[tuple[str, str, dict[str, Any]]] = []
        if span is not None:
            steps.append(("NSE files", NSE_FILES_PATH, {"job": "nse_files", "datasets": ["nse_bhavcopy", *NSE_IV_FILES, *NSE_EVENING_FILES],
                                                        "from": span[0], "to": span[1], "revalidate": True}))
        for label, path, body in (*steps, ("drivers", f"{INDEX_DRIVERS_PATH}?job=index_drivers_daily",
                                   {"job": "index_drivers_daily", "backfill_from": since[:10]}),
                                  ("IV store", f"{IV_EOD_PATH}?job=iv_eod", {"job": "iv_eod", "backfill_from": since[:10]}),
                                  ("gap rows", DATA_HEALTH_JOB_PATH,
                                   {"job": "data_health_refresh", "since": since[:10],
                                    "reason": f"stack down from {since[:10]} (no capture)"})):
            try:
                res = await _terminal_job(job, path, body)
                if label == "gap rows":
                    found = (res.get("gap_scan") or {}).get("gaps") or {}
                    gaps = [f"{k} {', '.join(v)}" for k, v in found.items() if v] if isinstance(found, dict) else []
                    lines.append("gap rows: " + ("; ".join(gaps) if gaps else "none (every session captured)"))
                elif label == "NSE files":
                    lines.append(f"NSE files {body['from']} → {body['to']}: {revision_digest(res)}")
                else:
                    days = res.get("days")
                    lines.append(f"{label}: {res.get('status', 'ok')} from {since[:10]}"
                                 + (f" ({days} day(s))" if days is not None else ""))
            except TerminalJobUnavailable as exc:
                lines.append(f"{label}: {exc}")
                break
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{label}: FAILED {str(exc)[:120]}")
    # the Desk and the shadow: each run's own SYS status, and a failed Desk (desk_daily raises) never stops the shadow or
    # the 'Stack was down' report (6 Nov checker: a failed run must never read as a replay)
    for job_id, label, slot, func in (("desk_daily", "Desk mark", "19:30", desk_daily),
                                      ("alpha_shadow_daily", "S1 shadow", "19:50", alpha_shadow_daily)):
        if not missed.get(job_id):
            continue
        t0 = datetime.now(IST)
        try:
            await func()
            st = _status_since(job_id, t0)
            lines.append(f"{label}: re-run ({st}; its {slot} run was missed)" if st
                         else f"{label}: re-run requested, no run recorded")
        except Exception as exc:  # noqa: BLE001 — the next job and the report must still happen
            lines.append(f"{label}: re-run FAILED {type(exc).__name__}: {str(exc)[:100]}")
    return lines


async def results_capture_daily() -> None:
    """20:45 IST Mon–Fri — store release times of results announced in the last 3 days (ERN, PEAD research)."""
    JOB = "results_capture_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        try:
            r = await _run_data_job(JOB, "/jobs/ingest-results", {"recent_events_days": 3, "max_age_days": 0})
            _log.info(JOB, f"symbols={r.get('symbols')} rows={r.get('rows')} empty={r.get('empty_count')}")
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


async def preopen_capture() -> None:
    """09:09 IST Mon–Fri — read NSE's final pre-open book (F&O and all stocks); data-service archives it to
    data/nse_archive/preopen/ (order imbalance is not in any EOD file, so it is lost unless captured)."""
    JOB = "preopen_capture"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                for key in ("FO", "ALL"):
                    r = await client.get(f"{DATA_SVC}/db/preopen", params={"key": key})
                    r.raise_for_status()
                    d = r.json()
                    _log.info(JOB, f"{key}: {len(d.get('rows', []))} stocks, book {d.get('timestamp')}")
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


_NOTIFY_LOG = _ROOT / "data" / "notifications.jsonl"


def _record_notification(kind: str, title: str, body: str) -> None:
    """Append to data/notifications.jsonl (the header bell's inbox in the UI); trimmed to the last 1,000."""
    try:
        _NOTIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _NOTIFY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(IST).isoformat(timespec="seconds"), "kind": kind,
                                 "title": title, "body": body[:400]}) + "\n")
        if _NOTIFY_LOG.stat().st_size > 400_000:
            lines = _NOTIFY_LOG.read_text(encoding="utf-8").splitlines()[-1000:]
            _NOTIFY_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


_APP_SINK = Path(os.environ.get(
    "SURYADHANA_NOTIFY_SINK",
    str(Path.home() / "Library" / "Application Support" / "ai.suryadhana.terminal" / "notify-sink.alive")))


def _app_is_notification_sink(max_age_s: float = 180.0) -> bool:
    """SuryaDhana.app shows the notification feed as native banners while it touches this file (at most once a
    minute, only after a successful poll of /api/notifications/feed): then the osascript banner would be a duplicate
    shown as 'Script Editor'. osascript stays the fallback when the app is closed or the feed is not served."""
    try:
        return _time.time() - _APP_SINK.stat().st_mtime < max_age_s
    except OSError:
        return False


def _notify_mac(title: str, body: str, kind: str = "alert") -> None:
    """macOS desktop notification: the alert channel that works before Telegram is configured (local stack only).
    Every notification is also recorded for the UI's inbox (and the app's notification feed)."""
    _record_notification(kind, title, body)
    if sys.platform != "darwin" or _app_is_notification_sink():
        return
    script = f"display notification {json.dumps(body[:220])} with title {json.dumps(title)} sound name \"Glass\""
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], timeout=10, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ── Alerts: the price levels and the typed alert engine (Terminal v2 PLAN 2.3, W2-ALERTS) ──────────────────────
# ui-api owns the rules, the evaluation and the fire queue (routers/alerts.py + the pure services/ui-api/alert_engine.py);
# the controller only asks and delivers. The ask is the same per-minute POST /api/alerts/run the price alerts have used
# since October, with W2-ALERTS' `scope` (all | live | eod: stored series only, no quote reads) and `dispatch=1`: the
# answer's "dispatch" list holds every fire not announced yet (price + typed, each AT MOST once, ≤ 30 min old) with its
# title, Telegram title, text and channel (mac | telegram | both). An older ui-api returns no "dispatch": the legacy
# price hits are announced as before. Outside the session the stored-series rules are evaluated after each EOD step
# (alerts_after: the 18:30 pipeline, the 19:25 drivers, the 20:30 pass with iv_eod, the 22:45 pass, the hourly data
# health). No alert implies a direction (PLAN §0.1): a relayed text with a direction word is withheld, never quoted.
ALERTS_RUN_PATH = "/api/alerts/run"
ALERTS_RULES_PATH = "/api/alerts/rules"
ALERTS_FROM_TEXT_PATH = "/api/alerts/rules/from-text"
ALERT_DIRECTION_WORDS = re.compile(r"\b(bullish|bearish|buy(s|ing)?|sell(s|ing)?|go long|go short|target|forecast\w*|"
                                   r"overbought|oversold|breakout|breakdown)\b", re.IGNORECASE)


def alert_text_or_withheld(item: dict[str, Any]) -> str:
    """The fire's text for the Mac / Telegram, or a neutral line when it carries a direction word (defence in depth:
    W2-ALERTS' templates and notes are scanned there already)."""
    text = str(item.get("text") or "").strip()
    if text and not ALERT_DIRECTION_WORDS.search(text):
        return text
    who = str(item.get("symbol") or item.get("rule_id") or "alert")
    return f"{who}: an alert rule's condition was met (its text was withheld: it carried a direction word; see ALRT)"


def alert_deliveries(item: dict[str, Any]) -> list[tuple[str, str, str]]:
    """[(channel, title, text)] for one dispatch item: 'mac' → the Mac notification + inbox, 'telegram' → Telegram,
    'both' (and anything unknown: never silently dropped) → both. Pure."""
    text = alert_text_or_withheld(item)
    ch = str(item.get("channel") or "both")
    out: list[tuple[str, str, str]] = []
    if ch in ("mac", "both") or ch not in ("mac", "telegram"):
        out.append(("mac", str(item.get("title") or "SuryaDhana alert"), text))
    if ch in ("telegram", "both") or ch not in ("mac", "telegram"):
        out.append(("telegram", str(item.get("telegram_title") or "Alert"), text))
    return out


async def _deliver_alerts(job: str, items: list[dict[str, Any]]) -> int:
    n = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = "price" if item.get("origin") == "price" else "alert"
        for channel, title, text in alert_deliveries(item):
            if channel == "mac":
                _log.info(job, text)
                await asyncio.to_thread(_notify_mac, title, text, kind)
            else:
                await _alerts.info(title, text)
        n += 1
    return n


async def alerts_dispatch(job: str, scope: str = "all") -> dict[str, Any]:
    """One evaluation + delivery round (POST /api/alerts/run?scope=…&dispatch=1). Returns ui-api's answer."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{UI_API}{ALERTS_RUN_PATH}", params={"scope": scope, "dispatch": "1"})
    r.raise_for_status()
    res = r.json()
    if isinstance(res.get("dispatch"), list):
        await _deliver_alerts(job, res["dispatch"])
    else:
        for h in res.get("hits", []):              # an older ui-api: the price levels only, announced as before
            if h["side"] == "move":
                text = f"{h['sym']} {h['change_pct']:+.1f}% today (alert at ±{h['level']:g}%, now ₹{h['price']:,.2f})"
            else:
                text = (f"{h['sym']} {'rose above' if h['side'] == 'above' else 'fell below'} "
                        f"₹{h['level']:,.2f} (now ₹{h['price']:,.2f})")
            _log.info(job, text)
            await asyncio.to_thread(_notify_mac, "SuryaDhana price alert", text, "price")
            await _alerts.info("Price alert", text)
    if res.get("rules_error"):
        _gold_warn_once(f"{job}:rules", f"typed alert rules not evaluated: {str(res['rules_error'])[:200]}")
    return res


async def price_alerts_check() -> None:
    """Every minute, Mon–Fri 09:15–15:30 IST — price the WTCH alert levels and evaluate the typed rules (ui-api), and
    announce what fired on the Mac and on Telegram (when configured). Price levels are one-shot; ui-api removes a
    crossed level. The job id stays price_alerts_check (SYS, the gates)."""
    JOB = "price_alerts_check"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    now = datetime.now(IST)
    if not ((9, 15) <= (now.hour, now.minute) <= (15, 30)):
        return
    async with lock:
        try:
            await alerts_dispatch(JOB, "all")
        except Exception as exc:
            _log.warning(JOB, f"check failed: {type(exc).__name__}: {exc}")


ALERTS_EOD_LOCK = "alerts_after_eod"


async def alerts_after(step: str) -> None:
    """After an EOD step stored new rows: evaluate the stored-series rules once (scope=eod: no quote reads) and deliver.
    Never raises into the step; one at a time (a second call while one runs is skipped: the running one sees the rows)."""
    if not ALERTS_ENGINE_ENABLED:
        return
    lock = _get_lock(ALERTS_EOD_LOCK)
    if lock.locked():
        return
    async with lock:
        try:
            res = await alerts_dispatch(ALERTS_EOD_LOCK, "eod")
            n = len(res.get("dispatch") or []) if isinstance(res, dict) else 0
            if n:
                _log.info(ALERTS_EOD_LOCK, f"after {step}: {n} alert(s) delivered")
        except Exception as exc:  # noqa: BLE001 — an alert round never fails the data step
            _gold_warn_once(ALERTS_EOD_LOCK, f"after {step}: alert round failed: {type(exc).__name__}: {str(exc)[:160]}")


ALERTS_ENGINE_ENABLED = os.getenv("ALERTS_ENGINE_ENABLED", "1") == "1"


def _alerts_after_soon(step: str) -> None:
    """Fire-and-forget alerts_after(step) from inside a job (the job's own lock and latency are not held by it)."""
    try:
        task = asyncio.get_running_loop().create_task(alerts_after(step))
    except RuntimeError:
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


FILING_ALERT_CATS = {"results", "orders", "rating", "m&a", "insider", "capital", "board"}
_FILINGS_SEEN = _ROOT / "data" / "filing_alerts_seen.json"


async def _my_symbols(client: httpx.AsyncClient) -> set[str]:
    """ICICI holdings, Desk positions, the WTCH watchlist (Redis mirror) and alerted symbols."""
    out: set[str] = set()
    for path, pick in (("/api/positions/open-positions",
                        lambda d: [p.get("symbol") for p in (d.get("positions") or ((d.get("last_known") or {}).get("positions")) or [])]),
                       ("/api/desk/status", lambda d: [p.get("symbol") for p in d.get("positions") or []]),
                       ("/api/monitor/list", lambda d: d.get("symbols") or []),
                       ("/api/alerts", lambda d: list((d.get("alerts") or {}).keys()))):
        try:
            r = await client.get(f"{UI_API}{path}")
            if r.status_code == 200:
                out |= {str(x).upper().replace(".NS", "") for x in pick(r.json()) if x}
        except Exception:
            continue
    return out


async def financials_sweep() -> None:
    """Saturday 10:00 IST — queue a background read of quarterly financials (NSE results XBRL) for every company in
    the FA cache plus the market-map names, your holdings, Desk, watchlist and the Desk's momentum watchlist.
    data-service reads them one at a time and skips anything read in the last 6 hours."""
    JOB = "financials_sweep"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            syms = await _my_symbols(client)
            mon = (await client.get(f"{UI_API}/api/market/monitor")).json()
            syms |= {str(m.get("symbol", "")).upper() for m in mon.get("map") or [] if m.get("symbol")}
            desk = (await client.get(f"{UI_API}/api/desk/status")).json()
            plan = (desk.get("plans") or [{}])[0]
            syms |= {str(w.get("symbol", "")).upper() for w in (plan.get("summary") or {}).get("watchlist") or [] if w.get("symbol")}
            # every company already in the FA cache (~1,800 liquid NSE names since 13 Oct): only new quarters are read
            fund = (await client.get(f"{UI_API}/api/market/fundamentals-screen")).json()
            syms |= {str(r.get("symbol", "")).upper() for r in fund.get("rows") or [] if r.get("symbol")}
            syms.discard("")
            r = await client.post(f"{DATA_SVC}/db/financials/prefetch", params={"symbols": ",".join(sorted(syms))})
            _log.info(JOB, f"queued {len(syms)} companies ({r.json().get('queued')} waiting)")
    except Exception as exc:
        _log.warning(JOB, f"sweep failed: {type(exc).__name__}: {exc}")


async def filing_alerts() -> None:
    """Every 5 min, 08:00–22:55 IST Mon–Sat — announce new material NSE filings (results, orders, ratings, M&A,
    insider/SAST, capital actions, board outcomes) by your stocks on the Mac and Telegram. Seen filings are
    remembered in data/filing_alerts_seen.json so nothing is announced twice."""
    JOB = "filing_alerts"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                mine = await _my_symbols(client)
                r = await client.get(f"{UI_API}/api/market/announcements")
                r.raise_for_status()
                items = r.json().get("items") or []
                try:
                    seen = set(json.loads(_FILINGS_SEEN.read_text()))
                except (OSError, ValueError):
                    seen = set()
                # every company that just filed results: read its numbers (XBRL) in the background, so the
                # reacting-today panel and tonight's wrap can say what they were
                fresh_results = sorted({f["symbol"] for f in items if f.get("category") == "results" and f.get("symbol")
                                        and f"{f.get('seq')}|{f.get('symbol')}" not in seen})
                if fresh_results:
                    try:
                        await client.post(f"{DATA_SVC}/db/financials/prefetch", params={"symbols": ",".join(fresh_results)})
                    except httpx.HTTPError:
                        pass
            if not mine:
                seen.update(f"{f.get('seq')}|{f.get('symbol')}" for f in items)
                _FILINGS_SEEN.parent.mkdir(parents=True, exist_ok=True)
                _FILINGS_SEEN.write_text(json.dumps(sorted(seen)[-5000:]))
                return
            first_run = not seen
            new = [f for f in items if f.get("symbol") in mine and f.get("category") in FILING_ALERT_CATS
                   and f"{f.get('seq')}|{f.get('symbol')}" not in seen]
            for f in items:
                seen.add(f"{f.get('seq')}|{f.get('symbol')}")
            _FILINGS_SEEN.parent.mkdir(parents=True, exist_ok=True)
            _FILINGS_SEEN.write_text(json.dumps(sorted(seen)[-5000:]))
            if first_run:                     # don't replay today's backlog the first time the job runs
                return
            for f in new[:10]:
                text = f"{f['symbol']} · {f['category'].upper()} · {f['subject']}"
                _log.info(JOB, text)
                await asyncio.to_thread(_notify_mac, "SuryaDhana · filing by your stock", text, "filing")
                await _alerts.info("Filing by your stock", f"{text}\n{(f.get('text') or '')[:300]}\n{f.get('pdf') or ''}")
            await _results_numbers_alerts(sorted(mine))
        except Exception as exc:
            _log.warning(JOB, f"check failed: {type(exc).__name__}: {exc}")


_RESULTS_NUMBERS_SENT = _ROOT / "data" / "results_numbers_sent.json"


def results_numbers_message(sym: str, f: dict, since: str) -> Optional[str]:
    """Pure: the one-line 'what the results said' alert for a quarter filed at or after `since`
    ('YYYY-MM-DDTHH:MM'), or None when that quarter's numbers are older."""
    if not f or str(f.get("filed_at") or "") < since:
        return None
    d = datetime.fromisoformat(f["period_end"])
    q = f"{['Q4', 'Q1', 'Q2', 'Q3'][(d.month - 1) // 3]} FY{(d.year + 1 if d.month >= 4 else d.year) % 100:02d}"

    def p(v: Optional[float]) -> str:
        return "—" if v is None else f"{'+' if v > 0 else ''}{v:.0f}%"

    profit = f"profit {f['pat_yoy_turn']}" if f.get("pat_yoy_turn") else f"profit {p(f.get('pat_yoy'))}"
    margin = f", net margin {f['pat_margin']:.1f}%" if f.get("pat_margin") is not None else ""
    pe = f" · P/E {f['pe']:.1f}×" if f.get("pe") is not None else ""
    return f"{sym} {q}: revenue {p(f.get('revenue_yoy'))}, {profit} y/y{margin}{pe}"


async def _results_numbers_alerts(mine: list[str]) -> None:
    """Once a holding's / watched stock's results filing has been read (XBRL), say what the numbers were. Once per
    quarter per stock; only for filings from the last two days."""
    if not mine:
        return
    try:
        sent = set(json.loads(_RESULTS_NUMBERS_SENT.read_text()))
    except (OSError, ValueError):
        sent = set()
    since = (datetime.now(IST) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{UI_API}/api/market/financials-latest", params={"symbols": ",".join(mine)})
        latest = r.json().get("latest") or {} if r.status_code == 200 else {}
    changed = False
    for sym, f in latest.items():
        key = f"{sym}|{f.get('period_end')}"
        msg = results_numbers_message(sym, f, since)
        if msg and key not in sent:
            sent.add(key); changed = True
            _log.info("filing_alerts", msg)
            await asyncio.to_thread(_notify_mac, "SuryaDhana · results numbers", msg, "results")
            await _alerts.info("Results numbers", msg)
    if changed:
        _RESULTS_NUMBERS_SENT.parent.mkdir(parents=True, exist_ok=True)
        _RESULTS_NUMBERS_SENT.write_text(json.dumps(sorted(sent)[-2000:]))


_MOVES_SENT = _ROOT / "data" / "move_alerts_sent.json"
MOVE_LEVELS = (5.0, 10.0)


def move_alert_keys(changes: dict[str, float], nifty: Optional[float], sma200: Optional[float],
                    already: set[str]) -> list[tuple[str, str]]:
    """Pure: (key, message) for every newly crossed level today. Holdings fire at ±5% and ±10% (once each); NIFTY
    fires once per side of its 200-day average (the Decision Desk's crash-filter line)."""
    out: list[tuple[str, str]] = []
    for sym, chg in sorted(changes.items()):
        for lv in MOVE_LEVELS:
            if abs(chg) >= lv:
                key = f"{sym}|{'+' if chg > 0 else '-'}{lv:g}"
                if key not in already:
                    out.append((key, f"{sym} is {'up' if chg > 0 else 'down'} {abs(chg):.1f}% today (your holding)"))
    if nifty and sma200:
        side = "above" if nifty >= sma200 else "below"
        key = f"NIFTY|{side}"
        other = f"NIFTY|{'below' if side == 'above' else 'above'}"
        if key not in already and other in already:          # only a real cross during the day, not the first reading
            out.append((key, f"NIFTY {nifty:,.0f} crossed {side} its 200-day average {sma200:,.0f}: the Desk's crash "
                             f"filter is decided at the month-end close, not intraday"))
        elif not already & {key, other}:
            out.append((key, ""))                             # remember today's starting side silently
    return out


async def internals_sample() -> None:
    """Every 2 min, Mon–Fri 09:15–15:31 IST — one market-internals sample (NSE breadth + segment moves) archived by
    data-service to data/nse_archive/internals/<date>.jsonl: the advance/decline line through the day (MOV, WRAP)."""
    JOB = "internals_sample"
    if await _closed_today(JOB):
        return
    now = datetime.now(IST)
    if not ((9, 15) <= (now.hour, now.minute) <= (15, 31)):
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{DATA_SVC}/db/internals/sample")
            r.raise_for_status()
    except Exception as exc:
        _log.warning(JOB, f"sample failed: {exc}")


async def move_alerts() -> None:
    """Every 5 min, Mon–Fri 09:20–15:30 IST — your ICICI holdings crossing ±5% / ±10% on the day, and NIFTY crossing
    its 200-day average, as Mac notifications (+ Telegram when configured). Once per level per day."""
    JOB = "move_alerts"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    now = datetime.now(IST)
    if lock.locked() or not ((9, 20) <= (now.hour, now.minute) <= (15, 30)):
        return
    async with lock:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                book = (await client.get(f"{UI_API}/api/positions/open-positions")).json()
                # ICICI not logged in yet: the last known holdings still deserve move alerts
                held = book.get("positions") or ((book.get("last_known") or {}).get("positions")) or []
                syms = sorted({str(p.get("symbol", "")).upper() for p in held if p.get("symbol")})
                changes: dict[str, float] = {}
                if syms:
                    q = (await client.get(f"{UI_API}/api/news-scanner/quotes",      # fresh: it decides, < 30 s old
                                          params={"symbols": ",".join(f"{x}.NS" for x in syms[:60]), "fresh": "1"}
                                          )).json().get("quotes") or {}
                    changes = {x: float(q[f"{x}.NS"]["change_pct"]) for x in syms
                               if (q.get(f"{x}.NS") or {}).get("available") and q[f"{x}.NS"].get("change_pct") is not None}
                crash = (await client.get(f"{UI_API}/api/market/crash-filter")).json()
                # NIFTY from NSE first (Yahoo's index quote can lag a session); Yahoo only as a fallback
                nifty = None
                try:
                    nl = await client.get(f"{UI_API}/api/market/nifty-live")
                    nifty = nl.json().get("last") if nl.status_code == 200 else None
                except Exception:  # noqa: BLE001
                    nifty = None
                if nifty is None:
                    nq = (await client.get(f"{UI_API}/api/news-scanner/quotes",
                                           params={"symbols": "^NSEI", "fresh": "1"})).json().get("quotes") or {}
                    nifty = (nq.get("^NSEI") or {}).get("price")
            today = now.date().isoformat()
            try:
                state = json.loads(_MOVES_SENT.read_text())
            except (OSError, ValueError):
                state = {}
            already = set(state.get(today, []))
            fresh = move_alert_keys(changes, nifty, crash.get("sma200"), already)
            for key, msg in fresh:
                already.add(key)
                if msg:
                    _log.info(JOB, msg)
                    await asyncio.to_thread(_notify_mac, "SuryaDhana · market move", msg, "move")
                    await _alerts.info("Market move", msg)
            _MOVES_SENT.parent.mkdir(parents=True, exist_ok=True)
            _MOVES_SENT.write_text(json.dumps({today: sorted(already)}))     # keep only today
        except Exception as exc:
            _log.warning(JOB, f"check failed: {type(exc).__name__}: {exc}")


def surveillance_changes(prev: dict[str, list[str]], now: dict[str, list[str]]) -> list[str]:
    """Pure: per symbol, NSE surveillance chips added or removed since the last check → "CUPID now ASM LT 2 (was
    ASM LT 1)", "PCJEWELLER out of ASM ST 1". Symbols seen for the first time report what they carry."""
    out = []
    for sym in sorted(now):
        a, b = set(prev.get(sym, [])), set(now.get(sym, []))
        if sym not in prev:
            if b:
                out.append(f"{sym} under {', '.join(sorted(b))}")
            continue
        added, gone = sorted(b - a), sorted(a - b)
        if added and gone:
            out.append(f"{sym} now {', '.join(added)} (was {', '.join(gone)})")
        elif added:
            out.append(f"{sym} added to {', '.join(added)}")
        elif gone:
            out.append(f"{sym} out of {', '.join(gone)}")
    return out


def fii_age_note(when: Any, today: str, holidays: Optional[Any] = None) -> str:
    """Review m084: NSE publishes FII / DII cash the evening after, so a morning note quotes the previous session; when
    the figure is older (the feed lagged: the 30 Oct note quoted 27 Oct), the note says by how many. With NSE's holiday
    master (``holidays``: ISO dates, data-service /db/market-holidays via _HOLIDAYS) it counts NSE sessions, so the
    morning after a weekday holiday is not flagged (round-2 review); without it, weekdays, and it says holidays were not
    counted. Pure."""
    try:
        a, b = date.fromisoformat(str(when)[:10]), date.fromisoformat(str(today)[:10])
    except ValueError:
        return ""
    days = [a + timedelta(days=i) for i in range(1, (b - a).days)]
    if holidays is not None:
        n = sum(1 for d in days if d.weekday() < 5 and d.isoformat() not in holidays)
        return f" — {n} NSE session{'s' if n > 1 else ''} older than the previous session" if n >= 1 else ""
    n = sum(1 for d in days if d.weekday() < 5)
    return f" — {n} weekday{'s' if n > 1 else ''} older than the previous session (NSE holidays not counted)" if n >= 1 else ""


def compose_morning_note(gift: dict, quotes: dict, cash: dict, events: list[dict], mine: set[str], today: str,
                         reported: Optional[list[dict]] = None, eco: Optional[list[dict]] = None,
                         surveillance: Optional[list[str]] = None, holidays: Optional[Any] = None) -> str:
    """Pure: one-paragraph pre-market note from the terminal's endpoints (GIFT gap, overnight cues, FII/DII, results
    filed since yesterday's close with what the numbers said, today's events with your stocks first, economic data
    and policy decisions due today)."""
    def pc(v: Any) -> str:
        return "—" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%"
    parts = []
    if gift.get("implied_gap_pct") is not None:
        parts.append(f"GIFT NIFTY implies {pc(gift['implied_gap_pct'])} at the open")
    cues = [f"{label} {pc((quotes.get(sym) or {}).get('change_pct'))}" for sym, label in
            (("^GSPC", "S&P"), ("^IXIC", "Nasdaq"), ("BZ=F", "Brent"), ("INR=X", "USD/INR"))
            if (quotes.get(sym) or {}).get("available")]
    if cues:
        parts.append("overnight " + ", ".join(cues))
    lat, when = (cash.get("summary") or {}).get("latest") or {}, (cash.get("summary") or {}).get("latest_date")
    if lat:
        parts.append(f"FII {lat.get('FII', 0):+,.0f} cr / DII {lat.get('DII', 0):+,.0f} cr ({when})" + fii_age_note(when, today, holidays))
    if reported:
        def numbers(r: dict) -> str:
            rev = f"rev {pc(r['revenue_yoy'])}" if r.get("revenue_yoy") is not None else ""
            pat = f"profit {r['pat_turn']}" if r.get("pat_turn") else f"profit {pc(r['pat_yoy'])}" if r.get("pat_yoy") is not None else ""
            both = " / ".join(x for x in (rev, pat) if x)
            return f"{r['symbol']}{' (' + both + ')' if both else ''}"
        ordered = sorted(reported, key=lambda r: (r.get("symbol") not in mine, -abs(r.get("pat_yoy") or 0)))
        parts.append(f"{len(reported)} reported since yesterday's close: " + ", ".join(numbers(r) for r in ordered[:5])
                     + ("…" if len(reported) > 5 else ""))
    todays = [e for e in events if e.get("event_date") == today]
    yours = [e for e in todays if e.get("symbol") in mine]
    if yours:
        label = lambda k: "board meeting" if k == "OTHER" else k.lower().replace("_", " ")  # noqa: E731 — as the UI

        def about(e: dict) -> str:    # what a board meeting is for, when NSE's calendar says (not the boilerplate)
            d = str(e.get("detail") or "")
            if e.get("kind") != "OTHER" or not d or "informed the exchange" in d.lower():
                return ""
            d = re.sub(r"^To consider and approve (the )?", "", d, flags=re.I).rstrip(".")
            d = re.sub(r"\b(\w+) s\b", r"\1's", d)          # NSE drops apostrophes: "Company s" → "Company's"
            return f": {d[:70]}"
        parts.append("YOUR STOCKS today: " + ", ".join(f"{e['symbol']} ({label(e['kind'])}{about(e)})" for e in yours))
    res = [e["symbol"] for e in sorted(todays, key=lambda e: -(e.get("turnover_cr") or 0)) if e.get("kind") == "RESULTS"]
    if res:
        parts.append(f"{len(res)} results today: " + ", ".join(res[:6]) + ("…" if len(res) > 6 else ""))
    due = [e for e in eco or [] if e.get("date") == today and e.get("kind") != "HOLIDAY"]
    if due:
        parts.append("data today: " + ", ".join(f"{e['what']} {e.get('time') or ''}".strip() for e in due))
    if surveillance:          # NSE surveillance changes on your holdings (ASM / GSM / band / F&O ban)
        parts.append("NSE surveillance: " + "; ".join(surveillance))
    closed = [e for e in eco or [] if e.get("date") == today and e.get("kind") == "HOLIDAY"]
    if closed:      # an exchange holiday leads the note: nothing trades today
        parts.insert(0, f"NSE CLOSED TODAY ({closed[0]['what'].split(' · ')[-1]})")
    return " · ".join(parts) if parts else "No pre-market data available."


def compose_close_note(nifty: dict, internals: dict, book: list[dict], quotes: dict, contrib: Optional[dict] = None) -> str:
    """Pure: the closing note. NIFTY's close, breadth through the day (broad or narrow, and how it changed), and
    your holdings' move today in ₹ (quantity × today's change, last known holdings when ICICI is logged out)."""
    def pc(v: Any) -> str:
        return "—" if v is None else f"{'+' if v > 0 else ''}{v:.2f}%"
    parts = []
    if nifty.get("last") is not None:
        parts.append(f"NIFTY {nifty['last']:,.0f} ({pc(nifty.get('change_pct'))})")
    sm = internals.get("summary") or {}
    if sm.get("n500_adv") is not None:
        line = f"NIFTY 500 breadth {sm['n500_adv']:.0f} up / {sm['n500_dec']:.0f} down"
        if sm.get("net_worst") is not None and sm.get("net_best") is not None and sm.get("samples", 0) > 10:
            line += f" (net ranged {sm['net_worst']:+.0f} to {sm['net_best']:+.0f})"
        if sm.get("divergence"):
            line += f": {sm['divergence']}"
        parts.append(line)
    ms = [m for m in (contrib or {}).get("members") or [] if m.get("points") is not None]
    if len(ms) >= 5:
        lead = [m for m in sorted(ms, key=lambda m: -abs(m["points"]))[:3]]
        parts.append("NIFTY points: " + ", ".join(f"{m['symbol']} {m['points']:+.0f}" for m in lead))
    if sm.get("small_minus_n50") is not None and abs(sm["small_minus_n50"]) >= 0.75:
        parts.append(f"small caps {pc(sm['small_minus_n50'])} vs NIFTY")
    day, movers = 0.0, []
    for p in book:
        sym = str(p.get("symbol", "")).upper()
        q = quotes.get(f"{sym}.NS") or {}
        qty, px, chg = p.get("quantity"), q.get("price"), q.get("change_pct")
        if q.get("available") and qty and px and chg is not None:
            rupees = float(qty) * px * (chg / 100) / (1 + chg / 100)
            day += rupees
            movers.append((abs(chg), f"{sym} {pc(chg)}"))
    if movers:
        top = ", ".join(m for _, m in sorted(movers, reverse=True)[:3])
        parts.append(f"your holdings {'+' if day >= 0 else '−'}₹{abs(day):,.0f} today ({top})")
    return " · ".join(parts) if parts else "No closing data available."


async def close_note() -> None:
    """15:40 IST Mon–Fri — the closing note (NIFTY, breadth through the day, your holdings in ₹) as a Mac
    notification, inbox entry and Telegram message."""
    JOB = "close_note"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                async def get(path: str, **params: Any) -> Any:
                    try:
                        r = await client.get(f"{UI_API}{path}", params=params or None)
                        return r.json() if r.status_code == 200 else {}
                    except Exception:
                        return {}
                nifty = await get("/api/market/nifty-live")
                internals = await get("/api/market/internals")
                held = await get("/api/positions/open-positions")
                book = held.get("positions") or ((held.get("last_known") or {}).get("positions")) or []
                syms = sorted({str(p.get("symbol", "")).upper() for p in book if p.get("symbol")})
                quotes = (await get("/api/news-scanner/quotes", symbols=",".join(f"{x}.NS" for x in syms[:60]))).get("quotes") or {} if syms else {}
                contrib = await get("/api/market/index-contribution", index="NIFTY 50")
            note = compose_close_note(nifty, internals, book, quotes, contrib)
            _log.info(JOB, note)
            await asyncio.to_thread(_notify_mac, "SuryaDhana · closing note", note, "close")
            await _alerts.info("Closing note", note)
        except Exception as exc:
            _log.error(JOB, f"FAILED: {type(exc).__name__}: {exc}")


async def morning_note() -> None:
    """08:50 IST Mon–Fri — the pre-market note (GIFT NIFTY gap, overnight cues, FII/DII, today's events with your
    stocks first) as a Mac notification, inbox entry and Telegram message."""
    JOB = "morning_note"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async def get(path: str, **params: Any) -> Any:
                    try:
                        r = await client.get(f"{UI_API}{path}", params=params or None)
                        return r.json() if r.status_code == 200 else {}
                    except Exception:
                        return {}
                gift = await get("/api/market/gift-nifty")
                quotes = (await get("/api/news-scanner/quotes", symbols="^GSPC,^IXIC,BZ=F,INR=X")).get("quotes") or {}
                cash = await get("/api/market/fii-dii-cash", days=10)
                events = (await get("/api/market/events")).get("rows") or []
                reported = (await get("/api/market/results-reacting")).get("rows") or []
                eco = (await get("/api/market/eco-calendar", back=0, ahead=1)).get("events") or []
                mine = await _my_symbols(client)
                flags = (await get("/api/market/surveillance", symbols=",".join(sorted(mine)))).get("flags") or {} if mine else {}
            now_flags = {s_: [c["code"] for c in (f.get("chips") or [])] for s_, f in flags.items()}
            seen_path = _ROOT / "data" / "surveillance_seen.json"
            try:
                prev = json.loads(seen_path.read_text()) if seen_path.exists() else {}
            except ValueError:
                prev = {}
            changes = surveillance_changes(prev, now_flags) if now_flags else []
            if now_flags:
                seen_path.write_text(json.dumps(now_flags))
            await _nse_holiday()                      # m084: NSE's holiday master, cached 12 h (the FII / DII age counts sessions)
            note = compose_morning_note(gift, quotes, cash, events, mine, datetime.now(IST).date().isoformat(), reported, eco,
                                        changes, holidays=_HOLIDAYS["days"] if _HOLIDAYS["at"] else None)
            _log.info(JOB, note)
            await asyncio.to_thread(_notify_mac, "SuryaDhana · pre-market note", note, "morning")
            await _alerts.info("Pre-market note", note)
        except Exception as exc:
            _log.error(JOB, f"FAILED: {type(exc).__name__}: {exc}")


def missed_jobs(now: datetime, root: Path) -> list[str]:
    """Pure-ish (reads files): today's jobs that should have run while the controller was down and are still worth
    running now. Pre-open book: NSE keeps it until the next session. Morning note: only before the 09:15 open.
    Evening wrap: after 21:00 if today's file is missing. Gold (any day): the key ingest jobs whose slot passed with no
    run in the persisted job history (gold_missed_jobs)."""
    out: list[str] = []
    if now.weekday() < 5:
        day, hm = now.date().isoformat(), (now.hour, now.minute)
        if hm >= (9, 9) and not (root / "data" / "nse_archive" / "preopen" / f"{day}_FO.json").exists():
            out.append("preopen_capture")
        if (8, 50) <= hm < (9, 15):
            try:
                sent = any('"kind": "morning"' in ln and ln.startswith(f'{{"at": "{day}')
                           for ln in (root / "data" / "notifications.jsonl").read_text(encoding="utf-8").splitlines())
            except OSError:
                sent = False
            if not sent:
                out.append("morning_note")
        if hm >= (21, 0) and not (root / "reports" / "daily_wrap" / f"{day}.md").exists():
            out.append("daily_wrap")
    history = read_job_history(root)
    out += gold_missed_jobs(now, history)
    out += terminal_missed_jobs(now, history)
    return out


# ── Downtime recovery (19 Oct 2026 resilience review) ─────────────────────────
# The scheduler keeps its jobs in memory and computes every next run from the moment it starts, so a
# controller that was down for three days (Mac slept, then rebooted, 16→19 Oct) silently skipped the
# EOD pipeline, the NSE ingests, the Desk mark and the shadow — and, being the alerter, told nobody.
# A once-a-minute heartbeat file lets the next start see the gap, count what each trigger missed, and
# catch the data up.
HEARTBEAT_FILE = _ROOT / "data" / ".controller_heartbeat.json"
DOWNTIME_REPORT_MIN = 10          # a routine restart is shorter than this; a gap beyond it is reported


def read_heartbeat(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(json.loads(path.read_text())["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_heartbeat(path: Path, now: Optional[datetime] = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": (now or datetime.now(IST)).isoformat()}))
        tmp.replace(path)
    except OSError:
        pass


def fire_times_between(trigger: Any, start: datetime, end: datetime, cap: int = 500) -> int:
    """How many times `trigger` would have fired in (start, end]; capped (a 1-min job over days)."""
    n, t = 0, trigger.get_next_fire_time(None, start + timedelta(microseconds=1))
    while t is not None and t <= end and n < cap:
        n += 1
        t = trigger.get_next_fire_time(t, t + timedelta(microseconds=1))
    return n


def downtime_missed(jobs: list, last_beat: datetime, now: datetime) -> dict[str, int]:
    """{job id: runs missed} for recurring jobs (one-off 'date' jobs and the heartbeat excluded)."""
    out = {}
    for job in jobs:
        if job.id == "controller_heartbeat" or type(job.trigger).__name__ == "DateTrigger":
            continue
        n = fire_times_between(job.trigger, last_beat, now)
        if n:
            out[job.id] = n
    return out


def plan_catchup(now: datetime, missed: dict[str, int]) -> tuple[str, datetime]:
    """Decide the data catch-up after downtime → (mode, when).

    mode: "full"  — the evening pipeline was missed and the market is shut: run /jobs/daily-pipeline
                    (Yahoo settled bars + NSE files + ML rebuild, isolated steps);
          "nse"   — NSE files only (bhavcopy, positions, events, monitor): during market hours the Yahoo
                    refresh would store today's half-formed bar, so it waits for the 18:30 pipeline;
          "skip"  — inside the EOD window: no data catch-up of its own; the scheduled 18:30–21:00 jobs still ahead do
                    their work, and the evening jobs whose slot already passed are replayed once each (M30,
                    evening_replay_plan / EVENING_REPLAY: before 6 Nov nothing re-ran them).
    when: never inside the 07:45–09:20 ICICI-login / pre-open window (moved to 09:21)."""
    when = now + timedelta(seconds=90)
    hm = (when.hour, when.minute)
    if (18, 20) <= hm < (21, 15):
        return "skip", when
    if (7, 45) <= hm < (9, 21):
        when = when.replace(hour=9, minute=21, second=0, microsecond=0)
        hm = (9, 21)
    market_or_settling = when.weekday() < 5 and (9, 0) <= hm < (18, 20)   # weekends: market shut, run it all
    if missed.get("eod_data_pipeline") and not market_or_settling:
        return "full", when
    return "nse", when


# ── M30 (5 Nov review): the evening jobs a start-up inside the EOD window replays itself ─────────────────────────
# The controller was down 19:34:54–19:55:26 on 5 Nov; the start-up planned "skip" (inside the 18:20–21:15 window "the
# scheduled jobs do the work") and re-ran nothing, so the 19:45 news track record and the 19:50 S1 shadow (the one
# promoted strategy's paper forward test) stayed stale until the next evening, while the report said the Desk and the
# shadow "mark every missed session on their next run (19:30 / 19:50)" — after 19:50 had passed. These are the evening
# jobs whose missed slot nothing else re-runs that evening. Each is a JOB, not a restart (the freeze window forbids
# restarts, PLAN §0.10), and each is safe to replay: the pipeline resumes after the last stored day; the snapshot is
# rebuilt (its readers below need it); the Desk and the shadow replay every missed session from stored closes with the
# rules unchanged; the index valuation adds missing days only; the track record and the Friday journal are recomputed
# from stored files. Run once each, in this order (dependencies first), by the start-up catch-up. The S1 shadow runs
# BEFORE the 19:45 news track record (6 Nov checker; the review asked "the S1 shadow first"): it reads only the pipeline's
# closes and the snapshot, never the track record, and the track record's subprocess may take up to 30 min.
EVENING_REPLAY: tuple[tuple[str, tuple[int, ...], time], ...] = (
    ("eod_data_pipeline", (0, 1, 2, 3, 4), time(18, 30)),
    ("index_valuation_daily", (0, 1, 2, 3, 4), time(19, 15)),
    ("shared_snapshot_build", (0, 1, 2, 3, 4), time(19, 20)),
    ("desk_daily", (0, 1, 2, 3, 4), time(19, 30)),
    ("alpha_shadow_daily", (0, 1, 2, 3, 4), time(19, 50)),
    ("news_track_record_daily", (0, 1, 2, 3, 4), time(19, 45)),
    ("weekly_journal", (4,), time(20, 10)),
)
_CATCHUP_SCHEDULED: set[str] = set()   # every job id this start scheduled a catch-up run for (the report's coverage)


def _note_catchup(job_id: str, when: datetime) -> None:
    """Record that a catch-up run of `job_id` is scheduled at `when`: the report's coverage, and SYS's per-job
    `catchup_at` (/api/scheduler/status) until the job next runs (_track clears it)."""
    _CATCHUP_SCHEDULED.add(job_id)
    _CATCHUP_PLAN[job_id] = when.astimezone(IST).isoformat(timespec="seconds")


def _spend_catchups(job_ids: set[str]) -> None:
    """A catch-up that re-ran these jobs itself (under its own id — startup_catchup, gold_downtime_catchup — so _track
    never cleared them) or skipped them is over: their `catchup_at` must not keep showing a time that has passed (6 Nov
    checker). A job whose own one-off (<id>_catchup / _startup / _deferred) is still pending keeps its time."""
    pending = _pending_oneoffs(job_ids)
    for j in job_ids - pending:
        _CATCHUP_PLAN.pop(j, None)


def catchup_notes(mode: str, missed: dict[str, int], replay: Sequence[str]) -> list[str]:
    """The jobs the start-up catch-up will re-run that the downtime actually MISSED (SYS's catchup_at, M30): a job the
    catch-up re-runs anyway (nse_positions_catchup, index_drivers_daily in the full / nse modes) but that missed nothing
    has no gap to catch up, so no catch-up time is shown for it. Pure."""
    return [*replay, *sorted(j for j in catchup_coverage(mode, missed, ()) if missed.get(j) and j not in replay)]


def evening_replay_plan(now: datetime, missed: dict[str, int]) -> tuple[list[str], list[str]]:
    """(replay now, left to today's own run) for the EVENING_REPLAY jobs the downtime missed. A job whose slot today is
    still ahead is left to that run (it would only race it: the 18:30 bars are not settled before 18:30); the others are
    replayed once, in EVENING_REPLAY order. Pure."""
    t = _ist_naive(now)
    replay: list[str] = []
    later: list[str] = []
    for job, days, slot in EVENING_REPLAY:
        if not missed.get(job):
            continue
        (later if t.weekday() in days and t.time() < slot else replay).append(job)
    return replay, later


def _evening_replay_funcs() -> dict[str, Callable[[], Any]]:
    return {"eod_data_pipeline": eod_data_pipeline, "index_valuation_daily": index_valuation_daily,
            "shared_snapshot_build": shared_snapshot_build, "desk_daily": desk_daily,
            "news_track_record_daily": news_track_record_daily, "alpha_shadow_daily": alpha_shadow_daily,
            "weekly_journal": weekly_journal}


def _status_since(job_id: str, since: datetime) -> str | None:
    """The status SYS recorded for `job_id`'s latest run if that run ended at or after `since`, else None (no run of it
    was recorded since then: the function returned before _track — a held lock, a closed-market guard)."""
    st = _latency.stats(job_id).get(job_id) or {}
    ts = st.get("last_ts")
    try:
        ended = datetime.fromisoformat(str(ts)) if ts else None
    except ValueError:
        ended = None
    return st.get("last_status") if ended is not None and ended >= since else None


async def evening_replay(job_ids: Sequence[str]) -> list[str]:
    """Run the planned EVENING_REPLAY jobs one after another (a failure is reported, never stops the next one); one
    phrase each, with the status THIS run recorded for SYS (never an earlier run's)."""
    funcs, out = _evening_replay_funcs(), []
    for job in job_ids:
        t0 = datetime.now(IST)
        try:
            await funcs[job]()
            st = _status_since(job, t0)
            out.append(f"{job}: re-run ({st})" if st else f"{job}: re-run requested, no run recorded")
        except Exception as exc:  # noqa: BLE001 — the next job and the report must still happen
            out.append(f"{job}: re-run FAILED {type(exc).__name__}: {str(exc)[:100]}")
    return out


def catchup_coverage(mode: str, missed: dict[str, int], replay: Sequence[str]) -> set[str]:
    """The missed job ids the start-up catch-up itself re-runs (by mode), plus the evening replay. Pure."""
    covered = set(replay)
    if mode in ("full", "nse"):
        covered |= {"nse_positions_catchup"} | ({"eod_data_pipeline"} if mode == "full" else set())
        covered |= {j for j in ("results_capture_daily", "index_valuation_daily", "desk_daily", "alpha_shadow_daily")
                    if missed.get(j)}
        if TERMINAL_JOBS_ENABLED:
            covered.add("index_drivers_daily")
    covered |= {j for j in GOLD_KEY_JOBS if missed.get(j)}
    return covered


def catchup_gaps(missed: dict[str, int], covered: set[str], later: Sequence[str],
                 next_runs: dict[str, datetime | None]) -> list[str]:
    """The honest tail of the 'Stack was down' report (M30: SYS never claims a catch-up that will not run): every missed
    key or evening job that NO catch-up re-runs, with its next scheduled run, and the ones left to today's own run.
    Recurring every-few-minutes jobs are not listed (their next tick is the catch-up). Pure."""
    watched = set(_KEY_JOBS) | {j for j, _, _ in EVENING_REPLAY}
    out: list[str] = []
    if later:
        out.append("left to today's scheduled run: " + ", ".join(
            f"{j} {next_runs[j]:%H:%M}" if next_runs.get(j) else j for j in later))
    gaps = sorted(j for j in missed if j in watched and j not in covered and j not in later)
    if gaps:
        out.append("NOT re-run (next scheduled run): " + ", ".join(
            f"{j} {next_runs[j]:%a %d %b %H:%M}" if next_runs.get(j) else f"{j} (none scheduled)" for j in gaps))
    return out


async def startup_catchup(last_beat_iso: str, started_iso: str, missed: dict[str, int], mode: str,
                          backup_at: str | None = None, replay: Sequence[str] = (), later: Sequence[str] = ()) -> None:
    """Run the planned data catch-up and send ONE report (warning level: the stack was down). Holds its lock while
    it runs, so the missed-backup catch-up (db_backup_catchup) never copies the DuckDB while this writes to it."""
    async with _get_lock("startup_catchup"):
        await _startup_catchup_run(last_beat_iso, started_iso, missed, mode, backup_at, replay, later)


def _pending_oneoffs(job_ids: set[str]) -> set[str]:
    """The jobs among `job_ids` with a one-off re-run pending in the scheduler (<id>_catchup / _startup / _deferred:
    the missed-today one-offs, the start-up ICICI check, a gold job moved past a freeze window)."""
    getter = getattr(scheduler, "get_job", None)
    if getter is None:
        return set()
    return {j for j in job_ids if any(getter(f"{j}{sfx}") is not None for sfx in ("_catchup", "_startup", "_deferred"))}


def _next_runs(job_ids: set[str]) -> dict[str, datetime | None]:
    """{job id: its next scheduled run (IST)} from the live scheduler; None where unknown."""
    getter = getattr(scheduler, "get_job", None)
    out: dict[str, datetime | None] = {}
    for j in job_ids:
        job = getter(j) if getter is not None else None
        nrt = getattr(job, "next_run_time", None)
        out[j] = nrt.astimezone(IST) if nrt else None
    return out


async def _startup_catchup_run(last_beat_iso: str, started_iso: str, missed: dict[str, int], mode: str,
                               backup_at: str | None, replay: Sequence[str] = (), later: Sequence[str] = ()) -> None:
    JOB = "startup_catchup"
    t0 = datetime.now(IST)                     # the "replayed" line counts only runs of THIS catch-up
    lines: list[str] = []
    deferred_gold: list[str] = []
    if mode == "full":
        try:
            res = await _run_data_job(JOB, "/jobs/daily-pipeline", dict(EOD_PIPELINE_BODY))
            soft = {k: v["error"] for k, v in res.items() if isinstance(v, dict) and v.get("error")}
            bh = res.get("bhavcopy", {})
            lines.append(f"EOD pipeline re-run: bhavcopy +{bh.get('days_loaded', 0)} day(s), ML features through "
                         f"{(res.get('build', {}).get('feature_date_range') or ['?', '?'])[1]}"
                         + (f"; failed steps: {', '.join(soft)}" if soft else ""))
        except Exception as exc:  # noqa: BLE001 — the report must still go out
            lines.append(f"EOD pipeline re-run FAILED: {exc}")
    elif mode == "nse":
        for path, label in (("/jobs/ingest-bhavcopy", "NSE bhavcopy"), ("/jobs/ingest-nse-positions", "NSE positions"),
                            ("/jobs/ingest-nse-events", "corporate calendar")):
            try:
                res = await _run_data_job(JOB, path, {})
                extra = f" +{res['days_loaded']} day(s)" if "days_loaded" in res else ""
                lines.append(f"{label}: ok{extra}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{label}: FAILED {exc}")
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                mm = (await client.get(f"{DATA_SVC}/db/market-monitor")).json()
            lines.append(f"market monitor as of {mm.get('as_of')}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"market monitor rebuild FAILED: {exc}")
        if missed.get("eod_data_pipeline"):
            lines.append("Yahoo bars + ML rebuild: tonight's 18:30 pipeline (market hours now)")
    elif replay:
        # M30: inside the EOD window the jobs whose slot already passed are replayed here, once each, in order
        lines += await evening_replay(replay)
    else:
        lines.append("inside the EOD window: no evening job's slot was missed")
    if mode in ("full", "nse"):
        lines += await _terminal_downtime_catchup(JOB, last_beat_iso, missed, mode)
    gold_ids = [j for j in GOLD_KEY_JOBS if missed.get(j)]
    if gold_ids:
        # PLAN §c.3 catch-up: the key gold jobs re-run with backfill_from = the last heartbeat's date; never inside a
        # freeze window (the EOD-window "skip" mode, or a run that drifted into one): one run at the window's end.
        backfill_from = last_beat_iso[:10]
        now = datetime.now(IST)
        slot = freeze_slot(now)
        if mode == "skip" or slot > now:
            when = slot if slot > now else freeze_slot(now.replace(hour=18, minute=30, second=0, microsecond=0))
            if scheduler is not None:
                scheduler.add_job(gold_downtime_catchup, trigger="date", run_date=when, args=[gold_ids, backfill_from],
                                  id="gold_downtime_catchup", name="Gold data catch-up after downtime",
                                  replace_existing=True, misfire_grace_time=3600, coalesce=True)
            for j in gold_ids:
                _note_catchup(j, when)
            deferred_gold = list(gold_ids)
            lines.append(f"gold ({', '.join(gold_ids)}): one run at {when:%H:%M} with backfill from {backfill_from}")
        else:
            lines.append(await gold_downtime_catchup(gold_ids, backfill_from))
    if backup_at:
        lines.append(f"today's 02:15 backup is missing: one run at {backup_at}")
    top = sorted(missed.items(), key=lambda kv: (-(kv[0] in _KEY_JOBS), kv[0]))[:12]
    missed_txt = ", ".join(f"{k}×{v}" for k, v in top) or "none"
    # M30: say exactly what was re-run, what waits for today's own slot and what is NOT re-run (with its next run) —
    # never a blanket "the Desk and the S1 shadow mark every missed session on their next run"
    covered = catchup_coverage(mode, missed, replay) | _CATCHUP_SCHEDULED | _pending_oneoffs(set(missed))
    if backup_at:
        covered.add("db_backup_daily")
    tail = catchup_gaps(missed, covered, later, _next_runs(set(missed) | set(later)))
    # only a run of THIS catch-up that recorded "done": an error, "skipped" (DESK_ENABLED=0) or "no new data" (nothing
    # moved, so nothing was replayed) never reads as a replay (6 Nov checker)
    replayed = [j for j in ("desk_daily", "alpha_shadow_daily") if j in covered and missed.get(j)
                and _status_since(j, t0) == "done"]
    _spend_catchups(catchup_coverage(mode, missed, replay) - set(deferred_gold))
    if replayed:
        tail.append(" and ".join({"desk_daily": "the Desk", "alpha_shadow_daily": "the S1 shadow"}[j] for j in replayed)
                    + " replayed every missed session from stored closes (rules unchanged)")
    body = (f"Down from {last_beat_iso[:16].replace('T', ' ')} to {started_iso[:16].replace('T', ' ')} IST.\n"
            f"Missed runs: {missed_txt}\nCatch-up: " + " · ".join(lines)
            + ("\n" + "\n".join(tail) if tail else ""))
    _log.warning(JOB, body)
    await _alerts.warning("Stack was down — catching up", body)


_KEY_JOBS = {"eod_data_pipeline", "desk_daily", "alpha_shadow_daily", "db_backup_daily", "daily_wrap",
             "icici_session_refresh", "shared_snapshot_build", "nse_positions_catchup", "results_capture_daily",
             "index_valuation_daily", "index_drivers_daily", "nse_evening_pass", *GOLD_KEY_JOBS}


async def daily_wrap() -> None:
    """21:00 IST Mon–Fri — write the day's market wrap (reports/daily_wrap/<date>.md, WRAP page) once the evening
    NSE files, FII/DII cash and results release times are in; the one-line summary goes out as an info alert."""
    JOB = "daily_wrap"
    if await _closed_today(JOB):
        return
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        # the 20:45 results capture feeds "results announced today": give it up to 20 min to finish
        for _ in range(40):
            if not _get_lock("results_capture_daily").locked():
                break
            await asyncio.sleep(30)
        cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "daily_wrap.py"), "--base", UI_API]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=600,
                                          cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)})
            last = (res.stdout.strip().splitlines() or [""])[-1]
            if res.returncode == 0 and last.startswith("RESULT "):
                result = json.loads(last[7:])
                _log.info(JOB, f"{result['path']}: {result['summary']}")
                await asyncio.to_thread(_record_notification, "wrap", f"Market wrap {result['date']}", result["summary"] or "written")
                await _alerts.info(f"Market wrap {result['date']}", result["summary"] or "written")
            else:
                _log.error(JOB, "daily_wrap failed", stderr=res.stderr[-400:])
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


async def index_valuation_daily(recent: int = 10) -> None:
    """19:15 IST Mon–Fri — append the day's index P/E, P/B and dividend yield from NSE's daily index file to the
    valuation history (MKT → Valuation · NSE, BRIEF, WRAP). Incremental: the last `recent` weekdays (10; the start-up
    catch-up after downtime passes the days down + 5), missing days only."""
    JOB = "index_valuation_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "backfill_index_valuation.py"), "--recent", str(int(recent))]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300,
                                          cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)})
            if res.returncode == 0:
                _log.info(JOB, (res.stdout.strip().splitlines() or ["done"])[-1])
            else:
                _log.error(JOB, "backfill_index_valuation failed", stderr=res.stderr[-400:])
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


def _evening_snapshot_env() -> dict:
    """Amendment A7: read the snapshot pointer AT SPAWN TIME (no controller module state).
    Strict freshness (2 h + source-mtime match) — right for the same-evening 19:45/19:50 jobs;
    absent/stale → {} and consumers silently use their old private-copy path."""
    try:
        import build_evening_snapshot as _snap
        path = _snap.current(max_age_h=2)
        return {"SURYA_SNAPSHOT_PATH": path} if path else {}
    except Exception:  # noqa: BLE001 — never let snapshot plumbing break a job spawn
        return {}


async def shared_snapshot_build() -> None:
    """19:20 IST Mon–Fri — build the shared evening DuckDB snapshot (APFS clone, verified,
    pointer file). The 19:45 news job, 19:50 shadow and 02:15 backup consume it instead of
    making private 4.7 GB copies (Bloomberg program F2.3/S3)."""
    JOB = "shared_snapshot_build"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "build_evening_snapshot.py")]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=600,
                                          cwd=str(_ROOT))
            if res.returncode == 0:
                _log.info(JOB, (res.stdout.strip().splitlines() or ["built"])[-1][:300])
            else:
                _log.error(JOB, "snapshot build failed", stderr=res.stderr[-400:])
                await _alerts.warning("Evening snapshot failed",
                                      "jobs fall back to private copies. " + (res.stderr[-160:] or ""))
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


DB_BACKUP_BUSY_EXIT = 75     # scripts/db_backup.py EXIT_BUSY: another run holds its lock; nothing was written


def offsite_dir() -> str | None:
    """M32 / owner action O-3: OFFSITE_BACKUP_DIR from the environment, else read from .env at run time (set it without
    restarting the controller). None = unset: the 02:15 job does not pass --offsite."""
    raw = (os.environ.get("OFFSITE_BACKUP_DIR") or _env_file_value("OFFSITE_BACKUP_DIR") or "").strip()
    return raw or None


def db_backup_cmd(offsite: str | None) -> list[str]:
    """The 02:15 command: scripts/db_backup.py, plus `--offsite DIR` ONLY when OFFSITE_BACKUP_DIR is set (db_backup.py
    copies tonight's files there, verifies the DuckDB copy by sha256 and rotates 7 daily + 4 Sundays; a failed off-site
    copy exits 1 after the local backup is complete, so SYS shows the run as an error and Telegram says why)."""
    cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "db_backup.py")]
    return cmd + ["--offsite", offsite] if offsite else cmd


async def db_backup_daily() -> None:
    """02:15 IST daily — verified DuckDB backup with rotation (scripts/db_backup.py).
    Reads the evening snapshot (allow_stale), so backups lag ≤1 trading day of the 20:30/20:45
    ingests — documented in docs/RUNBOOK_RESTORE.md. Also run once at start-up when today's was missed
    (db_backup_catchup). One at a time: this job's lock here, db_backup.py's file lock across processes."""
    JOB = "db_backup_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        _log.warning(JOB, "a backup is already running — skipped")
        return
    async with lock, _track(JOB):
        cmd = db_backup_cmd(offsite_dir())
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=1200,
                                          cwd=str(_ROOT))
            if res.returncode == 0:
                _log.info(JOB, (res.stdout.strip().splitlines() or ["backed up"])[-1][:300])
            elif res.returncode == DB_BACKUP_BUSY_EXIT:
                _log.warning(JOB, "skipped: another db_backup.py run holds the backup lock")
            elif "off-site copy FAILED" in (res.stderr or "") and "ui_prefs backup FAILED" not in (res.stderr or ""):
                _mark_failed(JOB)                 # M32: the local copy is complete; only the off-machine one failed
                _log.error(JOB, "off-site copy failed (local backup complete)", stderr=res.stderr[-400:])
                await _alerts.warning("Off-site backup copy FAILED",
                                      f"{_stderr_reason(res.stderr)}\nTonight's local backup is complete; check that "
                                      "OFFSITE_BACKUP_DIR is mounted (RUNBOOK 'Owner actions after the 5 Nov review').")
            else:
                _mark_failed(JOB)
                _log.error(JOB, "backup failed", stderr=res.stderr[-400:])
                await _alerts.critical("DuckDB backup FAILED", res.stderr[-200:] or "no stderr")
        except Exception as exc:
            _mark_failed(JOB)
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("DuckDB backup FAILED", str(exc)[:200])


# ── Missed nightly backup (P7) ────────────────────────────────────────────────
# Cron jobs are computed from start-up time, so a 02:15 the Mac was off for (24–25 Oct) was simply skipped and the
# next backup came a day later. At start-up, when today's backup is missing and its 02:15 slot has passed, ONE run
# is scheduled: never inside the restart-freeze windows (ICICI login + pre-open, EOD chain) nor less than the
# backup's own timeout before one opens, and only after the start-up data catch-up has stopped writing the DuckDB.
BACKUP_DIR = _ROOT / "data" / "backups" / "duckdb"
BACKUP_TIME = time(2, 15)
FREEZE_WINDOWS = ((time(7, 45), time(9, 20)), (time(18, 30), time(21, 15)))      # IST, ends inclusive
BACKUP_START_MARGIN = timedelta(minutes=20)       # = the backup's subprocess timeout above
BACKUP_CATCHUP_DELAY = timedelta(minutes=3)       # after start-up, and after the data catch-up's slot
BACKUP_CATCHUP_POLL_S = 30
BACKUP_CATCHUP_MAX_WAIT_S = 3 * 3600              # waiting for the data catch-up (≤ 3 data-service jobs)


def backup_done_today(now: datetime, dest: Path | None = None) -> bool:
    """Today's backup is complete: db_backup.py writes market-YYYYMMDD.meta.json last, after the verified copy (a
    killed or failed run leaves none). YYYYMMDD is the Mac's local date, which is IST on this machine."""
    return ((dest or BACKUP_DIR) / f"market-{now:%Y%m%d}.meta.json").is_file()


def backup_slot(t: datetime) -> datetime:
    """t when a backup may start then, else the minute after the freeze window it would run into: a start inside a
    window, or less than BACKUP_START_MARGIN before one opens, moves to 09:21 / 21:16."""
    for start, end in FREEZE_WINDOWS:
        lo = t.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0) - BACKUP_START_MARGIN
        after = t.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0) + timedelta(minutes=1)
        if lo <= t < after:
            return after
    return t


def in_freeze_window(t: datetime) -> bool:
    """Inside the 07:45–09:20 or 18:30–21:15 IST restart-freeze window. The ends are inclusive to the minute (like
    FREEZE_WINDOWS): 09:20:30 is still inside, 09:21:00 is the first moment outside."""
    minute = t.time().replace(second=0, microsecond=0)
    return any(start <= minute <= end for start, end in FREEZE_WINDOWS)


def freeze_slot(t: datetime) -> datetime:
    """t when it is outside the freeze windows, else the minute after the window it falls in (09:21 / 21:16): where a
    heavy gold data job that would land inside one is moved to. Unlike backup_slot there is no lead margin — the gold
    jobs are a few HTTP fetches, not a 20-minute copy of the DuckDB."""
    minute = t.time().replace(second=0, microsecond=0)
    for start, end in FREEZE_WINDOWS:
        if start <= minute <= end:
            return t.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0) + timedelta(minutes=1)
    return t


def plan_backup_catchup(now: datetime, dest: Path | None = None, not_before: datetime | None = None) -> datetime | None:
    """When to run today's missed backup once, or None: not missed (before 02:15, or today's backup exists), or the
    slot would fall after midnight (the next 02:15 run is close then). `not_before` is the start-up data catch-up's
    slot: the backup goes BACKUP_CATCHUP_DELAY after it."""
    if now.time() < BACKUP_TIME or backup_done_today(now, dest):
        return None
    when = backup_slot(max(now, not_before or now) + BACKUP_CATCHUP_DELAY)
    return when if when.date() == now.date() else None


# a one-off date job keeps APScheduler's default misfire grace of 1 s: a late loop would drop the catch-up silently.
# Late is fine (the job re-checks the date, the backup and the freeze windows when it fires).
BACKUP_CATCHUP_MISFIRE_S = 6 * 3600


async def db_backup_catchup() -> None:
    """One run of the nightly backup after start-up, today's having been missed (P7). Re-checks when it fires: waits
    while the data catch-up writes the DuckDB, does nothing if today's backup appeared or midnight passed, and
    moves itself to the end of a freeze window it would run into. It runs db_backup_daily itself, so it shares that
    job's lock and db_backup.py's file lock: never two backups at once."""
    JOB = "db_backup_catchup"
    waited = 0
    while _get_lock("startup_catchup").locked() and waited < BACKUP_CATCHUP_MAX_WAIT_S:
        await asyncio.sleep(BACKUP_CATCHUP_POLL_S)
        waited += BACKUP_CATCHUP_POLL_S
    if _get_lock("startup_catchup").locked():
        _log.warning(JOB, "the data catch-up is still running: left to tonight's 02:15 backup")
        return
    now = datetime.now(IST)
    if now.time() < BACKUP_TIME:
        _log.info(JOB, "not needed any more: tonight's 02:15 backup is next")
        return
    if backup_done_today(now):
        _log.info(JOB, "not needed any more: today's backup exists")
        return
    slot = backup_slot(now)
    if slot > now:
        if scheduler is not None:
            scheduler.add_job(db_backup_catchup, trigger="date", run_date=slot, id="db_backup_catchup",
                              name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True,
                              misfire_grace_time=BACKUP_CATCHUP_MISFIRE_S, coalesce=True)
        _log.info(JOB, f"freeze window: moved to {slot:%H:%M}")
        return
    _log.info(JOB, f"today's {BACKUP_TIME:%H:%M} backup is missing: running it now")
    await db_backup_daily()


def _stderr_reason(stderr: str | None) -> str:
    """The line that says what went wrong: a traceback's last line (the exception), else the last line."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "no stderr"


async def news_track_record_daily() -> None:
    """19:45 IST Mon–Fri — refresh the news scanner's track record (reports/news_scanner/, News Terminal view).
    A failed run (non-zero exit, timeout) raises a WARNING alert and shows as `error` on SYS: from 15 to 23 Oct it
    crashed every evening and only logged it, so the track record silently stayed at 14 Oct (P6)."""
    JOB = "news_track_record_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "news_scan_performance.py")]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=1800,
                                          cwd=str(_ROOT),
                                          env={**os.environ, "PYTHONPATH": str(_ROOT), **_evening_snapshot_env()})
            if res.returncode == 0:
                _log.info(JOB, "track record refreshed")
            else:
                _mark_failed(JOB)
                _log.error(JOB, f"news_scan_performance failed (exit {res.returncode})", stderr=res.stderr[-400:])
                await _alerts.warning("News track record failed",
                                      f"exit {res.returncode}: {_stderr_reason(res.stderr)}\n"
                                      "The track record keeps its last good run. Log: .logs/master-controller.log")
        except Exception as exc:
            _mark_failed(JOB)
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.warning("News track record failed", f"{type(exc).__name__}: {str(exc)[:200]}")


async def alpha_shadow_daily() -> None:
    """19:50 IST Mon–Fri — S1/S1H paper forward shadow (alpha_lab/paper/shadow.py --daily). Replay-based:
    safe to miss days, never places orders, messages Telegram on fill days and Fridays. A failed run (non-zero exit,
    timeout, a spawn error) records `error` on SYS (6 Nov checker: it recorded "done", so the start-up replay report
    said the shadow "replayed every missed session" beside its own "S1 shadow job failed" warning)."""
    JOB = "alpha_shadow_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        cmd = [PYTHON_BIN, str(_ROOT / "alpha_lab" / "paper" / "shadow.py"), "--daily"]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=600,
                                          cwd=str(_ROOT),
                                          env={**os.environ, "PYTHONPATH": str(_ROOT / "alpha_lab"),
                                               **_evening_snapshot_env()})
            if res.returncode == 0:
                _log.info(JOB, "shadow refreshed")
            else:
                _mark_failed(JOB)
                _log.error(JOB, f"shadow failed (exit {res.returncode})", stderr=(res.stderr or "")[-400:])
                await _alerts.warning("S1 shadow job failed",
                                      f"exit {res.returncode}: {_stderr_reason(res.stderr)}\n"
                                      "The shadow keeps its last good run. Log: .logs/master-controller.log")
        except Exception as exc:
            _mark_failed(JOB)
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.warning("S1 shadow job failed", f"{type(exc).__name__}: {str(exc)[:200]}")


# Newest row must be no older than this many days; older means the NSE source moved or the job is failing
# silently (the insider feed did exactly that on 5 May 2026). Mirrors ui/components/NseDatasets.tsx. The gold rows
# (PLAN §c.3: COT 9 days = weekly plus a holiday shift; curve/bars/VOI 4; ETF 5) come from data-service's positions
# meta once B1 adds the gold tables to it, so the 08:30 check and the WHSE panel cover gold with no new code path.
# DATASET_MAX_AGE_DAYS (a flat "days old" per table) is retired (Terminal v2 1.4): the freshness rule is B1's
# dataset_catalog `expected_by` (HH:MM IST, trading-day aware) + `max_age` in sessions, classified by ui-api's
# /api/data/health; _check_dataset_freshness below reads that view. GOLD_MAX_AGE_DAYS stays for the /status gold line.


def gold_freshness_line(tables: dict[str, Any], today: date) -> str:
    """The Telegram /status line for gold: the newest date per stored gold table, STALE-flagged past its max age
    (GOLD_MAX_AGE_DAYS); 'not ingested yet' until data-service's positions meta carries a gold table."""
    parts: list[str] = []
    seen = False
    for table, label in GOLD_STATUS_TABLES:
        row = tables.get(table)
        if not isinstance(row, dict):
            continue
        seen = True
        last = row.get("last")
        if not last:
            parts.append(f"{label} —")
            continue
        try:
            d = date.fromisoformat(str(last)[:10])
        except ValueError:
            parts.append(f"{label} ?")
            continue
        age = (today - d).days
        stale = age > GOLD_MAX_AGE_DAYS.get(table, 7)
        parts.append(f"{label} {d:%d %b}" + (f" ⚠ STALE ({age} d)" if stale else ""))
    if not seen:
        return "Gold data: not ingested yet (data-service has no gold tables)"
    return "Gold through: " + " · ".join(parts)


_FRESHNESS_BLIND_WARNED: dict[str, str] = {}


async def _check_dataset_freshness(job: str) -> list[str]:
    """Alert (critical) on every catalogued dataset ui-api's /api/data/health (B3) classes `red`: due by its `expected_by`
    (IST, trading-day aware) and more than `max_age` sessions behind the last close, or nothing stored — the Terminal v2
    1.4 rule that replaced the flat DATASET_MAX_AGE_DAYS. Amber (due, within max_age) is the view's and the hourly
    check's business; a `gap` row is explicit and unrecoverable (a session-bound capture that did not happen), never
    "stale". Called after the 08:30 sync and the 18:30 pipeline, when the F&O rows are not due yet (fresh)."""
    health = await _data_health(job)
    if health is None:
        # the old DATASET_MAX_AGE_DAYS net is gone: silence must be visible (check:B2-CTRL) — one WARNING line a day
        # (e.g. ui-api still on the pre-v2 release, whose /api/data/health is data-service's /health relay)
        day = datetime.now(IST).date().isoformat()
        if _FRESHNESS_BLIND_WARNED.get("day") != day:
            _FRESHNESS_BLIND_WARNED["day"] = day
            await _alerts.warning("Freshness check has no data-health view",
                                  f"ui-api {DATA_HEALTH_API} did not answer with dataset rows, so no stale-feed alert can fire "
                                  "today. Restart ui-api on the Terminal v2 release (outside 07:55–08:10); SYS › DATA shows the rows.")
        return []
    red = [r for r in health_rows(health) if r.get("state") == "red"]
    stale = [f"{r['id']}: {r.get('note') or 'nothing stored'}" for r in red]
    if stale:
        _log.warning(job, "stale datasets: " + "; ".join(stale))
        gold = [r for r in red if str(r["id"]).startswith("gold_")]
        title = "Gold data feed stale" if len(gold) == len(red) else ("Data feed stale" if gold else "NSE data feed stale")
        docs = sorted({str(r.get("dictionary_anchor")).split("#")[0] for r in red if r.get("dictionary_anchor")})
        hint = (f"\nThe source may have moved: see docs/{', docs/'.join(docs)}." if docs
                else "\nThe source may have moved: see docs/NSE_DATA_DICTIONARY.md.")
        await _alerts.critical(title, "\n".join(stale) + hint + "\nSYS › DATA has every row with its expected-by time.")
    return stale


async def nse_filings_weekly() -> None:
    """Saturday 09:00 IST — insider trades + new shareholding filings for the liquid universe."""
    JOB = "nse_filings_weekly"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        try:
            result = await _run_data_job(JOB, "/jobs/ingest-nse-filings", {})
            _log.info(JOB, f"symbols={result.get('symbols')} insider_rows={result.get('insider_rows')} "
                           f"shareholding_rows={result.get('shareholding_rows')} failures={result.get('failure_count')}")
            await _check_dataset_freshness(JOB)
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.critical("NSE filings weekly FAILED", str(exc))


async def nse_insider_daily() -> None:
    """21:50 IST Mon–Fri — insider (PIT) filings of the last 7 days from NSE's single-filing feed (corporates-pit-gg): one
    list call per window plus the XBRL of filings not stored yet (data-service skips the known ones), so INSD is current
    every evening instead of once a week (5 Nov 2026: it read STALE · 6 d mid-week). After the close and after the
    18:30–21:15 window, so its NSE requests never compete with the live quote fallback in session. A missed evening is
    covered by the next one's 7-day window and by Saturday's nse_filings_weekly (shareholding + the legacy feed)."""
    JOB = "nse_insider_daily"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        if not DATA_JOBS_ENABLED:
            return
        since = (datetime.now(IST).date() - timedelta(days=7)).isoformat()
        try:
            result = await _run_data_job(JOB, "/jobs/ingest-nse-filings", {"datasets": ["insider_gg"], "insider_since": since})
            _log.info(JOB, f"since={since} filings={result.get('filings')} new={result.get('parsed')} rows={result.get('rows')} "
                           f"known={result.get('skipped_known')} failures={len(result.get('failures') or [])}")
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")
            await _alerts.warning("NSE insider filings (daily) FAILED", str(exc)[:500])


async def weekly_journal() -> None:
    """Friday 20:10 IST — the week's decision journal (A2): Desk/shadow actions, vetoes that fired,
    regime, NAV vs NIFTY, next decisions and job failures, as reports/journal/<YYYY-WW>.md plus a
    Telegram digest. Deterministic template (scripts/journal_composer.py) — no LLM; the composer
    reads ui-api (which proxies this controller's telemetry) and the alpha_lab shadow artifacts,
    and NEVER sends messages itself: the digest goes out below via the AlertDispatcher."""
    JOB = "weekly_journal"
    lock = _get_lock(JOB)
    if lock.locked():
        return
    async with lock, _track(JOB):
        cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "journal_composer.py"), "--base", UI_API]
        try:
            res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300,
                                          cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)})
            last = (res.stdout.strip().splitlines() or [""])[-1]
            if res.returncode == 0 and last.startswith("RESULT "):
                result = json.loads(last[7:])
                _log.info(JOB, f"{result['path']}: {result['summary']}")
                await asyncio.to_thread(_record_notification, "journal",
                                        f"Weekly journal {result['week']}", result["summary"] or "written")
                await _alerts.info(f"Weekly journal {result['week']}",
                                   result.get("telegram") or result["summary"] or "written")
            else:
                _log.error(JOB, "weekly_journal failed", stderr=res.stderr[-400:])
        except Exception as exc:
            _log.error(JOB, f"FAILED: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# ICICI Breeze daily session: unattended TOTP login (scripts/daily_session_refresh.py).
# Rejections (bad password/code, captcha, SMS-only OTP) are never retried — a broker
# locks the account after repeated failures — only timeouts/network errors get one retry.
# Opt out: ICICI_AUTO_LOGIN=0.
# ══════════════════════════════════════════════════════════════════════════════

ICICI_AUTO_LOGIN = os.getenv("ICICI_AUTO_LOGIN", "1") == "1"
SESSION_REFRESH_SCRIPT = str(_ROOT / "scripts" / "daily_session_refresh.py")
_bg_tasks: set[asyncio.Task] = set()


async def _run_session_refresh(extra: tuple[str, ...] = ()) -> tuple[int, dict]:
    cmd = [PYTHON_BIN, SESSION_REFRESH_SCRIPT, "--headless", *extra]
    try:      # up to 5 min of it may be waiting for the SMS OTP you send on Telegram
        proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True,
                                       timeout=480, cwd=str(_ROOT))
    except subprocess.TimeoutExpired:
        return 3, {"status": "retry", "detail": "refresh script timed out after 8 min"}
    result = {"status": "error", "detail": (proc.stderr or proc.stdout or "no output")[-400:]}
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT "):
            try:
                result = json.loads(line[len("RESULT "):])
            except ValueError:
                pass
            break
    return proc.returncode, result


async def _ensure_live_prices(attempts: int = 3) -> bool:
    """After a login, data-service must hold the new session for ICICI live quotes. ui-api pushes it once; on 14 Oct
    that one connect hit an ICICI connection reset and quotes stayed off all afternoon. Check, and reconnect if needed."""
    async with httpx.AsyncClient(timeout=90) as client:
        for i in range(attempts):
            try:
                if (await client.get(f"{DATA_SVC}/provider/status")).json().get("connected"):
                    return True
                # send the token from .env (the login job saved it there; data-service's own environment may still
                # hold the previous one); an empty value is left out so data-service uses its environment (P3)
                creds = {"api_key": _env_file_value("ICICI_API_KEY"), "api_secret": _env_file_value("ICICI_API_SECRET"),
                         "session_token": _env_file_value("ICICI_SESSION_TOKEN")}
                r = await client.post(f"{DATA_SVC}/provider/configure", json={k: v for k, v in creds.items() if v})
                if r.json().get("connected"):
                    _log.info("icici_session_refresh", "data-service live quotes reconnected")
                    return True
            except Exception as exc:  # noqa: BLE001
                _log.warning("icici_session_refresh", f"live-quote reconnect {i + 1}/{attempts}: {type(exc).__name__}: {exc}")
            await asyncio.sleep(10 * (i + 1))
    _log.error("icici_session_refresh", "data-service could not connect to ICICI: live quotes off (Yahoo/NSE in use)")
    return False


def _login_running() -> bool:
    """One ICICI login at a time: a second one would text another OTP and invalidate the first."""
    return _get_lock("icici_session_refresh").locked() or bool(_login_task and not _login_task.done())


FORCE_LOGIN_BLACKOUT = (time(9, 0), time(15, 30))      # a forced login ends today's session and drops live quotes (PLAN §g)


def force_refusal(now: datetime) -> str | None:
    """Why a forced ICICI login (`?force=1`) is refused right now, or None: never during NSE trading hours on a weekday
    — the BRKR panel disables its button then too (PLAN §g step 4) and the owner's attended test is after 15:40."""
    if now.weekday() < 5 and FORCE_LOGIN_BLACKOUT[0] <= now.time() <= FORCE_LOGIN_BLACKOUT[1]:
        return ("a forced login ends today's ICICI session and drops live quotes: refused 09:00–15:30 on trading days "
                "(use it after 15:40)")
    return None


def otp_hint(detail: str) -> str:
    """The Telegram hint for a login that needs you: the SMS-code path only when the detail names an SMS OTP (a word
    boundary: 'TOTP' — the authenticator secret being unusable — is not an OTP you can reply with; G-LOGIN §9.3).
    An unusable authenticator key is not a password problem (5 Nov: the stored value was not a base32 setup key and
    the hint said "/password"): /login stops at the same check until the key is replaced or removed."""
    if "TOTP_SECRET is unusable" in detail:
        return ("The stored authenticator key is not a TOTP setup key (A–Z, 2–7, usually 16–32 characters). Replace it: "
                "security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w (it prompts), or remove it: "
                "security delete-generic-password -s suryadhana -a ICICI_TOTP_SECRET, then /login takes the SMS code.")
    return ("Send /login when you can reply with the SMS code." if re.search(r"\bOTP\b", detail)
            else "On Telegram: /password (or /userid) to fix it, then /login.")


async def special_session_login() -> None:
    """Log in to ICICI before an MCX SPECIAL session (Muhurat), which the Mon–Fri 08:00 job never covers.

    8 Nov 2026: today's Muhurat session (pre-open 14:05, trading 14:20–15:30) fell on a Sunday, so without this there is no
    broker session — no live MCX quote on GOLD / MCXG and, worse, no last-30-min VWAP for the session, which is the baseline
    Monday's 08:45 fair open is measured against. Does nothing on an ordinary day."""
    JOB = "special_session_login"
    now = datetime.now(IST)
    sp = mcx_specs.special_session_on(now.date())
    if not sp:
        return
    _log.info(JOB, f"{sp['name']}: pre-open {sp['pre_open']}, trading {sp['opens']}–{sp['closes']} — logging in")
    await icici_session_refresh()


async def india_imports_watch() -> None:
    """Fetch India's monthly gold-import figure from PIB once it is published, and store it if it is unambiguous.

    This is the one gold number with no machine-readable feed: the trade portal is a form with no download and RBI
    answers an automated XLSX download with a captcha (both probed 8 Nov 2026). PIB — the government's press agency —
    does answer, and the Commerce Ministry's monthly release states the figure in prose, so this job reads it there.

    It runs on the days around publication (the release lands about the 15th) and does nothing once the month is stored.
    `--store` writes ONLY when the figure's own sentence names the month it is claimed for; a year-earlier comparison, a
    quarter or a year-to-date total is reported for the owner to read instead of being stored under the wrong date. The
    stored source string carries the PRID and the sentence, so any row can be audited and revised later.
    """
    JOB = "india_imports_watch"
    if not GOLD_JOBS_ENABLED:
        return
    now = datetime.now(IST)
    month = (now.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    try:                                        # already stored (by this job, or typed by the owner)? then stay quiet
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{DATA_SVC}/db/gold/series",
                                 params={"ids": "INDIA_GOLD_IMPORTS_USD_BN", "freq": "M"})
        if r.status_code == 200:
            pts = ((r.json().get("series") or [{}])[0] or {}).get("points") or []
            if any(str(pt.get("report_date", ""))[:7] == month for pt in pts):
                return
    except Exception as exc:                    # noqa: BLE001  — a read failure is not a reason to skip the fetch
        _log.info(JOB, f"could not read the stored series ({type(exc).__name__}); looking for the release anyway")
    cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "gold_india_imports_find.py"), "--month", month, "--store"]
    try:
        res = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=300,
                                      cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)})
    except Exception as exc:                    # noqa: BLE001
        _log.warning(JOB, f"finder failed to run: {type(exc).__name__}")
        return
    out = (res.stdout or "").strip()
    _log.info(JOB, f"{month}: exit {res.returncode}")
    if res.returncode == 0 and "storing" in out:
        stored = next((ln for ln in out.splitlines() if ln.startswith("INDIA_GOLD_IMPORTS")), "")
        await _alerts.info(f"India gold imports {month} stored",
                           f"{stored or out.splitlines()[-1][:160]}\nRead from a PIB release; correct it with "
                           f"scripts/gold_india_imports.py if the release says otherwise.")
    elif res.returncode == 2:                   # found, but not unambiguous enough to store by itself
        link = next((ln.strip() for ln in out.splitlines() if "PressRelease" in ln), "")
        await _alerts.info(f"India gold imports {month}: needs your eye",
                           f"A PIB trade release is out but the figure is not unambiguous.\n{link}\n"
                           f"Store it with: python scripts/gold_india_imports.py --month {month} --usd-bn <figure>")
    # exit 3 (no release yet) and 4 (PIB did not answer) stay quiet: the job runs again tomorrow, and the
    # data-health row raises the month on the 16th if nothing is ever stored.


async def special_session_close() -> None:
    """After a SPECIAL session closes, store its last-30-min VWAP settlement while the broker session is still alive (the
    23:58 Mon–Fri job does not run on a Saturday or Sunday, and an ICICI session dies at midnight IST). The group also
    sweeps sessions no run ever stored, so a window missed during downtime is filled in the same pass."""
    JOB = "special_session_close"
    now = datetime.now(IST)
    if not mcx_specs.special_session_on(now.date()):
        return
    async with _get_lock(JOB), _track(JOB):
        out = await _gold_ingest("gold_mcx_close", ("mcx_close_vwap30", "derive_india"))
        _log.info(JOB, f"special-session settlement: {out}")


async def icici_session_refresh(startup: bool = False, force: bool = False) -> None:
    """08:00 IST Mon–Fri (and once at start-up on a trading morning): keep today's ICICI
    Breeze session alive; logs in unattended with TOTP when the token has expired. `force` (the BRKR panel's
    "force a new login", `?force=1` on /api/scheduler/icici-refresh) passes --force: a fresh login even if the token
    still works, which ends the current session. A run that needs you (rc 2) or fails after the retry is recorded as
    an error for SYS/history (_mark_failed), no longer as "done" (G-LOGIN §9.2)."""
    JOB = "icici_session_refresh"
    lock = _get_lock(JOB)
    if _login_running():
        _log.warning(JOB, "Already running — skipped")
        return
    async with lock, _track(JOB):
        if not ICICI_AUTO_LOGIN:
            _log.info(JOB, "ICICI_AUTO_LOGIN=0 — skipped")
            return
        extra: tuple[str, ...] = ("--quiet-minutes", "30") if startup else ()
        if force:
            extra += ("--force",)
            _log.info(JOB, "forced login requested (--force): today's session ends and a fresh TOTP login runs")
        result: dict = {}
        for attempt in (1, 2):
            rc, result = await _run_session_refresh(extra)
            if rc == 0:
                _log.info(JOB, f"{result.get('status')}: {result.get('detail')}")
                if result.get("status") == "skipped":
                    return
                if result.get("status") == "refreshed":
                    if result.get("outcome") == "warning":   # saved to .env only: ui-api did not take the token (P3)
                        await _alerts.warning("ICICI session refreshed via .env only", str(result.get("detail")))
                    else:
                        await _alerts.info("ICICI session refreshed", str(result.get("detail")))
                if result.get("status") in ("refreshed", "valid"):
                    await _ensure_live_prices()
                return
            if rc == 2:
                _mark_failed(JOB)
                detail = str(result.get("detail") or "")
                _log.error(JOB, f"needs you: {detail}")
                await _alerts.critical("ICICI login needs you", f"{detail}. {otp_hint(detail)}")
                return
            _log.warning(JOB, f"attempt {attempt} failed: {result.get('detail')}")
            if attempt == 1:
                await asyncio.sleep(300)
        _mark_failed(JOB)
        await _alerts.critical("ICICI session refresh FAILED", str(result.get("detail")))


# ══════════════════════════════════════════════════════════════════════════════
# Telegram bot: commands from your phone (scripts/telegram_bot.py). Answers TELEGRAM_CHAT_ID only.
# ══════════════════════════════════════════════════════════════════════════════
import telegram_bot as tgbot  # noqa: E402

_TG_OFFSET = _ROOT / "data" / "telegram_offset.json"
_login_task: Optional[asyncio.Task] = None


async def _tg_call(client: httpx.AsyncClient, method: str, **payload: Any) -> Any:
    r = await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}", json=payload)
    return r.json() if r.status_code == 200 else None


async def _tg_send(client: httpx.AsyncClient, text: str) -> None:
    """HTML reply in ≤ 4,096-character parts; plain text if Telegram can't parse a part."""
    for part in tgbot.chunks(text):
        ok = await _tg_call(client, "sendMessage", chat_id=TELEGRAM_CHAT_ID, text=part, parse_mode="HTML",
                            disable_web_page_preview=True)
        if ok is None:
            import re as _re
            await _tg_call(client, "sendMessage", chat_id=TELEGRAM_CHAT_ID, text=_re.sub(r"<[^>]+>", "", part))


def _env_set(key: str, value: str) -> None:
    sys.path.insert(0, str(_ROOT / "scripts"))
    from daily_session_refresh import write_env_value
    write_env_value(key, value)


async def _bot_login(args: list[str]) -> str:
    """/login: ICICI login in the background (it waits for your OTP); the result arrives as its own message."""
    global _login_task
    if _login_running():
        return "An ICICI login is already running. If ICICI texted you an OTP, reply with the 6 digits."
    if not (args and args[0].lower() in ("anyway", "force")):
        try:                     # the same user ID + password ICICI already rejected: don't burn another attempt
            sys.path.insert(0, str(_ROOT / "scripts"))
            from daily_session_refresh import blocked_reason, credential_fingerprint
            reason = blocked_reason(credential_fingerprint(_env_file_value("ICICI_CLIENT_ID"), _env_file_value("ICICI_PASSWORD")))
        except Exception:  # noqa: BLE001
            reason = None
        if reason:
            return (f"⛔ Not logging in: ICICI already rejected this user ID + password ({tgbot.esc(reason)}). "
                    "Repeated failures can lock the account. Fix it with /password or /userid, "
                    "or send <code>/login anyway</code> to try the same ones again.")

    async def run() -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            rc, res = await _run_session_refresh(("--ignore-block",))
            status, detail = res.get("status"), tgbot.esc(res.get("detail") or "")
            if rc == 0:
                msg = ("✅ ICICI session already valid." if status == "valid"
                       else f"⚠️ ICICI logged in, but: {detail}" if res.get("outcome") == "warning"
                       else f"✅ ICICI logged in: {detail}")
                msg += ("\nLive ICICI prices: on." if await _ensure_live_prices()
                        else "\n⚠️ Live ICICI prices didn't connect (prices stay on Yahoo/NSE); I'll retry at the next check.")
            elif "Invalid Credentials" in (res.get("detail") or "") or "rejected the login" in (res.get("detail") or ""):
                msg = (f"❌ ICICI rejected the user ID / password: {detail}\n"
                       "Send /password YOUR_PASSWORD (your message is deleted at once), then /login.")
            else:
                msg = f"⚠️ ICICI login did not finish ({tgbot.esc(status)}): {detail}"
            _log.info("telegram_login", f"rc={rc} {status}: {(res.get('detail') or '')[:160]}")
            await _tg_send(client, msg)

    _login_task = asyncio.create_task(run())
    return ("🔐 Starting the ICICI login with the user ID and password in .env. If ICICI texts you an OTP I will ask "
            "for it here: reply with the 6 digits.")


async def _bot_password(args: list[str]) -> str:
    if not args:
        return "Usage: /password YOUR_ICICI_PASSWORD (your message is deleted at once)"
    new = " ".join(args)
    if new == os.getenv("ICICI_PASSWORD", "") or new == _env_file_value("ICICI_PASSWORD"):
        block = _ROOT / ".icici_login_block.json"
        if block.exists():
            return ("⚠️ That is the password already saved, and ICICI rejected it (\"Invalid Credentials\"). "
                    "Your message was deleted. /login would fail again and repeated failures can lock the account: "
                    "check it on icicidirect.com first, then send the one that works.")
        return "🔑 That password is already saved. Your message was deleted. Send /login to use it."
    _env_set("ICICI_PASSWORD", new)
    return (f"🔑 ICICI password updated in .env ({len(new)} characters). Your message was deleted. "
            "Send /login to use it.")


def _env_file_value(key: str) -> str:
    try:
        from dotenv import dotenv_values
        return dotenv_values(_ROOT / ".env").get(key) or ""
    except Exception:  # noqa: BLE001
        return ""


async def _bot_userid(args: list[str]) -> str:
    if not args or not args[0].isalnum():
        return "Usage: /userid YOUR_ICICI_USER_ID"
    _env_set("ICICI_CLIENT_ID", args[0].upper())
    return f"🪪 ICICI user ID updated in .env ({tgbot.esc(args[0][:2].upper())}…{tgbot.esc(args[0][-2:].upper())}). Send /login to use it."


async def _bot_shadow(args: list[str]) -> str:
    """/shadow: the S1/S1H paper shadow's status file (alpha_lab; refreshed nightly at 19:50)."""
    f = _ROOT / "alpha_lab" / "reports" / "shadow_status.md"
    if not f.exists():
        return "The paper shadow has not produced a status yet (first run 19:50 IST)."
    return "<b>S1 paper shadow</b>\n<pre>" + tgbot.esc(f.read_text()[:3400]) + "</pre>"


# ── /status helpers (desktop review C-SECREL: SECREL-12, the desktop app line, ui-api shown HUNG on a timeout) ──
BOT_HEALTH_TIMEOUT_S = 8.0     # the watchdog's /health limit: a service slower than this is "hung" there too
_APP_BUNDLES = (Path("/Applications/SuryaDhana.app"), Path.home() / "Applications" / "SuryaDhana.app")
_APP_LOGIN_PLIST = Path.home() / "Library" / "LaunchAgents" / "SuryaDhana.plist"
_DEADMAN_STATE = _ROOT / ".pids" / "watchdog" / "deadman"      # "<epoch> ok|fail|error", written by stack_watchdog.sh


async def _bot_health(client: httpx.AsyncClient, name: str, base: str) -> tuple[bool, str]:
    """One service's line: up; HUNG (listening, /health timed out: the 25 Oct ui-api wedge, which /status used to show
    as a plain red dot); down (nothing listening); or the HTTP status it answered."""
    try:
        r = await client.get(f"{base}/health", timeout=BOT_HEALTH_TIMEOUT_S)
    except httpx.TimeoutException:
        return False, (f"🔴 {name} HUNG: listening, but /health gave no answer in {BOT_HEALTH_TIMEOUT_S:g} s. The watchdog "
                       f"restarts it about 3.5–5.5 min after it hung (data-service and master-controller: not inside "
                       f"a freeze window, and about 16 min while busy at high CPU; at most 3 restarts an hour). "
                       f"Now: <code>./start-local.sh restart {name}</code>")
    except httpx.ConnectError:
        return False, f"🔴 {name} down (not running): <code>./start-local.sh start {name}</code>"
    except httpx.HTTPError as exc:
        return False, f"🔴 {name}: /health failed ({type(exc).__name__})"
    if r.status_code != 200:
        return False, f"🔴 {name}: /health answered HTTP {r.status_code}"
    return True, f"🟢 {name}"


async def _bot_terminal_ui(client: httpx.AsyncClient) -> str:
    """SECREL-12: the release ui-api serves (GET /ready). Without one the terminal shows 'UI build not found' while
    every health light is green, so /status says so."""
    try:
        body = (await client.get(f"{UI_API}/ready", timeout=BOT_HEALTH_TIMEOUT_S)).json()
    except (httpx.HTTPError, ValueError):
        return "⚪ terminal UI: unknown (/ready did not answer)"
    ui = body.get("ui") if isinstance(body, dict) else None
    if ui == "ok":
        return f"🟢 terminal UI {tgbot.esc(str(body.get('ui_build_id') or '?'))}"
    if ui == "missing":
        return ("🔴 terminal UI MISSING: the app and the browser show 'UI build not found'. At the Mac: "
                "<code>./start-local.sh build-ui</code> (or <code>./start-local.sh build-ui --rollback</code>)")
    return f"⚪ terminal UI: {tgbot.esc(str(ui))}"


def _run_quiet(cmd: list[str]) -> str:
    """stdout of a short read-only command (ps, launchctl print, pmset -g, defaults read); '' on any failure."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _app_pids(exe: str) -> list[str]:
    """Pids whose command is the installed app's own executable (not a self-test or build copy under desktop/)."""
    out = []
    for line in _run_quiet(["ps", "-axo", "pid=,command="]).splitlines():
        pid, _, cmd = line.strip().partition(" ")
        cmd = cmd.lstrip()
        if cmd == exe or cmd.startswith(exe + " "):
            out.append(pid)
    return out


def _launchd_job_pid(label: str) -> str | None:
    for line in _run_quiet(["launchctl", "print", f"gui/{os.getuid()}/{label}"]).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "pid" and parts[1] == "=":
            return parts[2]
    return None


def _desktop_app_line() -> str:
    """The desktop app: installed, running (the installed bundle's executable), and who relaunches it after a crash:
    launchd (the Launch at Login job's own process), the crash guard a copy reopened from the Dock after Quit starts
    (app builds from 25 Oct round 3; `suryadhana-crash-guard <app pid>` in ps, as start-local.sh status checks), or
    nothing (an older build, or Launch at Login off)."""
    import plistlib

    app = next((p for p in _APP_BUNDLES if p.is_dir()), None)
    if app is None:
        return "⚪ desktop app: not installed (optional: the browser at http://127.0.0.1:8010 is the same terminal)"
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            ver = str(plistlib.load(f).get("CFBundleShortVersionString") or "?")
    except (OSError, ValueError, plistlib.InvalidFileException):
        ver = "?"
    pids = _app_pids(str(app / "Contents" / "MacOS" / "SuryaDhana"))
    if not pids:
        return f"⚪ desktop app {tgbot.esc(ver)}: not running (optional)"
    if not _APP_LOGIN_PLIST.exists():
        sup = "Launch at Login off: not relaunched after a crash"
    elif _launchd_job_pid("SuryaDhana") in pids:
        sup = "supervised by launchd"
    elif any(_run_quiet(["pgrep", "-f", "--", f"suryadhana-crash-guard {p} "]).strip() for p in pids):
        sup = "opened by hand: its crash guard relaunches it"
    else:
        sup = "opened by hand: not relaunched after a crash"
    return f"🟢 desktop app {tgbot.esc(ver)} running ({sup})"


def _deadman_line() -> str:
    """SECREL-02: the off-Mac dead-man ping (HEALTHCHECK_PING_URL) and the watchdog's last result. Never the URL."""
    if not _env_file_value("HEALTHCHECK_PING_URL"):
        return ("⚠️ No off-Mac alert: HEALTHCHECK_PING_URL is not set, so nobody is told if this Mac goes off or stops "
                "at the FileVault screen (RUNBOOK 'Off-machine dead-man ping')")
    try:
        at, res = _DEADMAN_STATE.read_text().split()[:2]
        age = _time.time() - int(at)
    except (OSError, ValueError):
        return "⚪ dead-man ping: configured, no ping recorded yet"
    if age > 600:
        return f"⚠️ dead-man ping: the last one was {int(age // 60)} min ago (is the watchdog running?)"
    line = {"ok": "🟢 dead-man ping ok", "fail": "🟠 dead-man ping: reported the stack unhealthy"}.get(
        res, "🔴 dead-man ping failing (no network, or a wrong URL)")
    return line + _watchdog_heartbeat_suffix()


_WATCHDOG_BEAT_STATE = _DEADMAN_STATE.with_name("deadman_watchdog")   # "<epoch> ok|error", the second heartbeat


def _watchdog_heartbeat_suffix() -> str:
    """Terminal v2 0.2: the watchdog's second heartbeat (HEALTHCHECK_WATCHDOG_URL, pinged on every run whatever the
    stack's state — it stops only when the Mac itself is off). Nothing when it is not configured."""
    if not _env_file_value("HEALTHCHECK_WATCHDOG_URL"):
        return ""
    try:
        at, res = _WATCHDOG_BEAT_STATE.read_text().split()[:2]
        age = _time.time() - int(at)
    except (OSError, ValueError):
        return " · watchdog heartbeat: configured, none recorded yet"
    if age > 600:
        return f" · watchdog heartbeat: last {int(age // 60)} min ago"
    return " · watchdog heartbeat ok" if res == "ok" else " · watchdog heartbeat failing (no network, or a wrong URL)"


def _reboot_recovery_line() -> str | None:
    """completeness-final-04: a warning when an unattended reboot would leave the stack down (None when fine)."""
    autorestart = next((ln.split()[1] for ln in _run_quiet(["pmset", "-g"]).splitlines()
                        if len(ln.split()) == 2 and ln.split()[0] == "autorestart"), None)
    auto_install = _run_quiet(["defaults", "read", "/Library/Preferences/com.apple.SoftwareUpdate",
                               "AutomaticallyInstallMacOSUpdates"]).strip()
    issues = []
    if autorestart == "0":
        issues.append("the Mac stays off after a power failure")
    if auto_install == "1":
        issues.append("macOS installs updates (and restarts) by itself")
    if not issues:
        return None
    return "⚠️ Unattended reboots: " + "; ".join(issues) + " (RUNBOOK 'Unattended reboots')"


def _mac_lines() -> list[str]:
    """The lines that need local commands (run in a thread: never on the event loop)."""
    lines = [_desktop_app_line(), _deadman_line()]
    reboot = _reboot_recovery_line()
    if reboot:
        lines.append(reboot)
    return lines


async def _bot_status(args: list[str]) -> str:
    lines = ["<b>System status</b>"]
    mac = asyncio.create_task(asyncio.to_thread(_mac_lines))
    async with httpx.AsyncClient(timeout=10) as client:
        (ds_ok, ds_line), (ui_ok, ui_line) = await asyncio.gather(
            _bot_health(client, "data-service", DATA_SVC), _bot_health(client, "ui-api", UI_API))
        lines += [ds_line, ui_line]
        if ui_ok:
            lines.append(await _bot_terminal_ui(client))
        try:
            lines += await mac
        except Exception:  # noqa: BLE001, S110 - the local checks are informational
            pass
        if ui_ok:          # a hung ui-api would only time out again on every call below
            try:
                pos = (await client.get(f"{UI_API}/api/positions/open-positions", timeout=30)).json()
                lines.append("🟢 ICICI session connected" if pos.get("connected") else
                             f"🔴 ICICI not connected: {tgbot.esc(str(pos.get('error') or '')[:120])} · /login")
            except Exception:  # noqa: BLE001 - any failure: unknown
                lines.append("⚪ ICICI: unknown")
        else:
            lines.append("⚪ terminal UI and ICICI: unknown (ui-api is not answering)")
        if tgbot.otp_pending():
            lines.append("🔐 An ICICI login is waiting for your OTP: reply with the SMS code")
        elif _login_running():
            lines.append("⏳ An ICICI login is running")
        if ui_ok:
            try:
                chk = (await client.get(f"{UI_API}/api/config/setup-status")).json().get("checks") or []
                todo = [c["title"] for c in chk if not c.get("ok")]
                lines.append("Setup to do: " + (tgbot.esc(", ".join(todo)) if todo else "nothing"))
            except Exception:  # noqa: BLE001, S110 - optional line
                pass
        if ds_ok:
            try:
                meta = (await client.get(f"{DATA_SVC}/db/nse-positions-meta")).json()
                t = meta.get("tables", meta)
                lines.append("Data through: bhavcopy " + str((t.get("nse_bhavcopy") or {}).get("last", "—"))[:10]
                             + " · F&amp;O " + str((t.get("nse_fo_daily") or {}).get("last", "—"))[:10])
                lines.append(tgbot.esc(gold_freshness_line(t, datetime.now(IST).date())))
            except Exception:  # noqa: BLE001, S110 - optional line
                pass
    if not mac.done():
        mac.cancel()
    jobs = scheduler.get_jobs() if scheduler is not None else []     # (None only before the lifespan starts it)
    nxt = sorted((j for j in jobs if j.next_run_time), key=lambda j: j.next_run_time)[:5]
    if nxt:
        lines.append("Next jobs: " + " · ".join(f"{j.next_run_time.astimezone(IST):%H:%M} {tgbot.esc(j.id)}" for j in nxt))
    return "\n".join(lines)


_BOT_ACTIONS = {"login": _bot_login, "password": _bot_password, "userid": _bot_userid, "status": _bot_status,
                "shadow": _bot_shadow}


async def _bot_get(path: str, **params: Any) -> Any:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{UI_API}{path}", params=params or None)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def _bot_put(path: str, body: dict) -> Any:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(f"{UI_API}{path}", json=body)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# ── Telegram parity for the typed alert engine (PLAN 2.3): /alerts list · /alert add <rule> ─────────────────────
# Behind the poller's chat-id check (the bot's only auth: messages from any other chat are ignored). Everything else —
# the legacy "/alerts" and "/alert TCS above 2400" price levels — stays with telegram_bot.handle unchanged.
_ALERT_CMD = re.compile(r"^/(alerts?)(?:@\w+)?\s+(list|add|snooze|resume|pause|del|fired)\b\s*(.*)$",
                        re.IGNORECASE | re.DOTALL)
ALERTS_FIRES_PATH = "/api/alerts/fires"
ALERT_ACTION_USAGE = ("Usage: <code>/alert snooze r-ab12cd34ef 60</code> (minutes, default 60) · "
                      "<code>/alert resume r-ab12cd34ef</code> · "
                      "<code>/alert pause r-ab12cd34ef</code> · <code>/alert del r-ab12cd34ef</code> · "
                      "<code>/alert fired</code>. "
                      "Ids: /alerts list. Price levels: /unalert TCS")
ALERT_ADD_USAGE = ("Usage: <code>/alert add iv_pctile:NIFTY above 80 repeat telegram</code> · "
                   "<code>/alert add price:TCS cross_up 4000</code> · <code>/alert add fii_net change_pct 50 window=1</code>\n"
                   "Ops: above · below · cross_up · cross_down · change_pct · pctile_above · pctile_below · changed. "
                   "Options: once | repeat · mac | telegram | both · window=N · cooldown=N · note=…")
ALERTS_LIST_MAX = 30


def alert_command(text: str) -> tuple[str, str] | None:
    """('list', '') for '/alerts list', ('add', '<rule text>') for '/alert add <rule>'; None for any other message (the
    legacy price-level commands keep their handler). '/alert list' and '/alerts add …' are accepted too. Pure."""
    m = _ALERT_CMD.match((text or "").strip())
    if not m:
        return None
    return m.group(2).lower(), m.group(3).strip()


def fmt_alert_rules(payload: Any) -> str:
    """The /alerts list reply (HTML): typed rules first, then the price levels; each rule's own summary line (ui-api's,
    direction-free), its state and its last fire. Pure."""
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        return "The alert engine did not answer (ui-api without the typed rules?). The price levels: /alerts"
    if not rules:
        return "No alert rules yet. " + ALERT_ADD_USAGE
    rules = sorted(rules, key=lambda r: (r.get("origin") == "price", str(r.get("created_at") or "")))
    lines = [f"<b>Alert rules</b> ({len(rules)})"]
    for r in rules[:ALERTS_LIST_MAX]:
        state = str(r.get("status") or "active")
        if state == "snoozed" and r.get("snooze_until"):
            state += f" to {str(r['snooze_until'])[11:16]}"
        last = f" · last fired {str(r['last_fired_at'])[5:16].replace('T', ' ')}" if r.get("last_fired_at") else ""
        lines.append(f"• {tgbot.esc(r.get('summary') or r.get('series') or r.get('id'))} — {tgbot.esc(state)}{tgbot.esc(last)}"
                     f" <code>{tgbot.esc(r.get('id') or '')}</code>")
    if len(rules) > ALERTS_LIST_MAX:
        lines.append(f"… and {len(rules) - ALERTS_LIST_MAX} more on the ALRT page")
    return "\n".join(lines)


def fmt_alert_fired(payload: Any) -> str:
    """The /alert fired reply: the last fires (price + typed) grouped by symbol, newest group first; each its own
    direction-free text (a relayed text with a direction word is withheld). Pure."""
    groups = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        return "The alert engine did not answer (ui-api without the typed rules?)."
    if not groups:
        return "Nothing has fired yet."
    lines = ["<b>Fired</b> (newest first)"]
    for g in groups[:10]:
        lines.append(f"<b>{tgbot.esc(g.get('symbol'))}</b> · {int(g.get('count') or 0)}")
        for f in (g.get("fires") or [])[:3]:
            when = str(f.get("at") or "")[5:16].replace("T", " ")
            lines.append(f"  {tgbot.esc(when)} {tgbot.esc(alert_text_or_withheld(f)[:220])}")
    return "\n".join(lines)


def fmt_alert_action(action: str, rule_id: str, res: Any) -> str:
    """The /alert snooze | resume | pause | del reply (None = ui-api refused or did not answer). Pure."""
    if not isinstance(res, dict):
        return (f"Could not {tgbot.esc(action)} <code>{tgbot.esc(rule_id)}</code>: an unknown id, a price level "
                f"(those: /unalert), or the engine did not answer. Ids: /alerts list")
    if res.get("deleted"):
        return f"Rule <code>{tgbot.esc(rule_id)}</code> deleted (its fires stay on ALRT)."
    state = str(res.get("status") or "")
    if state == "snoozed" and res.get("snooze_until"):
        state += f" to {str(res['snooze_until'])[11:16]}"
    return f"{tgbot.esc(res.get('summary') or rule_id)} — {tgbot.esc(state)} <code>{tgbot.esc(rule_id)}</code>"


def fmt_alert_added(res: Any) -> str:
    """The /alert add reply from PUT /api/alerts/rules/from-text ({ok, rule | error}; None = no answer). Pure."""
    if not isinstance(res, dict):
        return "Could not reach the alert engine (ui-api without the typed rules?). Nothing stored."
    if not res.get("ok"):
        return f"Not stored: {tgbot.esc(str(res.get('error') or 'invalid rule'))}\n{ALERT_ADD_USAGE}"
    rule = res.get("rule") or {}
    return (f"Rule stored: {tgbot.esc(rule.get('summary') or rule.get('series') or '')} "
            f"<code>{tgbot.esc(rule.get('id') or '')}</code>. It describes a level, not a call; /alerts list shows every rule.")


async def alert_bot_reply(text: str, get: Callable[..., Any], put: Callable[..., Any]) -> str | None:
    """The reply to /alerts list or /alert add <rule>, else None (the message goes to telegram_bot.handle)."""
    cmd = alert_command(text)
    if cmd is None:
        return None
    action, rest = cmd
    if action == "list":
        return fmt_alert_rules(await get(ALERTS_RULES_PATH))
    if action == "fired":
        return fmt_alert_fired(await get(ALERTS_FIRES_PATH, limit=30))
    if action in ("snooze", "resume", "pause", "del"):
        parts = rest.split()
        if not parts or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", parts[0]):
            return ALERT_ACTION_USAGE
        body: dict[str, Any] = {"action": "delete" if action == "del" else action}
        if action == "snooze":
            body["minutes"] = float(parts[1]) if len(parts) > 1 and re.fullmatch(r"\d{1,5}(\.\d+)?", parts[1]) else 60.0
        return fmt_alert_action(action, parts[0], await put(f"{ALERTS_RULES_PATH}/{parts[0]}/action", body))
    if not rest:
        return ALERT_ADD_USAGE
    return fmt_alert_added(await put(ALERTS_FROM_TEXT_PATH, {"text": rest}))


async def telegram_poller() -> None:
    """Long-poll Telegram for your messages and answer them. Messages from any other chat are ignored."""
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    async with httpx.AsyncClient(timeout=40) as client:
        await _tg_call(client, "setMyCommands",
                       commands=[{"command": c, "description": d[:255]} for c, _, d in tgbot.COMMANDS])
        try:
            offset = json.loads(_TG_OFFSET.read_text()).get("offset")
        except (OSError, ValueError):
            offset = None
        if offset is None:            # first start: skip whatever was sent before the bot existed
            res = await _tg_call(client, "getUpdates", timeout=0)
            ids = [u["update_id"] for u in (res or {}).get("result", [])]
            offset = (max(ids) + 1) if ids else 0
        while True:
            try:
                res = await _tg_call(client, "getUpdates", offset=offset, timeout=25, allowed_updates=["message"])
                for u in (res or {}).get("result", []):
                    offset = u["update_id"] + 1
                    _TG_OFFSET.write_text(json.dumps({"offset": offset}))
                    m = u.get("message") or {}
                    if str((m.get("chat") or {}).get("id")) != str(TELEGRAM_CHAT_ID):
                        continue                                  # not you: ignored
                    text = m.get("text") or ""
                    cmd = text.split()[0].lower() if text.startswith("/") else ""
                    if cmd in ("/password", "/userid"):        # secrets: remove the message from the chat first
                        await _tg_call(client, "deleteMessage", chat_id=TELEGRAM_CHAT_ID, message_id=m.get("message_id"))
                    _log.info("telegram", f"command {cmd or ('code' if text.strip().isdigit() else 'text')}")
                    try:
                        reply = await alert_bot_reply(text, _bot_get, _bot_put)
                        if reply is None:
                            reply = await tgbot.handle(text, _bot_get, _bot_put, _BOT_ACTIONS)
                    except Exception as exc:   # one bad command must not stop the bot
                        reply = f"⚠️ That failed: {tgbot.esc(type(exc).__name__)}: {tgbot.esc(str(exc)[:200])}"
                    await _tg_send(client, reply)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.warning("telegram", f"poll failed: {type(exc).__name__}: {exc}")
                await asyncio.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# Broker latency probe
# ══════════════════════════════════════════════════════════════════════════════

async def _probe_broker_latency() -> Optional[float]:
    try:
        t0 = _time.perf_counter()
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(f"{EXECUTION_SVC}/health")
        return round((_time.perf_counter() - t0) * 1000, 1)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI app + APScheduler lifespan
# ══════════════════════════════════════════════════════════════════════════════

scheduler: Optional[AsyncIOScheduler] = None


def _register_stack_dump_signal() -> None:
    """R-OPS-07: ``kill -USR1 <pid>`` writes every Python thread's stack to stderr (.logs/master-controller.log). A C-level
    handler, so it works while the event loop is stuck. scripts/stack_watchdog.sh sends USR1 before a hang restart,
    but only once it finds the JSON line below in the log since the last start (with no handler, USR1 kills)."""
    import faulthandler
    import signal

    try:
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
    except (AttributeError, RuntimeError, ValueError, OSError):
        return
    print(json.dumps({"event": "stack_dump_ready", "stack_dump_signal": "SIGUSR1", "pid": os.getpid()}),
          file=sys.stderr, flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global scheduler
    _register_stack_dump_signal()
    scheduler = AsyncIOScheduler(timezone=IST)
    # SYS job history from earlier runs (P14); arms saving each job's result from now on
    _log.info("scheduler", f"job history: {_history.load()} job(s) from {SCHEDULER_HISTORY_FILE.name}")
    _DATASET_CHECK["armed"] = True          # M33: from now on a run whose datasets did not move says "no new data"
    _CATCHUP_PLAN.clear()                    # a fresh start: only what THIS start schedules is a pending catch-up
    _CATCHUP_SCHEDULED.clear()

    # ── Pre-market sync: 08:30 IST ───────────────────────────────────────────
    scheduler.add_job(
        pre_market_sync,
        trigger=CronTrigger(hour=8, minute=30, timezone=IST),
        id="pre_market_sync",
        name="Pre-Market Data Sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ── Intraday inference: every 15 min 09:00–15:59 IST (market gate inside)
    scheduler.add_job(
        intraday_inference_cycle,
        trigger=CronTrigger(hour="9-15", minute="*/15", timezone=IST),
        id="intraday_inference",
        name="XGBoost + RL Inference Cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    # ── EOD rebalancing: 15:15 IST ───────────────────────────────────────────
    scheduler.add_job(
        eod_rebalancing,
        trigger=CronTrigger(hour=15, minute=15, timezone=IST),
        id="eod_rebalancing",
        name="EOD Portfolio Rebalancing",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # ── EOD data pipeline: 18:30 IST Mon–Fri (bars settled) ─────────────────
    scheduler.add_job(
        eod_data_pipeline,
        trigger=CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=IST),
        id="eod_data_pipeline",
        name="EOD Data Refresh + ML Dataset Build",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # ── Overnight RL retrain: 23:00 IST ─────────────────────────────────────
    scheduler.add_job(
        overnight_rl_retrain,
        trigger=CronTrigger(hour=23, minute=0, timezone=IST),
        id="overnight_rl_retrain",
        name="Overnight RL Retraining",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # ── Decision Desk (paper): 19:30 IST Mon–Fri, after the 18:30 EOD pipeline ──
    scheduler.add_job(
        desk_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=30, timezone=IST),
        id="desk_daily",
        name="Decision Desk — Paper Cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # ── Research datasets kept fresh: results release times, news scanner track record ──
    scheduler.add_job(
        results_capture_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=45, timezone=IST),
        id="results_capture_daily", name="Results Release Capture (NSE)",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    scheduler.add_job(
        news_track_record_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=45, timezone=IST),
        id="news_track_record_daily", name="News Scanner Track Record",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )

    # ── Shared evening snapshot (Bloomberg program F2.3) ──
    scheduler.add_job(
        shared_snapshot_build,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=20, timezone=IST),
        id="shared_snapshot_build", name="Shared Evening Snapshot",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )

    # ── Nightly DuckDB backup (Bloomberg program F1.3) ──
    scheduler.add_job(
        db_backup_daily,
        trigger=CronTrigger(hour=2, minute=15, timezone=IST),
        id="db_backup_daily", name="Nightly DuckDB Backup",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )

    # ── S1/S1H paper shadow (alpha_lab; owner started 15 Oct 2026) ──
    scheduler.add_job(
        alpha_shadow_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=50, timezone=IST),
        id="alpha_shadow_daily", name="S1 Paper Shadow (alpha_lab)",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )

    # ── Gold desk accuracy log: prediction before the MCX open, actual open after ──
    scheduler.add_job(
        gold_preopen_snapshot,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone=IST),
        id="gold_preopen_snapshot", name="Gold Pre-Open Snapshot (fair open)",
        max_instances=1, coalesce=True, misfire_grace_time=600,     # useless after 09:00
    )
    scheduler.add_job(
        price_alerts_check,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*", timezone=IST),
        id="price_alerts_check", name="Price Alerts (every minute in market hours)",
        max_instances=1, coalesce=True, misfire_grace_time=50,
    )
    scheduler.add_job(
        filing_alerts,
        trigger=CronTrigger(day_of_week="mon-sat", hour="8-22", minute="*/5", timezone=IST),
        id="filing_alerts", name="Filing Alerts for your stocks (every 5 min)",
        max_instances=1, coalesce=True, misfire_grace_time=240,
    )
    scheduler.add_job(
        financials_sweep,
        trigger=CronTrigger(day_of_week="sat", hour=10, minute=0, timezone=IST),
        id="financials_sweep", name="Financials sweep (FA / RV cache, weekly)",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    scheduler.add_job(
        internals_sample,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/2", timezone=IST),
        id="internals_sample", name="Market internals sample (breadth, every 2 min)",
        max_instances=1, coalesce=True, misfire_grace_time=90,
    )
    scheduler.add_job(
        move_alerts,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=IST),
        id="move_alerts", name="Move Alerts (holdings ±5/10%, NIFTY vs 200-DMA)",
        max_instances=1, coalesce=True, misfire_grace_time=240,
    )
    scheduler.add_job(
        close_note,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=40, timezone=IST),
        id="close_note", name="Closing Note",
        max_instances=1, coalesce=True, misfire_grace_time=3 * 3600,
    )
    scheduler.add_job(
        morning_note,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=50, timezone=IST),
        id="morning_note", name="Pre-market Note",
        max_instances=1, coalesce=True, misfire_grace_time=1800,     # useless after the open
    )
    scheduler.add_job(
        index_valuation_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=15, timezone=IST),
        id="index_valuation_daily", name="Index Valuation History",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    scheduler.add_job(
        daily_wrap,
        trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=0, timezone=IST),
        id="daily_wrap", name="Daily Market Wrap",
        max_instances=1, coalesce=True, misfire_grace_time=3 * 3600,
    )
    scheduler.add_job(
        preopen_capture,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=9, second=30, timezone=IST),
        id="preopen_capture", name="NSE Pre-open Book Capture",
        max_instances=1, coalesce=True, misfire_grace_time=3 * 3600,   # NSE keeps the book until the next session
    )
    scheduler.add_job(
        gold_open_capture,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=10, timezone=IST),
        id="gold_open_capture", name="Gold Open Capture (ICICI)",
        max_instances=1, coalesce=True, misfire_grace_time=2 * 3600,
    )
    # morning-closure MCX holidays (Dussehra, Diwali-Balipratipada, …): the day's first session opens 17:00
    scheduler.add_job(
        gold_open_capture,
        trigger=CronTrigger(day_of_week="mon-fri", hour=17, minute=10, timezone=IST),
        kwargs={"evening": True},
        id="gold_open_capture_evening", name="Gold Open Capture (ICICI, morning-closure days)",
        max_instances=1, coalesce=True, misfire_grace_time=2 * 3600,
    )

    # ── GOLD program ingest jobs (PLAN §c.3; GOLD_JOBS above): fetches into market.duckdb via data-service ──
    _log.info("scheduler", "gold jobs: " + ", ".join(register_gold_jobs(scheduler))
              + (" (GOLD_JOBS_ENABLED=0: registered, every run skips)" if not GOLD_JOBS_ENABLED else "")
              + "; dormant (O-8): " + ", ".join(GOLD_DORMANT_JOBS))

    # ── NSE positions catch-up (late evening files) and weekly company filings ──
    scheduler.add_job(
        nse_positions_catchup,
        trigger=CronTrigger(day_of_week="mon-fri", hour=20, minute=30, timezone=IST),
        id="nse_positions_catchup",
        name="NSE Positions Catch-up (OI, deals, MTF, evening files, drivers retry, iv_eod)",
        max_instances=1, coalesce=True, misfire_grace_time=3 * 3600,
    )
    # ── Terminal v2 (PLAN Wave 0 0.5, Wave 1.1 / 1.2 / 1.4): fetch + compute jobs on NSE's measured clock ──
    scheduler.add_job(
        index_drivers_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=19, minute=25, timezone=IST),
        id="index_drivers_daily", name="Index drivers (NIFTY 50 / NIFTY BANK contributions)",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        nse_evening_pass,
        trigger=CronTrigger(day_of_week="mon-fri", hour=22, minute=45, timezone=IST),
        id="nse_evening_pass", name="NSE evening pass (MTF T−1, bhavcopy revisions, FII/DII, results, iv_eod retry)",
        max_instances=1, coalesce=True, misfire_grace_time=3 * 3600,
    )
    scheduler.add_job(
        morning_sweep,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=35, timezone=IST),
        id="morning_sweep", name="Morning sweep (missing datasets + DATA digest)",
        max_instances=1, coalesce=True, misfire_grace_time=1800,
    )
    scheduler.add_job(
        iv_intraday_tick,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/2", timezone=IST),
        id="iv_intraday", name="Intraday OI / IV tape (Breeze chain through the budget ledger, every 2 min 09:15–15:30; cadence per tier planned to the budget)",
        max_instances=1, coalesce=True, misfire_grace_time=120,
    )
    scheduler.add_job(
        iv_weekly,
        trigger=CronTrigger(day_of_week="sat", hour=3, minute=0, timezone=IST),
        id="iv_weekly", name="IV weekly (rank / percentile recompute, catalog check)",
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    scheduler.add_job(
        data_health_check,
        trigger=CronTrigger(minute=10, timezone=IST),
        id="data_health_check", name="Data-health check (hourly; one Telegram line per transition)",
        max_instances=1, coalesce=True, misfire_grace_time=600,
    )
    scheduler.add_job(
        nse_insider_daily,
        trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=50, timezone=IST),
        id="nse_insider_daily",
        name="NSE insider filings (daily, last 7 days)",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        nse_filings_weekly,
        trigger=CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=IST),
        id="nse_filings_weekly",
        name="NSE Filings Weekly (insider, shareholding)",
        max_instances=1, coalesce=True, misfire_grace_time=12 * 3600,
    )
    # Friday 20:10 IST: after desk_daily (19:30) and alpha_shadow_daily (19:50) have refreshed their
    # artifacts, before nse_positions_catchup (20:30). A job, not a restart — the 18:30–21:15
    # restart-freeze window does not apply.
    scheduler.add_job(
        weekly_journal,
        trigger=CronTrigger(day_of_week="fri", hour=20, minute=10, timezone=IST),
        id="weekly_journal",
        name="Weekly Decision Journal (Friday)",
        max_instances=1, coalesce=True, misfire_grace_time=12 * 3600,
    )

    # ── ICICI session refresh: 08:00 IST Mon–Fri; big grace window so a Mac that
    #    wakes up late still logs in before the open ──────────────────────────
    scheduler.add_job(
        icici_session_refresh,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=IST),
        id="icici_session_refresh",
        name="ICICI Session Refresh (TOTP login)",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=4 * 3600,
    )
    # ── MCX special sessions (Muhurat): the Mon–Fri jobs above never fire on a Saturday or Sunday, so a special session
    #    would have no broker session and no stored settlement (8 Nov 2026). Both jobs return at once on an ordinary day.
    scheduler.add_job(
        special_session_login,
        trigger=CronTrigger(hour=13, minute=0, timezone=IST),
        id="special_session_login",
        name="ICICI login before an MCX special session (Muhurat)",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        special_session_close,
        trigger=CronTrigger(hour=15, minute=45, timezone=IST),
        id="special_session_close",
        name="MCX special-session settlement (VWAP30) while the session is alive",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    # ── India's monthly gold-import figure: the only gold number with no feed. PIB publishes it around the 15th, so look
    #    on the days after, at 11:15 (outside both freeze windows), and stop once the month is stored (8 Nov 2026).
    scheduler.add_job(
        india_imports_watch,
        trigger=CronTrigger(day="15-22", hour=11, minute=15, timezone=IST),
        id="india_imports_watch",
        name="India gold imports from the PIB monthly trade release",
        max_instances=1, coalesce=True, misfire_grace_time=7200,
    )
    # Started after 08:00 on a trading day (Mac just booted)? Check the session once now.
    _now = datetime.now(IST)
    if _now.weekday() < 5 and time(7, 0) <= _now.time() <= MARKET_CLOSE:
        scheduler.add_job(
            icici_session_refresh,
            trigger="date",
            run_date=_now + timedelta(seconds=45),
            kwargs={"startup": True},
            id="icici_session_refresh_startup",
            name="ICICI Session Refresh (start-up check)",
        )

    # downtime recovery: read the PREVIOUS run's heartbeat before this run starts writing its own
    started = datetime.now(IST)
    last_beat = read_heartbeat(HEARTBEAT_FILE)
    catchup: tuple[datetime, dict[str, int], str, datetime] | None = None
    if last_beat is not None and (started - last_beat) > timedelta(minutes=DOWNTIME_REPORT_MIN):
        missed = downtime_missed(scheduler.get_jobs(), last_beat, started)
        mode, when = plan_catchup(started, missed)
        catchup = (last_beat, missed, mode, when)
    # the key gold jobs the downtime catch-up re-runs WITH backfill_from (gold_downtime_catchup): the missed-today
    # one-offs below leave those alone — two runs of one job would race for its lock and the plain one could win
    gold_owned = {j for j in GOLD_KEY_JOBS if catchup is not None and catchup[1].get(j)}
    # the terminal jobs the data catch-up re-runs itself (0.9) — only when it will actually run (full / nse modes);
    # in the EOD-window "skip" mode the missed-today one-off is the run
    if catchup is not None and catchup[2] in ("full", "nse"):
        gold_owned |= {j for j in TERMINAL_CATCHUP_OWNED if catchup[1].get(j)}

    # catch up on today's jobs missed while the controller was down (Mac restarted, stack started late); a heavy gold
    # job never inside a freeze window (a boot at 08:05 runs gold_overnight once at 09:21, not at 08:06); the terminal
    # jobs are light fetches (the class PLAN §0.10 allows inside a window) and run as scheduled one-offs
    _catchup = {"preopen_capture": preopen_capture, "morning_note": morning_note, "daily_wrap": daily_wrap,
                "morning_sweep": morning_sweep, "index_drivers_daily": index_drivers_daily,
                "nse_positions_catchup": nse_positions_catchup, "results_capture_daily": results_capture_daily,
                "nse_evening_pass": nse_evening_pass, "iv_weekly": iv_weekly}
    for i, name in enumerate(missed_jobs(datetime.now(IST), _ROOT)):
        when = datetime.now(IST) + timedelta(seconds=60 + 30 * i)
        if name in gold_owned:
            _log.info("scheduler", f"missed today: {name} → left to the downtime catch-up (backfill from "
                                   f"{catchup[0]:%Y-%m-%d})" if catchup else f"missed today: {name}")
            continue
        if name in GOLD_JOBS:
            func, args = gold_runner(name)
            when = when if GOLD_JOBS[name].light else freeze_slot(when)
            scheduler.add_job(func, trigger="date", run_date=when, args=args, id=f"{name}_catchup",
                              name=f"{name} (catch-up after start)", misfire_grace_time=3600, coalesce=True)
        else:
            if name in TERMINAL_ONEOFF_DEFER:
                when = freeze_slot(when)
            scheduler.add_job(_catchup[name], trigger="date", run_date=when,
                              id=f"{name}_catchup", name=f"{name} (catch-up after start)")
        _note_catchup(name, when)
        _log.info("scheduler", f"missed today: {name} → running it once at {when:%H:%M}")

    # today's 02:15 backup missed (Mac off or asleep, controller down; P7): one run, outside the freeze windows,
    # after the data catch-up's slot. Independent of the heartbeat: a 2-minute restart across 02:15 misses it too.
    backup_when = plan_backup_catchup(started, BACKUP_DIR, not_before=catchup[3] if catchup else None)
    if backup_when is not None:
        scheduler.add_job(db_backup_catchup, trigger="date", run_date=backup_when, id="db_backup_catchup",
                          name="Nightly DuckDB Backup (catch-up after start)", replace_existing=True,
                          misfire_grace_time=BACKUP_CATCHUP_MISFIRE_S, coalesce=True)
        _log.warning("scheduler", f"today's {BACKUP_TIME:%H:%M} backup is missing — one run at {backup_when:%H:%M}")
    if catchup is not None:
        last_beat, missed, mode, when = catchup
        # M30: inside the EOD window ("skip") the evening jobs whose slot passed are replayed by the catch-up itself
        replay, later = evening_replay_plan(started, missed) if mode == "skip" else ([], [])
        for name in catchup_notes(mode, missed, replay):
            _note_catchup(name, when)
        scheduler.add_job(startup_catchup, trigger="date", run_date=when, id="startup_catchup",
                          name="Data catch-up after downtime",
                          args=[last_beat.isoformat(), started.isoformat(), missed, mode],
                          kwargs={"backup_at": backup_when.strftime("%H:%M") if backup_when else None,
                                  "replay": replay, "later": later})
        _log.warning("scheduler", f"controller was down since {last_beat.isoformat()} — {mode} catch-up at "
                                  f"{when.strftime('%H:%M')}" + (f" (replays {', '.join(replay)})" if replay else "")
                                  + f", missed: {missed}")
    write_heartbeat(HEARTBEAT_FILE, started)
    scheduler.add_job(write_heartbeat, trigger="interval", seconds=60, args=[HEARTBEAT_FILE],
                      id="controller_heartbeat", name="Controller heartbeat", max_instances=1, coalesce=True)

    scheduler.start()
    _log.info("scheduler", "APScheduler started (IST)", jobs=str(len(scheduler.get_jobs())), timezone="Asia/Kolkata")
    await _alerts.info("SuryaDhana Online", f"Master Controller started at {datetime.now(IST).strftime('%H:%M IST')}")
    bot = asyncio.create_task(telegram_poller())
    try:
        yield
    finally:
        _DATASET_CHECK["armed"] = False      # a stopped controller (or a test's lifespan) never GETs from _track again
    bot.cancel()
    scheduler.shutdown(wait=False)
    _log.info("scheduler", "APScheduler stopped")


app = FastAPI(
    title="SuryaDhana Master Controller",
    version="1.0.0",
    description="Autonomous IST-aware trading session scheduler + telemetry",
    lifespan=lifespan,
)

# No CORS (desktop review C2-security-07): the controller's only browser-facing client is ui-api's
# server-side proxy (/api/telemetry), so '*' CORS only let other websites drive autopilot and the ICICI
# login. Observability (PLAN 1.5): /metrics, X-Request-ID, JSON access log — inside the guard, which stays outermost.
install_observability(app, service="master-controller", thread_limit=None)
install_http_guard(app, service="master-controller")


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "master-controller",
        "scheduler_running": scheduler.running if scheduler else False,
        "ist_now": datetime.now(IST).isoformat(),
    }


# ── Scheduler status ──────────────────────────────────────────────────────────
def job_last_run(job_id: str, latency_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A job's last-run fields for /api/scheduler/status: from this run's latency tracker, else (nothing ran yet
    since the restart) from the persisted history (P14), so SYS no longer shows '—' after every restart.
    `last_run_source` (additive): "this_run", "history" or None (never ran). Latency average and sample count
    cover this run only."""
    st = latency_stats.get(job_id)
    if st:
        return {"last_latency_ms": st.get("last_ms"), "avg_latency_ms": st.get("avg_ms"),
                "last_status": st.get("last_status"), "last_run_ts": st.get("last_ts"),
                "samples": st.get("samples", 0), "last_run_source": "this_run"}
    h = _history.get(job_id)
    if h:
        return {"last_latency_ms": h.get("last_ms"), "avg_latency_ms": None, "last_status": h.get("last_status"),
                "last_run_ts": h.get("last_run_ts"), "samples": 0, "last_run_source": "history"}
    return {"last_latency_ms": None, "avg_latency_ms": None, "last_status": None, "last_run_ts": None,
            "samples": 0, "last_run_source": None}


_DOW = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def _cron_days(expr: str) -> str:
    if expr in ("*", "mon-sun"):
        return "daily"
    return ",".join("–".join(_DOW.get(x, x) for x in part.split("-")) for part in expr.split(","))


def describe_trigger(trigger: Any) -> str | None:
    """The IST schedule of a trigger in words for SYS's SCHEDULE column (m111: "—" for ≈ 30 jobs whose times were known
    only to a hand-kept UI table): "Mon–Fri 19:50", "Sat 02:30–06:30 hourly at :30", "every 5 min 09–15h Mon–Fri",
    "every 60 s", "once 21:16". Anything it cannot read falls back to the trigger's own text. Pure."""
    if trigger is None:
        return None
    kind = type(trigger).__name__
    try:
        if kind == "OrTrigger":
            return " · ".join(describe_trigger(t) or "" for t in trigger.triggers)
        if kind == "IntervalTrigger":
            secs = int(trigger.interval.total_seconds())
            return f"every {secs // 60} min" if secs % 60 == 0 and secs >= 120 else f"every {secs} s"
        if kind == "DateTrigger":
            return f"once {trigger.run_date.astimezone(IST):%a %d %b %H:%M}"
        if kind == "CronTrigger":
            f = {fld.name: str(fld) for fld in trigger.fields}
            days, hour, minute, second = _cron_days(f["day_of_week"]), f["hour"], f["minute"], f["second"]
            sec = "" if second in ("0", "*") else f":{int(second):02d}"
            if hour.isdigit() and minute.isdigit():
                when = f"{int(hour):02d}:{int(minute):02d}{sec}"
            elif minute.isdigit():
                hrs = "hourly" if hour == "*" else f"{hour.replace('-', '–')}h hourly"
                when = f"{hrs} at :{int(minute):02d}"
            elif minute == "*":
                when = "every minute" + ("" if hour == "*" else f" {hour.replace('-', '–')}h")
            else:
                step = minute.split("/")[1] if minute.startswith("*/") else None
                when = (f"every {step} min" if step else f"at :{minute}") + ("" if hour == "*" else f" {hour.replace('-', '–')}h")
            return f"{when}" if days == "daily" else f"{days} {when}"
    except Exception:  # noqa: BLE001 — a schedule string is never worth an error on SYS
        pass
    return str(trigger)


@app.get("/api/scheduler/status")
async def get_scheduler_status() -> dict[str, Any]:
    jobs_info: list[dict[str, Any]] = []
    latency_stats = _latency.stats()

    if scheduler:
        for job in scheduler.get_jobs():
            nrt = job.next_run_time
            nrt_ist = nrt.astimezone(IST).isoformat() if nrt else None
            nrt_unix = int(nrt.timestamp()) if nrt else None
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run_ist": nrt_ist,
                "next_run_unix": nrt_unix,
                **job_last_run(job.id, latency_stats),
                # additive (6 Nov, O-OPS): the schedule in words (m111), the run in flight (m113), and the one-off that
                # will re-run this job after downtime, only when one is actually scheduled (M30)
                "schedule_ist": describe_trigger(getattr(job, "trigger", None)),
                "running_since": _RUNNING.get(job.id),
                "catchup_at": _CATCHUP_PLAN.get(job.id),
            })

    broker_ms = await _probe_broker_latency()
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    return {
        "scheduler_running": scheduler.running if scheduler else False,
        "autopilot": _autopilot.to_dict(),
        "jobs": jobs_info,
        "broker_latency_ms": broker_ms,
        "system": {
            "cpu_pct": round(cpu, 1),
            "mem_pct": round(mem.percent, 1),
            "mem_used_gb": round(mem.used / 1e9, 2),
            "mem_total_gb": round(mem.total / 1e9, 2),
        },
        "ist_now": datetime.now(IST).isoformat(),
    }


# ── Autopilot toggle ──────────────────────────────────────────────────────────
class AutopilotRequest(BaseModel):
    enabled: bool


@app.get("/api/scheduler/autopilot")
async def get_autopilot() -> dict[str, Any]:
    return _autopilot.to_dict()


@app.post("/api/scheduler/autopilot")
async def set_autopilot(req: AutopilotRequest) -> dict[str, Any]:
    _autopilot.set(req.enabled)
    label = "ACTIVATED" if req.enabled else "SUSPENDED"
    _log.info("autopilot", f"AUTOPILOT {label} by user request")
    await _alerts.info(
        f"Autopilot {label}",
        f"Scheduler {'running' if req.enabled else 'paused'} since {datetime.now(IST).strftime('%H:%M IST')}",
    )
    return _autopilot.to_dict()


# ── Log REST endpoint ─────────────────────────────────────────────────────────
@app.post("/api/scheduler/icici-refresh")
async def run_icici_refresh(
    force: bool = Query(False, description="--force: log in even if today's token still works (ends the current ICICI "
                                           "session; refused 09:00–15:30 on trading days)"),
) -> dict[str, Any]:
    """Run the ICICI session refresh now (same safety rules as the scheduled job: one login at a time, never a retry of
    a rejection). `?force=1` (the BRKR auto-login panel's force button, PLAN §g) passes --force to the refresh script."""
    if _get_lock("icici_session_refresh").locked() or _login_running():
        return {"started": False, "force": force, "detail": "already running"}
    if force and (why := force_refusal(datetime.now(IST))):
        _log.warning("icici_session_refresh", f"forced login refused: {why}")
        return {"started": False, "force": True, "detail": why}
    task = asyncio.create_task(icici_session_refresh(force=force))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return {"started": True, "force": force,
            "detail": "running — watch the System page log" + (" (forced: a fresh TOTP login, today's session ends)" if force else "")}


@app.get("/api/scheduler/logs")
async def get_logs(limit: int = 100) -> list[str]:
    return _log.tail(min(limit, 500))


# ── SSE log stream ────────────────────────────────────────────────────────────
@app.get("/api/scheduler/logs/stream")
async def stream_logs(request: Request) -> StreamingResponse:
    q = _log.subscribe()

    async def event_generator() -> AsyncIterator[str]:
        try:
            for line in _log.tail(50):
                yield f"data: {line}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _log.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Latency metrics ───────────────────────────────────────────────────────────
@app.get("/api/scheduler/metrics")
async def get_metrics() -> dict[str, Any]:
    return {
        "latency_stats": _latency.stats(),
        "ist_now": datetime.now(IST).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# M31 (5 Nov review): the one-off backfill of what an outage left missing — PM-run, never scheduled
# ══════════════════════════════════════════════════════════════════════════════
# The controller's log records it down 31 Oct 11:29 → 4 Nov 21:29 and 28 Oct 12:46 → 30 Oct 08:11 (also 24 Oct 16:36 →
# 25 Oct 10:59, a weekend, and 5 Nov 19:34 → 19:55): no ALRT notes on 29 Oct or 2–4 Nov, no wraps for 16 / 21 / 28 / 29 Oct
# and 2 / 3 Nov, no FII/DII rows for 28 Oct and 2 / 3 Nov (the review's evidence). The command
#
#   python scripts/master_controller.py backfill-outage [--since 2026-10-28] [--until 2026-11-04] [--execute]
#
# prints the plan (default: a dry run that writes nothing) and, with --execute, runs it outside the freeze windows:
#   wraps    D-DATA's generator: daily_wrap.py --backfill-missing --since <since> --until <until> (stored sessions; a wrap
#            whose required sections are not stored is skipped, never half-written — D-DATA M10's one-date rule)
#   fii_dii  D-DATA's job: data-service POST /jobs/fii-dii-backfill {"since"} (+ "csv_text" of an owner-saved NSE CSV with
#            --fii-dii-csv): NSE serves only the latest day, so a missed session stays missing unless the owner saved it
#   notes    the ALRT inbox (data/notifications.jsonl): per missed CLOSING note, one line built from the stored NSE index
#            closes (index_ohlc_daily), marked backfilled and dated; per missed PRE-MARKET note, one "no pre-market note
#            is recorded" line — GIFT NIFTY and the overnight cues are not stored point-in-time, so it cannot be rebuilt.
# Honesty rule (6 Nov checker): a line states only what the code checked — the inbox holds no note of that kind for
# that session. It names a controller outage ONLY when the controller's own log records one over that slot (its
# "Down from <a> to <b> IST." downtime report lines, CONTROLLER_LOG); otherwise it names no cause (the current log
# begins with the 25 Oct 10:59 start, so no earlier session gets one, and it records no outage over the 30 Oct 08:50 slot).
OUTAGE_STEPS = ("wraps", "fii_dii", "notes")
# the review's evidence window (M31: the 28 Oct close, 29 Oct, 2–4 Nov); D-DATA's wraps backfill skips complete wraps,
# so the 16 / 21 Oct wraps are a separate `--steps wraps --since 2026-10-12` run (RUNBOOK)
OUTAGE_SINCE_DEFAULT = "2026-10-28"
FII_DII_BACKFILL_PATH = "/jobs/fii-dii-backfill"
NOTE_SLOTS = {"morning": time(8, 50), "close": time(15, 40)}
CONTROLLER_LOG = _ROOT / ".logs" / "master-controller.log"     # read-only here; rotated copies are .log.1, .log.2, …
_DOWN_LINE = re.compile(r"Down from (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) to (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) IST\.")


def controller_downtimes(lines: Iterable[str]) -> list[tuple[datetime, datetime]]:
    """[(down from, back at)] (IST) from the controller's own downtime reports in its log — the 'Stack was down' body
    _startup_catchup_run logs ("Down from 2026-10-31 11:29 to 2026-11-04 21:29 IST."), sorted, duplicates dropped. Pure."""
    out: set[tuple[datetime, datetime]] = set()
    for ln in lines:
        m = _DOWN_LINE.search(ln)
        if not m:
            continue
        try:
            a, b = (IST.localize(datetime.strptime(x, "%Y-%m-%d %H:%M")) for x in m.groups())  # noqa: DTZ007 — pytz
        except ValueError:
            continue
        if b > a:
            out.add((a, b))
    return sorted(out)


def downtime_over(downs: Sequence[tuple[datetime, datetime]], when: datetime) -> tuple[datetime, datetime] | None:
    """The recorded downtime that covers `when` (from ≤ when < back), else None. Pure."""
    return next(((a, b) for a, b in downs if a <= when < b), None)


def _read_controller_downtimes() -> list[tuple[datetime, datetime]]:
    """The downtimes the controller's log (and its rotated copies) records; [] when there is no log. Read-only."""
    lines: list[str] = []
    for path in sorted(CONTROLLER_LOG.parent.glob(CONTROLLER_LOG.name + "*")):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                lines += [ln for ln in fh if "Down from " in ln]
        except OSError:
            continue
    return controller_downtimes(lines)


def outage_sessions(rows: Any, since: str, until: str) -> list[str]:
    """The NSE sessions in [since, until]: the dates with a stored NIFTY 50 close (data-service /db/index-ohlc rows). Pure."""
    days = {str(r.get("date"))[:10] for r in (rows or []) if isinstance(r, dict) and r.get("close") is not None}
    return sorted(d for d in days if since <= d <= until)


def notes_present(lines: Sequence[str]) -> set[tuple[str, str]]:
    """{(session, 'morning' | 'close')} already in the inbox (any line of that kind dated that day, backfilled or not)."""
    out: set[tuple[str, str]] = set()
    for ln in lines:
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        kind = rec.get("kind")
        slot = rec.get("for_slot") or kind
        if slot in NOTE_SLOTS:
            out.add((str(rec.get("for_session") or rec.get("at") or "")[:10], str(slot)))
    return out


def missing_note_slots(lines: Sequence[str], sessions: Sequence[str]) -> list[tuple[str, str]]:
    """[(session, slot)] the inbox lacks, oldest first. Pure."""
    have = notes_present(lines)
    return [(d, slot) for d in sessions for slot in NOTE_SLOTS if (d, slot) not in have]


def _close_change(rows: Any, day: str) -> tuple[float, float | None] | None:
    pts = sorted((str(r.get("date"))[:10], float(r["close"])) for r in (rows or [])
                 if isinstance(r, dict) and r.get("close") is not None)
    for i, (d, c) in enumerate(pts):
        if d == day:
            return c, ((c / pts[i - 1][1] - 1) * 100 if i > 0 and pts[i - 1][1] else None)
    return None


def backfilled_note(day: str, slot: str, n50: Any, bank: Any, written_at: datetime,
                    downs: Sequence[tuple[datetime, datetime]] = ()) -> dict[str, Any]:
    """One inbox record for a missed note (pure). Close: NIFTY 50 / NIFTY BANK closes and day changes from the stored NSE
    daily index file — arithmetic, dated, sourced, no adjective. Morning: a "no pre-market note is recorded" line (kind
    'gap': the pre-open inputs were never stored, so nothing is reconstructed).

    Each line states only what was checked: the inbox holds no note of that kind for that session. A cause is named only
    when `downs` (the controller's own downtime records, controller_downtimes) covers the slot; never otherwise."""
    d = date.fromisoformat(day)
    slot_at = IST.localize(datetime.combine(d, NOTE_SLOTS[slot]))
    at = slot_at.isoformat(timespec="seconds")
    w = written_at.astimezone(IST)
    common = {"at": at, "for_session": day, "for_slot": slot, "backfilled": True,
              "written_at": w.isoformat(timespec="seconds")}
    down = downtime_over(downs, slot_at)
    log_note = (f"The controller's log records it down from {down[0]:%d %b %H:%M} to {down[1]:%d %b %H:%M} IST. "
                if down else "")
    if down:
        common["controller_down"] = {"from": down[0].isoformat(timespec="minutes"), "to": down[1].isoformat(timespec="minutes"),
                                     "source": "controller log"}
    if slot == "morning":
        return {**common, "kind": "gap", "title": f"No pre-market note · {d:%a %d %b}",
                "body": (f"No pre-market note is recorded for this session (inbox checked {w:%d %b %H:%M}). {log_note}"
                         "GIFT NIFTY and the overnight cues are not stored point-in-time, so it cannot be rebuilt; the "
                         "previous session's wrap is the record.")[:400]}
    parts = []
    for label, rows in (("NIFTY 50", n50), ("NIFTY BANK", bank)):
        cc = _close_change(rows, day)
        if cc is not None:
            parts.append(f"{label} {cc[0]:,.2f}" + (f" ({cc[1]:+.2f} %)" if cc[1] is not None else ""))
    body = (" · ".join(parts) or "index closes not stored for this session") + (
        " · source NSE daily index file (stored) · no closing note is recorded for this session; backfilled from stored "
        f"data on {w:%d %b %H:%M}" + (f" · {log_note.strip()}" if log_note else ""))
    return {**common, "kind": "close", "title": f"Closing note · {d:%a %d %b} (backfilled)", "body": body[:400],
            "source": "index_ohlc_daily"}


def merge_notifications(lines: Sequence[str], records: Sequence[dict[str, Any]]) -> list[str]:
    """The inbox with `records` added in time order (a stable sort on `at`, so same-time lines keep their order); a record
    whose (for_session, for_slot) is already present is not added twice. Unparsable lines keep their place. Pure."""
    have = notes_present(lines)
    keyed: list[tuple[str, int, str]] = []
    for i, ln in enumerate(lines):
        try:
            at = str((json.loads(ln) or {}).get("at") or "")
        except (ValueError, AttributeError):
            at = ""
        keyed.append((at, i, ln))
    n = len(keyed)
    for j, rec in enumerate(records):
        if (rec.get("for_session"), rec.get("for_slot")) in have:
            continue
        keyed.append((str(rec["at"]), n + j, json.dumps(rec, ensure_ascii=True)))
    last = ""
    out: list[tuple[str, int, str]] = []
    for at, i, ln in keyed:                       # unparsable lines inherit the previous time: they stay where they were
        last = at or last
        out.append((last, i, ln))
    return [ln for _, _, ln in sorted(out, key=lambda t: (t[0], t[1]))]


def plan_outage_backfill(since: str, until: str, steps: Sequence[str], fii_csv: str | None) -> list[dict[str, Any]]:
    """The commands / requests the backfill would run, in order (pure: printed by the dry run, run by --execute)."""
    plan: list[dict[str, Any]] = []
    if "wraps" in steps:
        # D-DATA's CLI takes --until too (daily_wrap.py: last session, default yesterday): the command's range is passed
        wrap_cmd = [PYTHON_BIN, str(_ROOT / "scripts" / "daily_wrap.py"), "--backfill-missing", "--since", since,
                    "--until", until, "--base", UI_API]
        plan.append({"step": "wraps", "kind": "subprocess", "cmd": wrap_cmd, "dry_run_cmd": [*wrap_cmd, "--dry-run"],
                     "writes": "reports/daily_wrap/<session>.md for stored sessions whose wrap is missing or incomplete"})
    if "fii_dii" in steps:
        body: dict[str, Any] = {"since": since}
        if fii_csv:
            body["csv_path"] = fii_csv           # read at --execute into csv_text (the file stays on this Mac)
        plan.append({"step": "fii_dii", "kind": "data_job", "path": FII_DII_BACKFILL_PATH, "body": body,
                     "writes": "nse_fii_dii_cash rows for gaps a source exists for; the rest is listed as still missing"})
    if "notes" in steps:
        plan.append({"step": "notes", "kind": "inbox", "path": str(_NOTIFY_LOG), "since": since, "until": until,
                     "writes": "data/notifications.jsonl: one backfilled close line / one 'no pre-market note is recorded' "
                               "line per missed note slot of a stored session, dated, in time order; a controller outage "
                               "is named only where the controller's log records one over that slot"})
    return plan


def _get_json_sync(url: str, **params: Any) -> Any:
    try:
        r = httpx.get(url, params=params or None, timeout=30)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def _index_rows(symbol: str, since: str) -> list[dict[str, Any]]:
    days = max(30, (datetime.now(IST).date() - date.fromisoformat(since)).days + 15)
    res = _get_json_sync(f"{DATA_SVC}/db/index-ohlc/{symbol}", days=days)
    return (res or {}).get("rows") or []


def _read_user_file(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _write_inbox_atomically(path: Path, records: Sequence[dict[str, Any]]) -> int:
    """Merge `records` into the inbox and replace it atomically; a line the controller appended meanwhile is re-merged
    (read → merge → re-read; replaced only when the file did not change between the last read and the write)."""
    for _ in range(5):
        before = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        merged = merge_notifications(before, records)
        tmp = path.with_name(f"{path.name}.backfill-{os.getpid()}")
        tmp.write_text("\n".join(merged) + "\n", encoding="utf-8")
        now_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if now_lines == before:
            os.replace(tmp, path)
            return len(merged) - len(before)
        tmp.unlink(missing_ok=True)
    raise RuntimeError("the inbox kept changing while merging: run the notes step again when no job is writing")


async def _run_backfill_step(step: dict[str, Any], since: str, until: str) -> str:
    if step["kind"] == "subprocess":
        res = await asyncio.to_thread(subprocess.run, step["cmd"], capture_output=True, text=True, timeout=1800,
                                      cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)})
        last = (res.stdout.strip().splitlines() or [""])[-1]
        return f"exit {res.returncode}: {last[:600] or _stderr_reason(res.stderr)}"
    if step["kind"] == "data_job":
        body = dict(step["body"])
        csv_path = body.pop("csv_path", None)
        if csv_path:
            body["csv_text"] = await asyncio.to_thread(_read_user_file, csv_path)
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{DATA_SVC}{step['path']}", json=body)
        if r.status_code == 404:
            return f"{step['path']} not served by data-service (D-DATA's route not mounted yet): nothing done"
        if r.status_code != 200:
            return f"HTTP {r.status_code}: {r.text[:300]}"
        started = r.json()
        if isinstance(started, dict) and started.get("job_id"):     # a data-service job: poll it (never POST it twice)
            outcome: Any = None
            async with httpx.AsyncClient(timeout=60) as client:
                for i in range(240):
                    await asyncio.sleep(data_job_poll_delay(i))
                    info = (await client.get(f"{DATA_SVC}/jobs/{started['job_id']}")).json()
                    if info.get("status") in ("done", "error"):
                        outcome = info.get("result") if info.get("status") == "done" else {"error": info.get("error")}
                        break
            return (json.dumps(outcome)[:600] if outcome is not None
                    else f"job {started['job_id']} still running (not waited for)")
        return json.dumps(started)[:600]
    n50, bank = await asyncio.to_thread(_index_rows, "NIFTY 50", since), await asyncio.to_thread(_index_rows, "NIFTY BANK", since)
    sessions = outage_sessions(n50, since, until)
    lines = (await asyncio.to_thread(_NOTIFY_LOG.read_text, encoding="utf-8")).splitlines() if _NOTIFY_LOG.exists() else []
    now = datetime.now(IST)
    downs = await asyncio.to_thread(_read_controller_downtimes)       # the controller's own records; never inferred
    records = [backfilled_note(d, slot, n50, bank, now, downs) for d, slot in missing_note_slots(lines, sessions)]
    added = await asyncio.to_thread(_write_inbox_atomically, _NOTIFY_LOG, records) if records else 0
    named = sum(1 for r in records if r.get("controller_down"))
    return (f"{len(sessions)} session(s), {len(records)} missed note slot(s) ({named} inside a downtime the controller's "
            f"log records), {added} line(s) added")


def backfill_outage_main(argv: Sequence[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="master_controller.py backfill-outage",
                                 description="One-off backfill of the artefacts an outage left missing (M31). Dry run by default.")
    ap.add_argument("--since", default=OUTAGE_SINCE_DEFAULT)
    ap.add_argument("--until", default=(datetime.now(IST).date() - timedelta(days=1)).isoformat())
    ap.add_argument("--steps", default=",".join(OUTAGE_STEPS), help="comma list of: " + ", ".join(OUTAGE_STEPS))
    ap.add_argument("--fii-dii-csv", default=None, help="an owner-saved NSE FII/DII CSV for sessions the API no longer serves")
    ap.add_argument("--execute", action="store_true", help="run the plan (default: print it and write nothing)")
    ap.add_argument("--allow-window", action="store_true", help="run inside a 07:45–09:20 / 18:30–21:15 freeze window anyway")
    # run from a shell, not by start-local.sh: the Docker-era defaults (http://ui-api:8000, `python`) would be wrong here
    ap.add_argument("--ui-api", default=os.environ.get("UI_API_URL") or "http://127.0.0.1:8010")
    ap.add_argument("--data-service", default=os.environ.get("DATA_SERVICE_URL") or "http://127.0.0.1:8001")
    args = ap.parse_args(list(argv))
    global UI_API, DATA_SVC, PYTHON_BIN
    UI_API, DATA_SVC = args.ui_api.rstrip("/"), args.data_service.rstrip("/")
    if not os.environ.get("PYTHON_BIN"):
        PYTHON_BIN = sys.executable                # the interpreter running this command (the canonical env)
    steps = [x.strip() for x in args.steps.split(",") if x.strip()]
    bad = [x for x in steps if x not in OUTAGE_STEPS]
    if bad:
        ap.error(f"unknown step(s) {bad}; known: {list(OUTAGE_STEPS)}")
    for v in (args.since, args.until):
        date.fromisoformat(v)                    # a bad date fails here, before anything is planned
    plan = plan_outage_backfill(args.since, args.until, steps, args.fii_dii_csv)
    if not args.execute:
        print(json.dumps({"dry_run": True, "since": args.since, "until": args.until, "plan": plan}, indent=1, default=str))
        print("Nothing written. Re-run with --execute (outside the freeze windows) to run it; for the wraps first run "
              "its own dry_run_cmd above to see which sessions it would write.")
        return 0
    if in_freeze_window(datetime.now(IST)) and not args.allow_window:
        print("refused: inside a restart-freeze window (07:45–09:20 / 18:30–21:15 IST); run it after the window", file=sys.stderr)
        return 3
    rc = 0
    for step in plan:
        try:
            out = asyncio.run(_run_backfill_step(step, args.since, args.until))
            print(f"{step['step']}: {out}")
            rc |= 1 if out.startswith(("exit 1", "exit 2", "HTTP ")) else 0
        except Exception as exc:  # noqa: BLE001 — the next step still runs
            print(f"{step['step']}: FAILED {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
            rc = 1
    return rc


# ══════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Guard before uvicorn: `--help` used to fall through and silently start a SECOND
    # controller on :8008 (Bloomberg F5.5). Any argument now prints usage and exits.
    if len(sys.argv) > 1 and sys.argv[1] == "backfill-outage":       # M31: a one-off PM command, never the server
        sys.exit(backfill_outage_main(sys.argv[2:]))
    if len(sys.argv) > 1:
        print(
            "master_controller — IST scheduler + Telegram bot + telemetry on :8008.\n"
            "Takes no arguments. Start:  python scripts/master_controller.py\n"
            "(launchd/ops run it the same way; config comes from .env, not flags)\n"
            "One-off: python scripts/master_controller.py backfill-outage --help (M31; dry run by default)"
        )
        sys.exit(0 if sys.argv[1] in ("-h", "--help") else 2)
    import uvicorn
    uvicorn.run(
        "master_controller:app",
        host="0.0.0.0",
        port=8008,
        log_level="info",
        loop="asyncio",
    )
