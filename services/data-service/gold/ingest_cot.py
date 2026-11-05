"""CFTC Commitments of Traders for COMEX gold (SOURCES.md B1–B4, B10): the four Socrata datasets → ``gold_cot_raw``
(the latest payload per (dataset, id) — INSERT OR REPLACE on the §c.1 key, so a republished week REPLACES the stored
payload rather than keeping both vintages) and ``gold_cot`` (typed wide rows), plus the release calendar rows in
``gold_events``. ``release_at`` is the CFTC calendar from ``pit.cot_release_date`` (Friday 15:30 ET, the Monday after a
federal holiday, the verified catch-up dates of the 2018-19 / 2025 lapses and the 2023 ION incident); the four
unverifiable Oct-2013 weeks are stamped late with ``release_source = 'unverified'``.

Parsing traps handled (G-COT): every value is a JSON string; ``report_date_as_yyyy_mm_dd`` is an ISO timestamp;
``cftc_commodity_code`` carries a trailing space (we filter on ``cftc_contract_market_code``); CFTC typos are
spelled exactly (``noncomm_postions_spread_all``, ``change_in_noncomm_spead_all``, ``swap__positions_short_all``,
``tot_rept_positions_short``); the API default ``$limit`` is 1,000 (we always set 50,000); non-Tuesday as-of
dates exist (holidays) so rows key on the date itself; a republished week overwrites its raw payload (no vintage diff).
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from gold import db, pit
from gold.db import utcnow
from shared.logging import get_logger

logger = get_logger(__name__)

DATASETS: dict[str, tuple[str, str, str]] = {   # key → (socrata id, report, fut_or_combined)
    "disagg_f": ("72hh-3qpy", "disagg", "F"),
    "disagg_c": ("kh3c-gbw2", "disagg", "C"),
    "legacy_f": ("6dca-aqww", "legacy", "F"),
    "legacy_c": ("jun7-fc8e", "legacy", "C"),
}
GOLD_CODES: tuple[str, ...] = ("088691", "088695", "088LM1")     # COMEX gold, micro gold, Coinbase 1-oz
API_BASE = "https://publicreporting.cftc.gov/resource/{dataset}.json"
VIEWABLE_URL = "https://www.cftc.gov/dea/futures/deacmxsf.htm"
PAGE_LIMIT = 50_000

# typed column ← candidate source fields (first present wins); disaggregated and legacy differ
_DISAGG_MAP: dict[str, tuple[str, ...]] = {
    "open_interest": ("open_interest_all",), "oi_chg": ("change_in_open_interest_all",),
    "pm_long": ("prod_merc_positions_long",), "pm_short": ("prod_merc_positions_short",),
    "sd_long": ("swap_positions_long_all",), "sd_short": ("swap__positions_short_all",), "sd_spread": ("swap__positions_spread_all",),
    "mm_long": ("m_money_positions_long_all",), "mm_short": ("m_money_positions_short_all",), "mm_spread": ("m_money_positions_spread",),
    "or_long": ("other_rept_positions_long",), "or_short": ("other_rept_positions_short",), "or_spread": ("other_rept_positions_spread",),
    "nr_long": ("nonrept_positions_long_all",), "nr_short": ("nonrept_positions_short_all",),
    "chg_pm_long": ("change_in_prod_merc_long",), "chg_pm_short": ("change_in_prod_merc_short",),
    "chg_sd_long": ("change_in_swap_long_all",), "chg_sd_short": ("change_in_swap_short_all",), "chg_sd_spread": ("change_in_swap_spread_all",),
    "chg_mm_long": ("change_in_m_money_long_all",), "chg_mm_short": ("change_in_m_money_short_all",), "chg_mm_spread": ("change_in_m_money_spread",),
    "chg_or_long": ("change_in_other_rept_long",), "chg_or_short": ("change_in_other_rept_short",), "chg_or_spread": ("change_in_other_rept_spread",),
    "chg_nr_long": ("change_in_nonrept_long_all",), "chg_nr_short": ("change_in_nonrept_short_all",),
    "traders_total": ("traders_tot_all",), "traders_mm_long": ("traders_m_money_long_all",), "traders_mm_short": ("traders_m_money_short_all",),
    "traders_mm_spread": ("traders_m_money_spread_all",), "traders_sd_long": ("traders_swap_long_all",), "traders_sd_short": ("traders_swap_short_all",),
    "traders_pm_long": ("traders_prod_merc_long_all",), "traders_pm_short": ("traders_prod_merc_short_all",),
    "traders_or_long": ("traders_other_rept_long_all",), "traders_or_short": ("traders_other_rept_short",),
    "conc_gross4_long": ("conc_gross_le_4_tdr_long",), "conc_gross4_short": ("conc_gross_le_4_tdr_short",),
    "conc_gross8_long": ("conc_gross_le_8_tdr_long",), "conc_gross8_short": ("conc_gross_le_8_tdr_short",),
    "conc_net4_long": ("conc_net_le_4_tdr_long_all",), "conc_net4_short": ("conc_net_le_4_tdr_short_all",),
    "conc_net8_long": ("conc_net_le_8_tdr_long_all",), "conc_net8_short": ("conc_net_le_8_tdr_short_all",),
}
_LEGACY_MAP: dict[str, tuple[str, ...]] = {
    "open_interest": ("open_interest_all",), "oi_chg": ("change_in_open_interest_all",),
    "nc_long": ("noncomm_positions_long_all",), "nc_short": ("noncomm_positions_short_all",),
    "nc_spread": ("noncomm_postions_spread_all", "noncomm_positions_spread_all"),
    "c_long": ("comm_positions_long_all",), "c_short": ("comm_positions_short_all",),
    "nr_long": ("nonrept_positions_long_all",), "nr_short": ("nonrept_positions_short_all",),
    "chg_nc_long": ("change_in_noncomm_long_all",), "chg_nc_short": ("change_in_noncomm_short_all",),
    "chg_c_long": ("change_in_comm_long_all",), "chg_c_short": ("change_in_comm_short_all",),
    "chg_nr_long": ("change_in_nonrept_long_all",), "chg_nr_short": ("change_in_nonrept_short_all",),
    "traders_total": ("traders_tot_all",),
    "conc_gross4_long": ("conc_gross_le_4_tdr_long",), "conc_gross4_short": ("conc_gross_le_4_tdr_short",),
    "conc_gross8_long": ("conc_gross_le_8_tdr_long",), "conc_gross8_short": ("conc_gross_le_8_tdr_short",),
    "conc_net4_long": ("conc_net_le_4_tdr_long_all",), "conc_net4_short": ("conc_net_le_4_tdr_short_all",),
    "conc_net8_long": ("conc_net_le_8_tdr_long_all",), "conc_net8_short": ("conc_net_le_8_tdr_short_all",),
}
_INT_COLS = {c for c in (*_DISAGG_MAP, *_LEGACY_MAP) if not c.startswith("conc_")}


def _num(rec: dict[str, Any], names: tuple[str, ...], as_int: bool) -> float | int | None:
    for n in names:
        v = rec.get(n)
        if v in (None, "", "NaN"):
            continue
        try:
            f = float(str(v).strip())
        except ValueError:
            continue
        return round(f) if as_int else f
    return None


def _report_date(rec: dict[str, Any]) -> date:
    raw = str(rec.get("report_date_as_yyyy_mm_dd") or rec.get("report_date") or "")[:10]
    return date.fromisoformat(raw)


def parse_records(records: Iterable[dict[str, Any]], dataset: str, *, now: datetime | None = None,
                  codes: tuple[str, ...] = GOLD_CODES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(raw_rows, typed_rows) for one dataset from JSON records or csv.DictReader rows."""
    now = now or utcnow()
    _, report, foc = DATASETS[dataset]
    fmap = _DISAGG_MAP if report == "disagg" else _LEGACY_MAP
    raw_rows, typed_rows = [], []
    for rec in records:
        code = str(rec.get("cftc_contract_market_code") or "").strip()
        if code not in codes:
            continue
        rd = _report_date(rec)
        rid = str(rec.get("id") or f"{rd:%y%m%d}{code}{foc}")
        raw_rows.append({"dataset": dataset, "id": rid, "report_date": rd, "contract_code": code,
                         "market_name": rec.get("market_and_exchange_names"), "payload": json.dumps(rec, separators=(",", ":")),
                         "first_seen_at": now})
        row: dict[str, Any] = {"report_date": rd, "contract_code": code, "fut_or_combined": foc, "report": report,
                               "release_at": pit.cot_release_at(rd), "release_source": pit.cot_release_source(rd), "first_seen_at": now,
                               "source": f"cftc_socrata_{DATASETS[dataset][0]}"}
        for col, names in fmap.items():
            row[col] = _num(rec, names, as_int=col in _INT_COLS)
        typed_rows.append(row)
    return pd.DataFrame(raw_rows), pd.DataFrame(typed_rows)


def parse_json_text(text: str, dataset: str, **kw: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise TypeError("CFTC API body is not a JSON list")
    return parse_records(data, dataset, **kw)


def parse_csv_text(text: str, dataset: str, **kw: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    return parse_records(csv.DictReader(io.StringIO(text)), dataset, **kw)


def ingest(store: Any, dataset: str, raw: pd.DataFrame, typed: pd.DataFrame) -> dict[str, int]:
    """Write one dataset's rows (INSERT OR REPLACE on the natural keys). A republished week overwrites both its raw
    payload and its typed row (fresh ``first_seen_at``); the previous payload is not kept. ``release_at`` is capped at
    ``first_seen_at`` so a row can never be dated public before we held it."""
    if typed.empty:
        return {"raw": 0, "typed": 0}
    typed = typed.copy()
    typed["release_at"] = [min(r, f) for r, f in zip(typed["release_at"], typed["first_seen_at"])]
    n_raw = db.upsert(store, "gold_cot_raw", raw)
    n_typed = db.upsert(store, "gold_cot", typed)
    logger.info("gold.cot.ingested", dataset=dataset, raw=n_raw, typed=n_typed,
                last=str(typed["report_date"].max()))
    return {"raw": n_raw, "typed": n_typed}


def api_url(dataset: str, since: date | None, codes: tuple[str, ...] = GOLD_CODES) -> tuple[str, dict[str, str]]:
    sid = DATASETS[dataset][0]
    quoted = ", ".join(f"'{c}'" for c in codes)
    where = f"cftc_contract_market_code in ({quoted})"
    if since:
        where += f" AND report_date_as_yyyy_mm_dd > '{since.isoformat()}T00:00:00.000'"
    return API_BASE.format(dataset=sid), {"$where": where, "$order": "report_date_as_yyyy_mm_dd ASC", "$limit": str(PAGE_LIMIT)}


def last_report_date(store: Any, dataset: str) -> date | None:
    _, report, foc = DATASETS[dataset]
    v = db.scalar(store, "SELECT MAX(report_date) FROM gold_cot WHERE report = ? AND fut_or_combined = ? AND contract_code = '088691'",
                  [report, foc])
    return pd.Timestamp(v).date() if v is not None else None


def fetch_and_ingest(store: Any, http: Any, *, datasets: Iterable[str] = tuple(DATASETS), backfill_from: date | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    """Incremental pull (``report_date > max stored``) for each dataset; 0 rows = "not yet released"."""
    out: dict[str, Any] = {}
    headers = {}
    token = os.getenv("CFTC_APP_TOKEN", "").strip()
    if token:
        headers["X-App-Token"] = token      # never logged
    for ds in datasets:
        since = backfill_from - pd.Timedelta(days=1) if backfill_from else last_report_date(store, ds)
        if isinstance(since, pd.Timestamp):
            since = since.date()
        url, params = api_url(ds, since)
        resp = http.get(url, params=params, headers=headers, timeout_s=60)
        if resp.status_code == 429:
            out[ds] = {"status": "throttled"}
            continue
        if resp.status_code != 200:
            out[ds] = {"status": f"http_{resp.status_code}"}
            continue
        raw, typed = parse_json_text(resp.text, ds, now=now)
        res = ingest(store, ds, raw, typed)
        out[ds] = {"status": "ok" if res["typed"] else "not_yet", **res,
                   "new_report_date": str(typed["report_date"].max()) if not typed.empty else None}
    return out


def identity_check(store: Any) -> pd.DataFrame:
    """Rows where legacy commercial long ≠ producer long + swap long + swap spread (same report_date, 088691,
    futures-only). Empty = identity holds (verified on 20 Oct 2026: 59,531 = 19,715 + 17,737 + 22,079)."""
    return db.query_df(store, """
        SELECT l.report_date, l.c_long, d.pm_long + d.sd_long + d.sd_spread AS disagg_sum,
               l.c_long - (d.pm_long + d.sd_long + d.sd_spread) AS diff
        FROM gold_cot l JOIN gold_cot d
          ON l.report_date = d.report_date AND l.contract_code = d.contract_code AND l.fut_or_combined = d.fut_or_combined
        WHERE l.report = 'legacy' AND d.report = 'disagg' AND l.contract_code = '088691' AND l.fut_or_combined = 'F'
          AND l.c_long <> d.pm_long + d.sd_long + d.sd_spread
        ORDER BY l.report_date
    """)


def release_events(year: int, *, now: datetime | None = None) -> pd.DataFrame:
    """COT_RELEASE rows for gold_events: every Tuesday report's release (Friday 15:30 ET, the Monday after a federal
    holiday, or a verified catch-up date) in IST; a Monday-dated report (the Tuesday was a holiday) replaces its Tuesday."""
    now = now or utcnow()
    rows = []
    d = date(year, 1, 1)
    while d.year == year:
        monday_report = d.weekday() == 0 and d in pit.COT_RELEASE_EXCEPTIONS
        if d.weekday() == 1 and (d - timedelta(days=1)) in pit.COT_RELEASE_EXCEPTIONS:
            d += timedelta(days=1)                            # the Monday-dated report already carries this week
            continue
        if d.weekday() == 1 or monday_report:                 # Tuesday positions (or the Monday when Tuesday was a holiday)
            rel_utc = pit.cot_release_at(d)
            rel_ist = pd.Timestamp(rel_utc, tz="UTC").tz_convert("Asia/Kolkata")
            rows.append({"event_date": rel_ist.date(), "time_ist": rel_ist.strftime("%H:%M"), "kind": "COT_RELEASE",
                         "name": f"CFTC COT (positions as of {d:%a %d %b})", "detail": "Friday 15:30 ET; Monday after US holidays; verified catch-up dates",
                         "country": "US", "impact": "context", "forecast": None, "previous": None, "actual": None,
                         "in_session": False, "source": "rule+B10", "first_seen_at": now})
        d += timedelta(days=1)
    return pd.DataFrame(rows)
