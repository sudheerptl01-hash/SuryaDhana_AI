"""
NSE corporate events: what is coming up for each listed company.

Three free NSE feeds, verified live (docs/NSE_DATA_DICTIONARY.md → "Filings, results, board meetings"):
  event-calendar                 forward board meetings (results, dividends, fund raising), ~300 rows in season
  corporate-board-meetings       the latest board-meeting intimations, with the filing PDF
  corporates-corporateActions    ex-dates of dividends, bonuses, splits, rights, buybacks (date window)

Rows are normalised to one shape and upserted into `nse_events`; past events are kept, so the table
grows into a point-in-time event history (first_seen = when this system first saw the announcement).
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

import httpx
import pandas as pd

from nse_filings import API, API_HEADERS
from shared.logging import get_logger

logger = get_logger("nse-events")

# Order matters: the first match is the event's primary kind; every match goes into `tags`.
_KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("RESULTS", re.compile(r"financial result|results?\b|quarterly|audited", re.I)),
    ("BONUS", re.compile(r"\bbonus", re.I)),
    ("SPLIT", re.compile(r"split|sub-?division", re.I)),
    ("RIGHTS", re.compile(r"\brights?\b", re.I)),
    ("BUYBACK", re.compile(r"buy\s?-?back", re.I)),
    ("DIVIDEND", re.compile(r"dividend", re.I)),
    ("M&A", re.compile(r"merger|amalgamation|demerger|scheme of arrangement|acquisition", re.I)),
    ("FUND RAISE", re.compile(r"fund rais|preferential|qip|qualified institutions|debentures|ncd", re.I)),
    ("AGM", re.compile(r"\bagm\b|annual general meeting|egm|postal ballot", re.I)),
]


def classify(*texts: Optional[str]) -> tuple[str, str]:
    """(primary kind, comma-separated tags) from a purpose / subject text."""
    text = " ".join(t for t in texts if t)
    tags = [k for k, rx in _KINDS if rx.search(text)]
    return (tags[0] if tags else "OTHER"), ",".join(tags)


def _d(v: Any) -> Optional[str]:
    """NSE dates ('12-Oct-2026', '12-10-2026', '-') → ISO, or None."""
    s = str(v or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _clean(v: Any) -> Optional[str]:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    return None if s in ("", "-", "None") else s


def parse_calendar(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        d = _d(r.get("date"))
        if not d or not r.get("symbol"):
            continue
        kind, tags = classify(r.get("purpose"), r.get("bm_desc"))
        out.append({"symbol": r["symbol"].strip().upper(), "event_date": d, "kind": kind, "source": "calendar",
                    "tags": tags, "company": _clean(r.get("company")), "purpose": _clean(r.get("purpose")),
                    "detail": _clean(r.get("bm_desc")), "record_date": None, "announced_at": None, "url": None})
    return out


def parse_board(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        d = _d(r.get("bm_date"))
        if not d or not r.get("bm_symbol"):
            continue
        kind, tags = classify(r.get("bm_desc"))
        url = _clean(r.get("attachment"))
        out.append({"symbol": r["bm_symbol"].strip().upper(), "event_date": d, "kind": kind, "source": "board",
                    "tags": tags, "company": _clean(r.get("sm_name")), "purpose": _clean(r.get("bm_purpose")),
                    "detail": _clean(r.get("bm_desc")), "record_date": None,
                    "announced_at": _clean(r.get("bm_timestamp")),
                    "url": url if url and url.startswith("https://") else None})
    return out


def parse_actions(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        d = _d(r.get("exDate"))
        if not d or not r.get("symbol") or (r.get("series") or "EQ") not in ("EQ", "BE", "SM", "ST"):
            continue
        kind, tags = classify(r.get("subject"))
        out.append({"symbol": r["symbol"].strip().upper(), "event_date": d, "kind": kind, "source": "action",
                    "tags": tags, "company": _clean(r.get("comp")), "purpose": _clean(r.get("subject")),
                    "detail": _clean(r.get("subject")), "record_date": _d(r.get("recDate")),
                    "announced_at": _clean(r.get("caBroadcastDate")), "url": None})
    return out


def _get(client: httpx.Client, path: str, params: dict) -> list[dict]:
    r = client.get(f"{API}/{path}", params=params)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", []) or []


def ingest_events(store, progress: Optional[Callable[[int, int], None]] = None,
                  client: Optional[httpx.Client] = None, today: Optional[date] = None,
                  back_days: int = 7, ahead_days: int = 90, sleep_s: float = 0.8) -> dict:
    """Pull the three feeds and upsert them. A feed that fails is reported, never fatal."""
    today = today or date.today()
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=30, follow_redirects=True)
    window = {"from_date": f"{today - timedelta(days=back_days):%d-%m-%Y}",
              "to_date": f"{today + timedelta(days=ahead_days):%d-%m-%Y}"}
    feeds = [("calendar", "event-calendar", {"index": "equities"}, parse_calendar),
             ("board", "corporate-board-meetings", {"index": "equities"}, parse_board),
             ("action", "corporates-corporateActions", {"index": "equities", **window}, parse_actions)]
    out: dict[str, Any] = {"failures": []}
    rows: list[dict] = []
    try:
        for i, (name, path, params, parse) in enumerate(feeds, 1):
            try:
                parsed = parse(_get(client, path, params))
                rows += parsed
                out[name] = len(parsed)
            except Exception as exc:  # noqa: BLE001 — one feed down must not lose the others
                logger.warning("NSE events feed failed", feed=name, error=str(exc)[:200])
                out["failures"].append({"feed": name, "error": str(exc)[:200]})
            if progress:
                progress(i, len(feeds))
            time.sleep(sleep_s)
    finally:
        if own:
            client.close()
    if rows:
        df = pd.DataFrame(rows).drop_duplicates(["symbol", "event_date", "kind", "source"], keep="last")
        out["upserted"] = store.upsert_nse_events(df)
    else:
        out["upserted"] = 0
    return out
