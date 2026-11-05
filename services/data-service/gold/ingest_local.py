"""Local inputs (SOURCES.md H1, H2) and compiled tables: the automated pre-open briefs (``gold_premarket/YYYYMMDD.json``,
schema-validated, sha256-deduped), the fair-open accuracy log (migrated from ``data/gold_preopen/log.json`` and
dual-written by ui-api through ``POST /jobs/gold-log``), the daily health snapshot (read from ui-api) and the gold
calendar (COT releases, COMEX FND/LTD, MCX expiries and holidays, Indian demand dates, the Budget).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db
from gold.db import utcnow
from gold.ingest_india import family_expiry, previous_mcx_session
from shared import mcx_specs as specs
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[3]
BRIEF_DIR = Path(os.getenv("GOLD_BRIEF_DIR", str(ROOT / "gold_premarket")))
PREOPEN_LOG_PATH = Path(os.getenv("GOLD_PREOPEN_LOG", str(ROOT / "data" / "gold_preopen" / "log.json")))
UI_API_URL = os.getenv("UI_API_URL", "http://127.0.0.1:8010")
BRIEF_REQUIRED = ("meta", "baseline", "gap_model", "synthesis", "data_quality")

# F19 Indian demand calendar (secondary sources, SOURCES.md) and the Budget; Muhurat per circular MCX/TRD/590/2026.
INDIA_EVENTS: tuple[tuple[date, str, str, str, str | None], ...] = (
    (date(2026, 4, 19), "FESTIVAL", "Akshaya Tritiya", "traditional gold-buying day (Sunday)", None),
    (date(2026, 11, 6), "FESTIVAL", "Dhanteras", "peak retail gold demand day", None),
    (date(2026, 11, 8), "MCX_SPECIAL", "Muhurat trading (Diwali Laxmi Pujan)", "circular MCX/TRD/590/2026: special 14:05–14:19, trading 14:20–15:30",
     "14:20"),
    (date(2027, 2, 1), "BUDGET", "Union Budget", "customs duty on gold can change (F9)", "11:00"),
)


# ── H1 briefs ───────────────────────────────────────────────────────────────────────────────────────

def validate_brief(doc: dict[str, Any]) -> list[str]:
    """Shape check against the schema's required top-level keys (the full JSON-schema file is 14 keys; we require the
    five the table reads)."""
    missing = [k for k in BRIEF_REQUIRED if k not in doc]
    if "meta" in doc and not isinstance(doc["meta"], dict):
        missing.append("meta:object")
    if "meta" in doc and isinstance(doc["meta"], dict) and not doc["meta"].get("report_date"):
        missing.append("meta.report_date")
    return missing


def parse_brief(text: str, *, now: datetime | None = None) -> pd.DataFrame:
    now = now or utcnow()
    doc = json.loads(text)
    problems = validate_brief(doc)
    if problems:
        raise ValueError("brief fails the schema check: " + ", ".join(problems))
    meta, syn, gap = doc["meta"], doc.get("synthesis") or {}, doc.get("gap_model") or {}
    rd = db.to_date(meta.get("report_date"))
    gen = meta.get("generated_at")
    gen_dt = pd.Timestamp(gen).tz_convert("UTC").tz_localize(None).to_pydatetime() if gen and "+" in str(gen) else db.to_date(gen)
    return pd.DataFrame([{"report_date": rd, "generated_at": gen_dt, "schema_version": meta.get("schema_version"),
                          "bias": syn.get("bias"), "bias_score": _num(syn.get("bias_score")), "confidence": _num(syn.get("confidence")),
                          "model_fair_open": _num(gap.get("model_fair_open_inr")), "open_signal": gap.get("open_signal"),
                          "doc": json.dumps(doc, separators=(",", ":")), "file_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                          "first_seen_at": now}])


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def ingest_briefs(store: Any, folder: Path | str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Every ``YYYYMMDD.json`` in the folder whose sha256 is not stored yet; a bad file is reported, never fatal."""
    folder = Path(folder or BRIEF_DIR)
    have = set(db.query_df(store, "SELECT file_sha256 FROM gold_brief_docs")["file_sha256"].tolist()) if folder.exists() else set()
    inserted, skipped, errors = 0, 0, []
    if not folder.exists():
        return {"inserted": 0, "skipped": 0, "errors": [f"missing folder {folder}"]}
    for p in sorted(folder.glob("*.json")):
        if not re.match(r"^\d{8}\.json$", p.name):
            continue
        text = p.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() in have:
            skipped += 1
            continue
        try:
            inserted += db.upsert(store, "gold_brief_docs", parse_brief(text, now=now))
        except Exception as exc:  # noqa: BLE001 — one malformed brief never stops the rest
            errors.append({"file": p.name, "error": str(exc)[:160]})
    return {"inserted": inserted, "skipped": skipped, "errors": errors}


# ── H2 pre-open accuracy log ────────────────────────────────────────────────────────────────────────

def stale_baseline_rule(row: dict[str, Any]) -> bool:
    """True when the inputs look stale: the baseline's session is not the previous MCX session of the day, or the
    overnight rupee reference never moved (``inr_now == inr_ref`` — no fresh INR bar, SOURCES.md H2)."""
    day = db.to_date(row.get("day") or row.get("date"))
    src = str(row.get("baseline_source") or "")
    m = re.search(r"settlement (\d{1,2} [A-Za-z]{3})", src)
    if day and m:
        try:
            sess = db.strptime(f"{m.group(1)} {day.year}", "%d %b %Y").date()
            if sess > day:
                sess = sess.replace(year=day.year - 1)
            if sess != previous_mcx_session(day):
                return True
        except ValueError:
            pass
    inr_now, inr_ref = row.get("inr_now"), row.get("inr_ref")
    return inr_now is not None and inr_ref is not None and float(inr_now) == float(inr_ref)


def _ts(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    t = pd.Timestamp(v)
    return (t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t).to_pydatetime()


def preopen_log_row(payload: dict[str, Any], *, now: datetime | None = None) -> pd.DataFrame:
    """One gold_preopen_log row from today's snapshot/capture payload (the log.json record shape)."""
    now = now or utcnow()
    day = db.to_date(payload.get("day") or payload.get("date"))
    if day is None:
        raise ValueError("preopen log row needs a day")
    contract = str(payload.get("contract") or "")
    expiry = db.to_date(payload.get("expiry"))
    m = re.search(r"settlement (\d{1,2} [A-Za-z]{3})", str(payload.get("baseline_source") or ""))
    bsess = None
    if m:
        try:
            bsess = db.strptime(f"{m.group(1)} {day.year}", "%d %b %Y").date()
        except ValueError:
            bsess = None
    inputs = payload.get("inputs_json") or payload.get("inputs")
    stale = payload.get("stale_baseline")
    row = {"day": day, "snapshot_at": _ts(payload.get("snapshot_at")), "contract": contract or None, "expiry": expiry,
           "baseline": _num(payload.get("baseline")), "baseline_source": payload.get("baseline_source"), "baseline_session": bsess,
           "comex_symbol": payload.get("comex_symbol"), "comex_ref": _num(payload.get("comex_ref")), "comex_now": _num(payload.get("comex_now")),
           "inr_ref": _num(payload.get("inr_ref")), "inr_now": _num(payload.get("inr_now")), "fair_open": _num(payload.get("fair_open")),
           "threshold": _num(payload.get("threshold")), "event_risk": int(payload["event_risk"]) if payload.get("event_risk") is not None else None,
           "actual_open": _num(payload.get("actual_open")), "actual_source": payload.get("actual_source"),
           "captured_at": _ts(payload.get("captured_at")), "error": _num(payload.get("error")), "naive_error": _num(payload.get("naive_error")),
           "stale_baseline": bool(stale) if stale is not None else stale_baseline_rule({**payload, "day": day}),
           "inputs_json": json.dumps(inputs, separators=(",", ":")) if isinstance(inputs, (dict, list)) else inputs}
    return pd.DataFrame([row])


def upsert_preopen_log(store: Any, payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Merge-write: fields missing from ``payload`` keep the stored value (the 09:10 capture adds the open to the 08:45 row)."""
    day = db.to_date(payload.get("day") or payload.get("date"))
    existing = db.query_df(store, "SELECT * FROM gold_preopen_log WHERE day = ?", [day]) if day else pd.DataFrame()
    merged = dict(payload)
    if not existing.empty:
        old = db.records(existing)[0]
        for k, v in old.items():
            if merged.get(k) is None and v is not None and k not in ("stale_baseline",):
                merged[k] = v
        merged.setdefault("day", day)
    df = preopen_log_row(merged, now=now)
    return {"inserted": db.upsert(store, "gold_preopen_log", df), "day": str(day)}


def migrate_preopen_log(store: Any, path: Path | str | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """``data/gold_preopen/log.json`` ({day: record}) → gold_preopen_log with ``inputs_json`` NULL and the stale flag by rule."""
    p = Path(path or PREOPEN_LOG_PATH)
    if not p.exists():
        return {"inserted": 0, "missing": str(p)}
    data = json.loads(p.read_text(encoding="utf-8"))
    frames = []
    for day, rec in sorted(data.items()):
        rec = dict(rec)
        rec.setdefault("day", day)
        rec.pop("inputs_json", None)
        frames.append(preopen_log_row(rec, now=now))
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    n = db.upsert(store, "gold_preopen_log", df)
    return {"inserted": n, "days": [str(d) for d in df["day"]] if n else [],
            "stale_flagged": [str(d) for d, s in zip(df["day"], df["stale_baseline"]) if s] if n else []}


# ── health snapshot (ui-api /api/gold/health → gold_health_daily) ───────────────────────────────────

def health_row(payload: dict[str, Any], *, now: datetime | None = None, day: date | None = None) -> pd.DataFrame:
    now = now or utcnow()
    verdict = payload.get("verdict")
    line = verdict.get("line") if isinstance(verdict, dict) else (verdict if isinstance(verdict, str) else payload.get("line"))
    gauges = payload.get("gauges") if payload.get("gauges") is not None else []
    return pd.DataFrame([{"day": day or now.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST).date(), "snapshot_at": now,
                          "verdict": line, "gauges": json.dumps(gauges, separators=(",", ":"), default=str)}])


def fetch_health(store: Any, http: Any, *, now: datetime | None = None) -> dict[str, Any]:
    resp = http.get(f"{UI_API_URL}/api/gold/health", timeout_s=30)
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    df = health_row(resp.json(), now=now)
    return {"status": "ok", "inserted": db.upsert(store, "gold_health_daily", df), "day": str(df["day"].iloc[0])}


# ── the gold calendar (gold_events) ─────────────────────────────────────────────────────────────────

def _event(d: date, kind: str, name: str, detail: str | None, *, time_ist: str | None, country: str, in_session: bool | None,
           source: str, now: datetime) -> dict[str, Any]:
    return {"event_date": d, "time_ist": time_ist, "kind": kind, "name": name, "detail": detail, "country": country, "impact": "context",
            "forecast": None, "previous": None, "actual": None, "in_session": in_session, "source": source, "first_seen_at": now}


COMEX_EVENT_SYMBOLS = ("GC", "1OZ", "QO", "MGC")


def comex_contract_dates(store: Any, symbols: tuple[str, ...] = COMEX_EVENT_SYMBOLS) -> pd.DataFrame:
    """One row per (symbol, mmy) with first_intent / first_notice / last_trade / ltd_end_time / source: the latest Sunday
    CME calendar (``cme_calendar``) first, and for every month the calendar does not carry, the daily product reference
    file (``cme_prf``: FirstNoticeDt / LastTrdDt, no intent day) — so the matched month's FND exists from the first
    weekday deploy, not the first Sunday (wave 1c, C-TRADER-13 / C-DATA-8)."""
    cols = ["symbol", "mmy", "first_intent", "first_notice", "last_trade", "ltd_end_time", "source"]
    marks = ", ".join("?" for _ in symbols)
    cal = db.query_df(store, f"""
        SELECT symbol, mmy, first_intent, first_notice, last_trade, ltd_end_time, 'cme_calendar' AS source FROM gold_cme_calendar
        WHERE symbol IN ({marks}) AND as_of = (SELECT MAX(as_of) FROM gold_cme_calendar)""", list(symbols))
    prf = db.query_df(store, f"""
        SELECT symbol, mmy, NULL AS first_intent, first_notice, last_trd AS last_trade, NULL AS ltd_end_time, 'cme_prf' AS source
        FROM gold_cme_prf WHERE symbol IN ({marks}) AND biz_date = (SELECT MAX(biz_date) FROM gold_cme_prf)""", list(symbols))
    frames = [f for f in (cal, prf) if not f.empty]
    if not frames:
        return pd.DataFrame(columns=cols)
    df = pd.concat(frames, ignore_index=True)
    df["mmy"] = df["mmy"].astype(str)
    return df.drop_duplicates(["symbol", "mmy"], keep="first")[cols]        # the calendar row wins; PRF fills the gaps


def compile_events(store: Any, *, now: datetime | None = None, horizon_days: int = 400) -> pd.DataFrame:
    """Rows the page and ECO read once: COT releases (rule + exceptions), COMEX first intent / FND / LTD from the stored
    CME calendar with the daily PRF as fallback (``comex_contract_dates``), MCX expiries per family (rule), MCX holidays
    (shared/mcx_specs), Indian demand dates, the Budget."""
    from gold.ingest_cot import release_events

    now = now or utcnow()
    today = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(IST).date()
    end = today + timedelta(days=horizon_days)
    rows: list[dict[str, Any]] = []
    for yr in {today.year, end.year}:
        ev = release_events(yr, now=now)
        if not ev.empty:
            rows.extend(r for r in ev.to_dict(orient="records") if today - timedelta(days=60) <= r["event_date"] <= end)
    for r in comex_contract_dates(store).itertuples(index=False):
        label = f"{r.symbol} {str(r.mmy)[:4]}-{str(r.mmy)[4:6]}"
        for col, kind, name in (("first_intent", "COMEX_FIRST_INTENT", "first intent day"), ("first_notice", "COMEX_FND", "first notice day"),
                                ("last_trade", "COMEX_LTD", "last trading day")):
            d = db.to_date(getattr(r, col))
            if d and today - timedelta(days=30) <= d <= end:
                detail = (f"CME product calendar; LTD ends {r.ltd_end_time or '12:30 CT'}" if r.source == "cme_calendar"
                          else "CME product reference file (daily); the Sunday calendar refines the LTD end time")
                rows.append(_event(d, kind, f"COMEX {label} {name}", detail, time_ist="23:00" if kind == "COMEX_LTD" else None,
                                   country="US", in_session=None, source=r.source, now=now))
    for code in ("GOLD", "GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"):
        months = specs.CONTRACTS[code].months if code in specs.CONTRACTS else tuple(range(1, 13))
        y, m = today.year, today.month
        for _ in range(14):
            if m in months:
                d = family_expiry(code, y, m)
                if today <= d <= end:
                    rows.append(_event(d, "MCX_EXPIRY", f"MCX {code} {d:%b-%y} expiry", "rule: 5th (GOLD/GOLDM) or month end (TEN/GUINEA/PETAL)",
                                       time_ist="23:30", country="IN", in_session=True, source="rule:mcx_specs", now=now))
            m += 1
            if m > 12:
                y, m = y + 1, 1
    for d, (name, closure) in specs.MCX_HOLIDAYS_2026.items():
        if today - timedelta(days=30) <= d <= end:
            rows.append(_event(d, "MCX_HOLIDAY", f"MCX {closure} closure: {name}", "shared/mcx_specs", time_ist=None, country="IN",
                               in_session=False, source="mcx_specs", now=now))
    for d, kind, name, detail, t in INDIA_EVENTS:
        if today - timedelta(days=30) <= d <= end:
            rows.append(_event(d, kind, name, detail, time_ist=t, country="IN", in_session=None, source="F19/F6", now=now))
    df = pd.DataFrame(rows)
    return df.drop_duplicates(["event_date", "kind", "name"]) if not df.empty else df


def ingest_events(store: Any, *, now: datetime | None = None) -> dict[str, Any]:
    df = compile_events(store, now=now)
    return {"inserted": db.upsert(store, "gold_events", df), "kinds": sorted(df["kind"].unique().tolist()) if not df.empty else []}
