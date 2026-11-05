"""India sources (SOURCES.md F1, F8–F11, F13, F14, F16): the ICICI security master (MCX settlement proxy + OI per
expiry, labelled by SESSION), Zerodha's NRML margin mirror, IBJA AM/PM, the RBI weekly statistical supplement, the
RBI/FBIL reference rate, AMFI's monthly gold-ETF row, the dated customs-duty constant and the hand-typed PIB import
number (its release URL is unverified, F14).
"""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db, pit
from gold.db import utcnow
from shared import mcx_specs as specs
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SECURITY_MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
ZERODHA_URL = "https://zerodha.com/margin-calculator/Commodity/"
IBJA_URL = "https://ibjarates.com/"
RBI_WSS_URL = "https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx"
RBI_REF_URL = "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx"
AMFI_URL = "https://portal.amfiindia.com/spages/am{mon}{yyyy}repo.xls"

FAMILY_BY_SHORT: dict[str, str] = {"GOLD": "GOLD", "GOLDM": "GOLDM", "GOLDMI": "GOLDM", "GOLDTEN": "GOLDTEN", "GOLDTE": "GOLDTEN",
                                   "GOLDPETAL": "GOLDPETAL", "GOLDPE": "GOLDPETAL", "GOLDGUINEA": "GOLDGUINEA", "GOLDGU": "GOLDGUINEA"}
QUOTE_UNIT: dict[str, str] = {"GOLD": "INR/10g", "GOLDM": "INR/10g", "GOLDTEN": "INR/10g", "GOLDGUINEA": "INR/8g", "GOLDPETAL": "INR/1g"}
MONTH_END_FAMILIES = ("GOLDTEN", "GOLDGUINEA", "GOLDPETAL")
# Purity (wave 1d round 2, PM decision D1 — binding for data-service AND ui-api): COMEX and LBMA quote per FINE troy
# ounce, so the program's landed price (COMEX × USD/INR ÷ 31.1034768 × 10) is the rupee price of 10 g of FINE gold
# (1000). A contract or a dealer price of purity P compares with landed × P / 1000: MCX GOLD / GOLDM 995, GOLDTEN /
# GOLDPETAL / GOLDGUINEA 999 (the exchange's own spec, shared/mcx_specs — the guinea is NOT priced as 916: its ₹/8 g
# trades at the 999 level, 5 Nov evidence ₹1,12,211 / 8 g = ₹1,40,264 / 10 g ≈ GOLDPETAL ₹1,40,330); IBJA 999 × 0.999,
# IBJA 995 × 0.995. Purity and quotation grams are READ from shared/mcx_specs (the single source both services import);
# the literals below are only the fallback for a family the spec module does not list.
LANDED_FINENESS = 1000
_PURITY_FALLBACK: dict[str, int] = {"GOLD": 995, "GOLDM": 995, "GOLDTEN": 999, "GOLDPETAL": 999, "GOLDGUINEA": 999}
_GRAMS_FALLBACK: dict[str, float] = {"GOLD": 10.0, "GOLDM": 10.0, "GOLDTEN": 10.0, "GOLDGUINEA": 8.0, "GOLDPETAL": 1.0}


def _spec_purity(family: str) -> int:
    spec = specs.CONTRACTS.get(family)
    try:
        return int(str(spec.purity).strip()) if spec is not None else _PURITY_FALLBACK.get(family, 999)
    except ValueError:
        return _PURITY_FALLBACK.get(family, 999)


MCX_PURITY: dict[str, int] = {fam: _spec_purity(fam) for fam in _PURITY_FALLBACK}
QUOTE_GRAMS: dict[str, float] = {fam: float(specs.CONTRACTS[fam].quote_per_grams) if fam in specs.CONTRACTS else g
                                 for fam, g in _GRAMS_FALLBACK.items()}


def purity_factor(purity: int | str) -> float:
    """The share of fine gold in ``purity`` (995 → 0.995): what multiplies the FINE landed price (D1)."""
    return int(str(purity).strip()) / LANDED_FINENESS


def landed_factor(family: str) -> tuple[float, str]:
    """(factor, basis_reference) turning the FINE duty-paid landed ₹/10 g into the price of ``family``'s purity in its
    own quotation unit: GOLD / GOLDM 0.995 'landed_995'; GOLDTEN 0.999 'landed_999'; GOLDPETAL 0.999 ÷ 10 (₹/1 g);
    GOLDGUINEA 0.999 × 0.8 (₹/8 g). The basis is then ``contract ÷ (duty_paid × factor) − 1`` — the same number as the
    contract scaled to ₹/10 g divided by landed × purity / 1000 (D1)."""
    p = MCX_PURITY.get(family, _spec_purity(family))
    return purity_factor(p) * QUOTE_GRAMS.get(family, 10.0) / 10.0, f"landed_{p}"


def per_10g(value: float | None, family: str) -> float | None:
    """A ``family`` price in ₹ per 10 g (D3: a PETAL ₹/1 g × 10, a GUINEA ₹/8 g × 1.25) — never compared unscaled."""
    if value is None:
        return None
    return round(float(value) * 10.0 / QUOTE_GRAMS.get(family, 10.0), 2)


IBJA_PURITIES = ("999", "995", "916", "750", "585")

# F9: BCD + AIDC, dated steps (owner confirms the primary at CBIC, O-3). env GOLD_IMPORT_DUTY_PCT/_EFFECTIVE may add a step.
DUTY_HISTORY: tuple[tuple[date, float, str], ...] = (
    (date(2024, 7, 24), 6.0, "Budget 2024-25: BCD 5 % + AIDC 1 %"),
    (date(2026, 5, 13), 15.0, "Notification 16/2026-Customs (12 May 2026): BCD 10 % + AIDC 5 %"),
)


def _flt(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("%", "")
    if s in ("", "-", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ── F1 ICICI security master → gold_curve (MCX, proxy settlement, OI), labelled by session ──────────

def previous_mcx_session(publish_day: date) -> date:
    """The session whose settlement a master published on ``publish_day`` carries: weekends and MCX full holidays
    skipped (the Monday file after a Friday holiday carries Thursday's settlement) — the ui-api rule, duplicated so
    data-service never imports ui-api."""
    d = publish_day - timedelta(days=1)
    while d.weekday() >= 5 or (specs.holiday_on(d) or (None, None))[1] == "full":
        d -= timedelta(days=1)
    return d


def band_session(oi_session: date) -> date:
    """The session whose SETTLEMENT a master's price band is centred on (wave 1d, the 5 Nov blocker).

    A master published on day D carries the open interest at the close of S1 = ``previous_mcx_session(D)`` (the OI
    label is right) but the band is the daily price range that was IN FORCE DURING S1, i.e. ±3 % around the settlement
    of the session BEFORE S1. Verified against the last-30-minute VWAP of Breeze 1-minute bars (MCX GOLD DEC-26):
    the Mon 26 Oct file's midpoint 1,43,309 = Thu 22 Oct 1,43,308 (Fri 23 Oct was 1,42,036); Tue 27 Oct 1,42,024 =
    Fri 23 Oct; Wed 28 Oct 1,43,073 = Mon 26 Oct 1,43,069; Fri 30 Oct 1,43,705 = Wed 28 Oct 1,43,693; Wed 04 Nov
    1,40,186 = Mon 02 Nov 1,40,190; Thu 05 Nov 1,39,452 = Tue 03 Nov 1,39,448 — while the files' OI (16,282 / 16,110)
    equals Breeze's closing OI of Tue 03 / Wed 04 Nov. So ``band_session(S1)`` = the session before S1."""
    return previous_mcx_session(oi_session)


def band_midpoint(lo: Any, hi: Any) -> float | None:
    """(lo + hi) / 2 rounded to the paisa, or None when either edge is missing / not positive."""
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if not (lo_f > 0 and hi_f > 0) or math.isnan(lo_f) or math.isnan(hi_f):
        return None
    return round((lo_f + hi_f) / 2.0, 2)


def relabel_band_sessions(store: Any) -> dict[str, Any]:
    """One-off, idempotent: rows written before wave 1d carry ``session_date = trade_date``; the band's settlement belongs
    to ``band_session(trade_date)``. Only ``session_date`` changes (not part of the key), never a value or the OI label.
    Readers never depend on this having run: they derive the band session from ``trade_date`` (``reads``)."""
    df = db.query_df(store, """SELECT DISTINCT trade_date FROM gold_curve
                               WHERE exchange = 'MCX' AND source = 'icici_master_band' AND session_date = trade_date""")
    n = 0
    for r in df.itertuples(index=False):
        td = db.to_date(r.trade_date)
        if td is None:
            continue
        db.execute(store, """UPDATE gold_curve SET session_date = ? WHERE exchange = 'MCX' AND source = 'icici_master_band'
                             AND trade_date = ? AND session_date = trade_date""", [band_session(td), td])
        n += 1
    return {"relabelled_dates": n}


def master_text_from_zip(zip_bytes: bytes) -> tuple[str, date]:
    """(MCXScripMaster.txt text, the zip entry's date = ICICI's publish date; never the download time)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        info = z.getinfo("MCXScripMaster.txt")
        return z.read(info).decode("utf-8", "ignore"), date(*info.date_time[:3])


def parse_mcx_master(text: str, published: date, *, now: datetime | None = None) -> pd.DataFrame:
    """FUTURE rows of the five gold families → gold_curve rows. ``trade_date`` = S1, the previous MCX session of the
    publish date (the session of the OI, taken from the shifted ``MarginPercentage`` column); ``band_lo`` / ``band_hi`` =
    the raw ±3 % band in force during S1; ``settle`` = the band midpoint, which is the settlement of ``session_date`` =
    ``band_session(S1)`` — ONE SESSION BEFORE the row's trade_date (wave 1d). ``quality`` proxy, ``source``
    icici_master_band. Readers re-key the midpoint to its own session (``reads.mcx_settlement_rows``)."""
    now = now or utcnow()
    session = previous_mcx_session(published)
    settle_session = band_session(session)
    pub_ist = datetime(published.year, published.month, published.day, 7, 30, tzinfo=IST)
    release_at = min(pub_ist.astimezone(ZoneInfo("UTC")).replace(tzinfo=None), now)
    rows: list[dict[str, Any]] = []
    for r in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        fam = FAMILY_BY_SHORT.get((r.get("ShortName") or "").strip().strip('"'))
        if fam is None or (r.get("Series") or "").strip() != "FUTURE":
            continue
        try:
            lo, hi = float(r["LowPriceRange"]), float(r["HighPriceRange"])
            expiry = db.strptime(r["ExpiryDate"].strip(), "%d-%b-%Y").date()
        except (KeyError, ValueError, TypeError):
            continue
        if lo <= 0 or hi <= 0:
            continue
        rows.append({"trade_date": session, "exchange": "MCX", "symbol": fam, "expiry": expiry, "open": None, "high": None, "low": None,
                     "close": None, "settle": round((lo + hi) / 2.0, 2), "band_lo": lo, "band_hi": hi, "volume": None,
                     "open_interest": int(float(r.get("MarginPercentage") or 0) or 0), "oi_change": None, "unit": QUOTE_UNIT[fam],
                     "source": "icici_master_band", "quality": "proxy", "session_date": settle_session, "release_at": release_at,
                     "first_seen_at": now})
    return pd.DataFrame(rows)


def recompute_curve_oi_change(store: Any, exchange: str = "MCX", source: str = "icici_master_band") -> None:
    db.execute(store, """
        UPDATE gold_curve SET oi_change = sub.d FROM (
            SELECT trade_date, exchange, symbol, expiry, source,
                   open_interest - LAG(open_interest) OVER (PARTITION BY exchange, symbol, expiry, source ORDER BY trade_date) AS d
            FROM gold_curve WHERE exchange = ? AND source = ?) AS sub
        WHERE gold_curve.trade_date = sub.trade_date AND gold_curve.exchange = sub.exchange AND gold_curve.symbol = sub.symbol
          AND gold_curve.expiry = sub.expiry AND gold_curve.source = sub.source""", [exchange, source])


def ingest_mcx_master(store: Any, text: str, published: date, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_mcx_master(text, published, now=now)
    n = db.upsert(store, "gold_curve", df)
    if n:
        recompute_curve_oi_change(store)
    oi_session = previous_mcx_session(published)
    front = None
    if n:
        g = df[df["symbol"] == "GOLD"].sort_values("expiry")
        if not g.empty:
            front = {"expiry": str(g.iloc[0]["expiry"]), "band_midpoint": float(g.iloc[0]["settle"]),
                     "band_session": str(band_session(oi_session)), "oi": int(g.iloc[0]["open_interest"]), "oi_session": str(oi_session)}
    return {"inserted": n, "published": str(published), "session_date": str(oi_session), "oi_session": str(oi_session),
            "band_session": str(band_session(oi_session)), "gold_front": front}


def _breeze_cache_file() -> Any:
    """The Breeze SDK's cached SecurityMaster.zip (shared/breeze_cache.py; tests redirect it)."""
    from shared import breeze_cache

    return breeze_cache.CACHE


def _refresh_breeze_cache(blob: bytes) -> bool:
    """Write a freshly published master to the Breeze SDK's cache (atomic; best effort: never fails the job).

    The cache refreshes itself at most every 20 h and only when a Breeze session starts, so the 08:00 login kept the
    previous day's file and new listings were missing from the token map; the catalog row breeze_security_master
    (job gold_mcx_master) read a session behind on 5 Nov. This job already downloads the same zip at ≈07:35."""
    try:
        if not zipfile.is_zipfile(io.BytesIO(blob)):
            return False
        dest = _breeze_cache_file()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".gold.part")
        tmp.write_bytes(blob)
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001 — the gold ingest stands on its own; the cache keeps its old copy
        return False


def fetch_mcx_master(store: Any, http: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Conditional GET (``If-Modified-Since`` = the stored ``Last-Modified``): all weekend and before ICICI's ≈07:00
    publish the answer is a 304 of a few bytes instead of the 3 MB zip (SOURCES.md F1 trap). A new master (200) is
    also written to the Breeze SDK's cache, so the token map has the day's listings."""
    headers = {}
    since = db.get_state(store, "mcx_master.last_modified")
    if since:
        headers["If-Modified-Since"] = since
    resp = http.get(SECURITY_MASTER_URL, headers=headers, timeout_s=90)
    if resp.status_code == 304:
        return {"status": "not_modified", "inserted": 0}
    if resp.status_code != 200:
        return {"status": f"http_{resp.status_code}", "inserted": 0}
    text, published = master_text_from_zip(resp.content)
    out = ingest_mcx_master(store, text, published, now=now)
    out["breeze_cache_refreshed"] = _refresh_breeze_cache(resp.content)
    lm = resp.headers.get("Last-Modified")
    if lm:
        db.set_state(store, "mcx_master.last_modified", lm, now=now)
    return {"status": "ok", **out}


# ── F8 Zerodha NRML margin mirror → gold_margins (MCX) ──────────────────────────────────────────────

_ZERODHA_ROW = re.compile(r"^(GOLD(?:M|TEN|GUINEA|PETAL)?)\s+([A-Z][a-z]{2})\s+(\d{4})\b", re.IGNORECASE)


def family_expiry(code: str, year: int, month: int) -> date:
    """The MCX expiry of ``code`` in a contract month: the 5th (GOLD, GOLDM) or the month end (TEN, GUINEA, PETAL),
    stepped back to the previous expiry-business day (weekends, full and morning-closure holidays)."""
    if code in MONTH_END_FAMILIES or code not in specs.CONTRACTS or specs.CONTRACTS[code].expiry_kind == "month_end":
        d = (pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)).date()
    else:
        d = date(year, month, 5)
    for _ in range(10):
        hol = specs.holiday_on(d)
        if d.weekday() < 5 and (hol is None or hol[1] == "evening"):
            return d
        d -= timedelta(days=1)
    return d


def parse_zerodha_margins(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """Rows 'GOLD Dec 2026 Lot size 1 | NRML Margin | NRML Margin Rate | Price' → gold_margins (source zerodha_nrml),
    dated by the page's 'updated: 25 Oct 2026' line."""
    from bs4 import BeautifulSoup

    now = now or utcnow()
    m_upd = re.search(r"pdated:\s*(\d{1,2} [A-Za-z]{3} \d{4})", html_text)
    trade_date = db.strptime(m_upd.group(1), "%d %b %Y").date() if m_upd else now.astimezone(IST).date()
    soup = BeautifulSoup(html_text, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        m = _ZERODHA_ROW.match(cells[0])
        if not m:
            continue
        code = m.group(1).upper()
        try:
            month = db.strptime(m.group(2), "%b").month
        except ValueError:
            continue
        margin, rate, price = _flt(cells[1]), _flt(cells[2]), _flt(cells[3])
        if margin is None:
            continue
        rows.append({"trade_date": trade_date, "exchange": "MCX", "symbol": code, "expiry": family_expiry(code, int(m.group(3)), month),
                     "source": "zerodha_nrml", "margin_ccy": margin, "margin_pct": rate, "ref_price": price, "first_seen_at": now})
    return pd.DataFrame(rows)


def ingest_zerodha(store: Any, html_text: str, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_zerodha_margins(html_text, now=now)
    n = db.upsert(store, "gold_margins", df)
    return {"inserted": n, "trade_date": str(df["trade_date"].iloc[0]) if n else None,
            "families": sorted(df["symbol"].unique().tolist()) if n else []}


# ── F10 IBJA AM/PM tables ───────────────────────────────────────────────────────────────────────────

_IBJA_HEADER = ["999", "995", "916", "750", "585", "silver 999"]


def parse_ibja_html(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """The two 'Previous 30 days' tables (first AM, then PM): date dd/mm/yyyy, 999…585 ₹/10 g, silver ₹/kg.
    Today's row before the fix says 'Rates will be uploaded soon' and is skipped; nothing is backfilled from the chart."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    tables = [t for t in soup.find_all("table") if t.find("table") is None]
    fixes: list[list[list[str]]] = []
    for t in tables:
        trs = t.find_all("tr")
        if not trs:
            continue
        head = [c.get_text(" ", strip=True).lower() for c in trs[0].find_all(["th", "td"])]
        if len(head) >= 7 and head[1:7] == _IBJA_HEADER:
            body = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs[1:]]
            fixes.append([r for r in body if r and re.match(r"^\d{2}/\d{2}/\d{4}$", r[0])])
    frames = []
    for fix, rows in zip(("AM", "PM"), fixes[:2]):
        pts: dict[str, list[tuple[date, float]]] = {}
        for r in rows:
            d = db.strptime(r[0], "%d/%m/%Y").date()
            for i, p in enumerate(IBJA_PURITIES, start=1):
                v = _flt(r[i]) if i < len(r) else None
                if v is not None:
                    pts.setdefault(f"IBJA_{p}_{fix}", []).append((d, v))
            silver = _flt(r[6]) if len(r) > 6 else None
            if silver is not None:
                pts.setdefault(f"IBJA_SILVER_999_{fix}", []).append((d, silver))
        for sid, series_pts in pts.items():
            frames.append(pit.series_frame(sid, sorted(series_pts), freq="D", source="ibja_page", release_kind=f"ibja_{fix.lower()}",
                                           now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── F11 RBI weekly statistical supplement (foreign-exchange reserves, gold line) ────────────────────

def parse_rbi_wss(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """'2. Foreign Exchange Reserves … As on October 16, 2026': rows '1 Total Reserves' and '1.2 Gold' (₹ cr, US$ mn)."""
    from bs4 import BeautifulSoup

    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    m = re.search(r"Foreign Exchange Reserves.{0,120}?As on ([A-Z][a-z]+ \d{1,2}, \d{4})", flat)
    if not m:
        return pd.DataFrame()
    asof = db.strptime(m.group(1), "%B %d, %Y").date()
    soup = BeautifulSoup(html_text, "html.parser")
    gold_inr = gold_usd = total_usd = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        label = cells[0].lower()
        if label.startswith("1.2 gold"):
            gold_inr, gold_usd = _flt(cells[1]), _flt(cells[2])
        elif label.startswith("1 total reserves"):
            total_usd = _flt(cells[2])
    frames = []
    for sid, v in (("RBI_GOLD_RESERVES_INR_CR", gold_inr), ("RBI_GOLD_RESERVES_USD_MN", gold_usd), ("RBI_RESERVES_TOTAL_USD_MN", total_usd)):
        if v is not None:
            frames.append(pit.series_frame(sid, [(asof, v)], freq="W", source="rbi_wss", release_kind="rbi_wss", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── F13 RBI / FBIL USD-INR reference rate ───────────────────────────────────────────────────────────

def parse_rbi_reference_rate(html_text: str, *, now: datetime | None = None, as_of: date | None = None) -> pd.DataFrame:
    """Two layouts. The archive table (rows 'dd/mm/yyyy | USD | GBP | EUR | YEN') carries its own dates. The RBI home
    sidebar ('Exchange Rates INR / 1 USD : 94.9432') carries none, so that layout is read only when the caller states
    ``as_of`` (never guessed). Series USDINR_FBIL, release 13:30 IST on the day."""
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text))
    pts: list[tuple[date, float]] = []
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\s+([\d]{2,3}\.\d{2,4})\b", flat):          # archive table
        try:
            pts.append((db.strptime(m.group(1), "%d/%m/%Y").date(), float(m.group(2))))
        except ValueError:
            continue
    if not pts and as_of is not None:
        m_val = re.search(r"INR\s*/\s*1\s*USD\s*:?\s*([\d]{2,3}\.\d{2,4})", flat)
        if m_val:
            pts.append((as_of, float(m_val.group(1))))
    return pit.series_frame("USDINR_FBIL", pts, freq="D", source="rbi_reference_rate", release_kind="rbi_ref", now=now)


# ── F16 AMFI monthly report (xls) ───────────────────────────────────────────────────────────────────

def parse_amfi_xls(xls_bytes: bytes, *, now: datetime | None = None) -> pd.DataFrame:
    """Sheet MCR_MonthlyReport, row 'Gold ETF': schemes, folios, net inflow (₹ cr), month-end AUM (₹ cr); the month from the
    header 'as on September 30, 2026'."""
    import xlrd

    wb = xlrd.open_workbook(file_contents=xls_bytes)
    sh = wb.sheet_by_name("MCR_MonthlyReport") if "MCR_MonthlyReport" in wb.sheet_names() else wb.sheet_by_index(0)
    month_end: date | None = None
    gold: list[Any] | None = None
    for i in range(sh.nrows):
        row = sh.row_values(i)
        text = " ".join(str(c) for c in row)
        if month_end is None:
            m = re.search(r"as on ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
            if m:
                month_end = db.strptime(m.group(1), "%B %d, %Y").date()
        if any(str(c).strip().lower() == "gold etf" for c in row):
            gold = [c for c in row if c != ""]
            break
    if month_end is None or gold is None:
        return pd.DataFrame()
    # [serial, 'Gold ETF', schemes, folios, mobilised, redemption, net inflow, net AUM as on month end, average AUM for the month, …]
    i0 = next(i for i, c in enumerate(gold) if str(c).strip().lower() == "gold etf")
    vals = gold[i0 + 1:]
    frames = []
    for sid, v in (("AMFI_GOLD_ETF_SCHEMES", vals[0] if len(vals) > 0 else None), ("AMFI_GOLD_ETF_FOLIOS", vals[1] if len(vals) > 1 else None),
                   ("AMFI_GOLD_ETF_NET_CR", vals[4] if len(vals) > 4 else None), ("AMFI_GOLD_ETF_AUM_CR", vals[5] if len(vals) > 5 else None),
                   ("AMFI_GOLD_ETF_AVG_AUM_CR", vals[6] if len(vals) > 6 else None)):
        f = _flt(v)
        if f is not None:
            frames.append(pit.series_frame(sid, [(month_end, f)], freq="M", source="amfi_xls", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def amfi_url(month_end: date) -> str:
    return AMFI_URL.format(mon=month_end.strftime("%b").lower(), yyyy=month_end.year)


# ── F9 duty steps, F14 hand-typed series ────────────────────────────────────────────────────────────

def duty_frame(*, now: datetime | None = None, extra: tuple[date, float] | None = None) -> pd.DataFrame:
    """GOLD_IMPORT_DUTY_PCT rows, released on their effective date (freq D, a step series)."""
    now = now or utcnow()
    steps = list(DUTY_HISTORY)
    if extra and all(extra[0] != s[0] for s in steps):
        steps.append((extra[0], extra[1], "env override GOLD_IMPORT_DUTY_PCT"))
    rows = []
    for eff, pct, note in sorted(steps):
        rel = datetime(eff.year, eff.month, eff.day, 0, 0, tzinfo=IST).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        rows.append({"series_id": "GOLD_IMPORT_DUTY_PCT", "report_date": eff, "freq": "D", "value": pct, "release_at": min(rel, now),
                     "release_source": "publisher", "first_seen_at": now, "source": f"cbic:{note}", "quality": "official", "revision": 0})
    return pd.DataFrame(rows)


def duty_on(day: date, extra: tuple[date, float] | None = None) -> tuple[float, date]:
    """(rate %, effective date) in force on ``day``."""
    steps = sorted(list(DUTY_HISTORY) + ([(extra[0], extra[1], "env")] if extra else []))
    rate, eff = steps[0][1], steps[0][0]
    for d, pct, _ in steps:
        if d <= day:
            rate, eff = pct, d
    return rate, eff


def manual_series_frame(values: list[dict[str, Any]], *, source: str = "manual", now: datetime | None = None) -> pd.DataFrame:
    """Hand-typed observations (`[{series_id, report_date, value}]`) for series whose feed has no verified URL (F14)."""
    now = now or utcnow()
    rows = []
    for v in values:
        d = db.to_date(v.get("report_date"))
        f = _flt(v.get("value"))
        sid = str(v.get("series_id") or "").strip()
        if not sid or d is None or f is None:
            continue
        rows.append({"series_id": sid, "report_date": d, "freq": str(v.get("freq") or "M"), "value": f, "release_at": now,
                     "release_source": "fetch", "first_seen_at": now, "source": source, "quality": "official", "revision": 0})
    return pd.DataFrame(rows)
