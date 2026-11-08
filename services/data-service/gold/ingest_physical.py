"""Physical, ETF, official-sector, Shanghai and OTC sources (SOURCES.md D1–D5, E1, E3, E5, E7, E8, E12, E14, E15, E19, A9, A11).

Every parser is a pure function over the fetched body so it replays from the saved research samples
(``reports/gold_program/G-PHYSICAL/samples``, ``G-CME/samples``). Terms posture (owner decision O-1): WGC / SPDR /
IBJA / SGE numbers are stored for display with attribution on the private terminal and never re-served; the
catalog row of each series carries the attribution text. Nothing here touches the CME website, the MCX site or the
LBMA price pages (link-only publishers, PLAN 0.1 #6).
"""
from __future__ import annotations

import csv
import html as html_lib
import io
import itertools
import json
import math
import re
import zipfile
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db, pit
from gold.db import utcnow
from shared.logging import get_logger

logger = get_logger(__name__)

OZ_PER_TONNE = 32150.7466
GRAMS_PER_OZ = 31.1034768
SHANGHAI = ZoneInfo("Asia/Shanghai")

GLD_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en"
IAU_URL = "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund"
WGC_FLOWS_URL = "https://fsapi.gold.org/api/v11/charts/etfv2/revised/flows-chart2"
WGC_HOLDINGS_URL = "https://fsapi.gold.org/api/v11/charts/etfv2/revised/holdings-chart2"
WGC_ARCHIVE_URL = "https://fsapi.gold.org/api/v11/charts/etfv2/revised/archive-tablegroup/all"
WGC_PREMIUMS_URL = "https://fsapi.gold.org/api/v11/charts/local-gold-price-premiums"
WGC_SD_URL = "https://fsapi.gold.org/api/v11/charts/supply-and-demand/43"
WGC_PRICE_URL = "https://fsapi.gold.org/api/goldprice/v13/chart/main?period=1y"
IMF_URL = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/{countries}.{indicators}..M"
SGE_DAILY_URL = "https://en.sge.com.cn/data/data_daily_international_new"
SGE_BENCH_HTML_URL = "https://en.sge.com.cn/data_BenchmarkPrice_Daily"
SGE_BENCH_JSON_URL = "https://en.sge.com.cn/graph/DayilyJzj"
SGE_QUOTES_URL = "https://www.sge.com.cn/graph/quotations"
SGE_MONTHLY_LIST_URL = "https://en.sge.com.cn/data_MonthlyReport"
SHFE_KX_URL = "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{yyyymmdd}.dat"
LBMA_TRADE_URL = "https://www.lbma.org.uk/prices-and-data/lbma-trade-data"
LBMA_VAULT_PAGE_URL = "https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data"
SWISS_ZIP_URL = "https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_EXP_en/TN8_EXP_en.zip"

IMF_INDICATORS: dict[str, str] = {           # SDMX indicator → series_id template
    "IRFCLDT1_IRFCL56V_FTO": "IMF_GOLD_OZ_{iso}",      # official gold, fine troy ounces
    "IRFCLDT1_IRFCL56_USD": "IMF_GOLD_USD_{iso}",      # official gold, US$ (SCALE 6 = millions)
}
WGC_REGIONS: dict[str, str] = {"North America": "NA", "Europe": "EU", "Asia": "ASIA", "Other": "OTHER"}
WGC_SD_MAP: dict[str, str] = {
    "Mine production": "MINE", "Recycled gold": "RECYCLED", "Net producer hedging": "HEDGING",
    "Jewellery fabrication": "JEWELLERY", "Technology": "TECHNOLOGY", "Total bc": "BAR_COIN", "Etfs": "ETF",
    "Central banks": "CENTRAL_BANKS", "LBMA": "LBMA_AVG_PRICE",
}
WGC_PRICE_MAP: dict[str, str] = {"lbma_am_usd": "LBMA_AM_USD", "lbma_pm_usd": "LBMA_PM_USD", "sge_am_cny": "SGE_AM_CNY_WGC",
                                 "sge_pm_cny": "SGE_PM_CNY_WGC", "mcx_am_inr": "MCX_AM_INR_WGC"}


# ── small helpers ───────────────────────────────────────────────────────────────────────────────────

def _flt(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if math.isnan(v) else float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s in ("", "-", "NA", "N/A", "US Holiday", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    f = _flt(v)
    return round(f) if f is not None else None


def _ms_date(ms: Any, tz: ZoneInfo | None = None) -> date:
    """Epoch milliseconds → calendar date: WGC stamps midnight UTC of the London date; SGE stamps midnight Beijing."""
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=tz or timezone.utc).date()


def _month_end(y: int, m: int) -> date:
    return (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).date()


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def _tables(html_text: str) -> list[Any]:
    """bs4 tables that contain no nested table (html.parser; lxml is not installed)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_text, "html.parser")
    return [t for t in soup.find_all("table") if t.find("table") is None]


def _cells(tr: Any) -> list[str]:
    return [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]


# ── E1 SPDR GLD historical archive (XLSX) ───────────────────────────────────────────────────────────

def _gld_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return db.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_gld_archive(xlsx_bytes: bytes, *, now: datetime | None = None, since: date | None = None) -> pd.DataFrame:
    """Sheet 'US GLD Historical Archive' → gold_etf_holdings rows (fund GLD). 'US Holiday' rows are skipped; the row
    for T is public at ≈06:00 IST on T+1 (release rule ``gld``). The disclaimer sheet is never stored."""
    import openpyxl

    now = now or utcnow()
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    try:
        name = next((s for s in wb.sheetnames if "archive" in s.lower()), wb.sheetnames[-1])
        ws = wb[name]
        ws.reset_dimensions()
        for row in ws.iter_rows(values_only=True):
            if not row or row[0] is None:
                continue
            d = _gld_date(row[0])
            if d is None or (since and d < since):
                continue
            tonnes = _flt(row[9]) if len(row) > 9 else None
            if tonnes is None:
                continue
            ounces, oz_per_share, nav, aum = _flt(row[8]), _flt(row[2]), _flt(row[3]), _flt(row[10]) if len(row) > 10 else None
            shares = round(ounces / oz_per_share) if ounces is not None and oz_per_share else None
            rows.append({"report_date": d, "fund": "GLD", "tonnes": tonnes, "ounces": ounces, "shares": shares, "nav": nav,
                         "aum_usd_mn": (aum / 1e6) if aum is not None else None,
                         "premium_discount": _flt(row[6]), "release_at": min(pit.release_rule("gld", d), now),
                         "first_seen_at": now, "source": "spdr_xlsx"})
    finally:
        wb.close()
    return pd.DataFrame(rows)


def ingest_gld(store: Any, xlsx_bytes: bytes, *, now: datetime | None = None, since: date | None = None) -> dict[str, Any]:
    df = parse_gld_archive(xlsx_bytes, now=now, since=since)
    n = db.upsert(store, "gold_etf_holdings", df)
    last = df.sort_values("report_date").iloc[-1] if n else None
    return {"inserted": n, "last": str(last["report_date"]) if last is not None else None,
            "tonnes": float(last["tonnes"]) if last is not None else None}


# ── E3 iShares IAU product page (regex; the CSV endpoint is dead) ───────────────────────────────────

_IAU_BLOCK = re.compile(r'"(tonnes|ounces)":\{[^{}]*?"formattedValue":"([\d,\.]+)"[^{}]*?"formattedAsOfDate":"([A-Za-z]{3} \d{1,2}, \d{4})"')
_IAU_PLAIN = re.compile(r'keyFundFacts-(tonnes|ounces)"[^>]*>([\d,\.]+)<')
_IAU_ASOF = re.compile(r'keyFundFacts-tonnes-asOf[^>]*>[^<\d]*(?:as of )?([A-Za-z]{3} \d{1,2}, \d{4})')


def parse_iau_page(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """One gold_etf_holdings row (fund IAU) from the product page: 'Tonnes in Trust 463.05 as of Oct 23, 2026'."""
    now = now or utcnow()
    txt = html_lib.unescape(html_text)
    found: dict[str, tuple[float, date]] = {}
    for key, val, asof in _IAU_BLOCK.findall(txt):
        f = _flt(val)
        if f is not None:
            found[key] = (f, db.strptime(asof, "%b %d, %Y").date())
    if "tonnes" not in found:
        plain = {k: _flt(v) for k, v in _IAU_PLAIN.findall(txt)}
        asof = _IAU_ASOF.search(txt)
        tonnes_plain, ounces_plain = plain.get("tonnes"), plain.get("ounces")
        if tonnes_plain is not None and asof:
            d = db.strptime(asof.group(1), "%b %d, %Y").date()
            found["tonnes"] = (tonnes_plain, d)
            if ounces_plain is not None:
                found["ounces"] = (ounces_plain, d)
    if "tonnes" not in found:
        return pd.DataFrame()
    tonnes, d = found["tonnes"]
    ounces = found.get("ounces", (None, d))[0]
    return pd.DataFrame([{"report_date": d, "fund": "IAU", "tonnes": tonnes, "ounces": ounces, "shares": None, "nav": None,
                          "aum_usd_mn": None, "premium_discount": None, "release_at": min(pit.release_rule("iau", d), now),
                          "first_seen_at": now, "source": "ishares_page"}])


def ingest_iau(store: Any, html_text: str, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_iau_page(html_text, now=now)
    n = db.upsert(store, "gold_etf_holdings", df)
    return {"inserted": n, "last": str(df["report_date"].iloc[0]) if n else None, "tonnes": float(df["tonnes"].iloc[0]) if n else None}


# ── E5 / E8 / E7 / A9 World Gold Council chart JSON (display-only, attributed; O-1) ──────────────────

def _chart(obj: Any) -> dict[str, Any]:
    o = json.loads(obj) if isinstance(obj, str) else obj
    return o.get("chartData") or o


def parse_wgc_flows(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """Weekly ETF flows per region (tonnes) + the global sum, and the global US$ flow (millions)."""
    cd = _chart(obj)
    weekly = cd["data"]["Weekly"]["series"]
    frames: list[pd.DataFrame] = []
    totals_t: dict[date, float] = {}
    totals_usd: dict[date, float] = {}
    for s in weekly.get("tonnes", []):
        key = WGC_REGIONS.get(s.get("name"))
        if not key:
            continue
        pts = [(_ms_date(t), float(v)) for t, v in s.get("data", []) if v is not None]
        for d, v in pts:
            totals_t[d] = totals_t.get(d, 0.0) + v
        frames.append(pit.series_frame(f"WGC_ETF_FLOW_T_{key}", pts, freq="W", source="wgc_fsapi", release_kind="wgc_weekly", now=now))
    for s in weekly.get("usd", []):
        if s.get("name") in WGC_REGIONS:
            for t, v in s.get("data", []):
                if v is not None:
                    totals_usd[_ms_date(t)] = totals_usd.get(_ms_date(t), 0.0) + float(v) / 1e6
    frames.append(pit.series_frame("WGC_ETF_FLOW_T_GLOBAL", sorted(totals_t.items()), freq="W", source="wgc_fsapi",
                                   release_kind="wgc_weekly", now=now))
    frames.append(pit.series_frame("WGC_ETF_FLOW_USD_MN_GLOBAL", sorted(totals_usd.items()), freq="W", source="wgc_fsapi",
                                   release_kind="wgc_weekly", now=now))
    return pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()


def parse_wgc_holdings(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """Weekly holdings per region (tonnes) + the global sum."""
    cd = _chart(obj)
    block = cd["data"]["Weekly"]["tonnes"]
    cols = [str(c) for c in block["columns"]]
    per: dict[str, list[tuple[date, float]]] = {k: [] for k in WGC_REGIONS.values()}
    total: list[tuple[date, float]] = []
    for row in block["set"]:
        d = _ms_date(row[0])
        tot = 0.0
        for name, key in WGC_REGIONS.items():
            if name in cols:
                v = row[cols.index(name)]
                if v is not None:
                    per[key].append((d, float(v)))
                    tot += float(v)
        total.append((d, tot))
    frames = [pit.series_frame(f"WGC_ETF_HOLD_T_{k}", pts, freq="W", source="wgc_fsapi", release_kind="wgc_weekly", now=now)
              for k, pts in per.items()]
    frames.append(pit.series_frame("WGC_ETF_HOLD_T_GLOBAL", total, freq="W", source="wgc_fsapi", release_kind="wgc_weekly", now=now))
    return pd.concat([f for f in frames if not f.empty], ignore_index=True)


def wgc_archive_table(obj: Any, section: str, period: str = "Weekly") -> tuple[date | None, pd.DataFrame]:
    """(as-of date, table) for ``regional`` | ``countries`` | ``top10_ca`` | ``bottom10_ca`` of the archive-tablegroup."""
    cd = _chart(obj)
    blk = cd["data"][section][period]
    data = blk["data"]
    cols = [" ".join(re.sub(r"<br\s*/?>", " ", str(c)).split()) for c in data["columns"]]
    rows = [data[k] for k in sorted((k for k in data if k.isdigit()), key=int)]
    asof = db.to_date(blk.get("asOfDate"))
    return asof, pd.DataFrame(rows, columns=cols)


def parse_wgc_archive(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """India's ETF holdings (tonnes) from the weekly country table (series WGC_ETF_HOLD_T_IN)."""
    asof, tbl = wgc_archive_table(obj, "countries", "Weekly")
    if asof is None or tbl.empty:
        return pd.DataFrame()
    hold_col = next((c for c in tbl.columns if c.lower().startswith("holdings")), None)
    row = tbl[tbl.iloc[:, 0].astype(str).str.strip().str.lower() == "india"]
    if hold_col is None or row.empty:
        return pd.DataFrame()
    return pit.series_frame("WGC_ETF_HOLD_T_IN", [(asof, _flt(row.iloc[0][hold_col]))], freq="W", source="wgc_fsapi",
                            release_kind="wgc_weekly", now=now)


def parse_wgc_premiums(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """India / China local premiums ($/oz). The chart is daily-spaced; stored with the spacing it has."""
    cd = _chart(obj)
    frames = []
    for key, sid in (("india_premdisc", "WGC_PREMIUM_IN"), ("china_premdisc", "WGC_PREMIUM_CN")):
        pts = [(_ms_date(t), float(v)) for t, v in cd.get(key, []) if v is not None]
        if not pts:
            continue
        gaps = [(b[0] - a[0]).days for a, b in itertools.pairwise(pts)]
        freq = "D" if gaps and sorted(gaps)[len(gaps) // 2] <= 3 else "W"
        frames.append(pit.series_frame(sid, pts, freq=freq, source="wgc_fsapi", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _quarter_end(label: str) -> date | None:
    m = re.match(r"Q([1-4])\s*'(\d{2})", str(label))
    if not m:
        return None
    q, yy = int(m.group(1)), 2000 + int(m.group(2))
    return _month_end(yy, q * 3)


def parse_wgc_sd(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """Quarterly balance sheet (tonnes): supply (mine, recycled, hedging) and demand categories, plus the OTC & other
    balancing item = supply − (jewellery + technology + bar & coin + ETFs + central banks)."""
    cd = _chart(obj)
    series: dict[str, dict[date, float]] = {}
    for block in ("Supply_Quarterly", "Demand_Quarterly"):
        blk = cd.get(block) or {}
        cats = [_quarter_end(c) for c in blk.get("categories", [])]
        for s in blk.get("series", []):
            key = WGC_SD_MAP.get(s.get("name"))
            if not key:
                continue
            series.setdefault(key, {})
            for d, v in zip(cats, s.get("data", [])):
                if d is not None and v is not None:
                    series[key][d] = float(v)
    otc: dict[date, float] = {}
    for d in series.get("MINE", {}):
        supply = series["MINE"].get(d, 0.0) + series.get("RECYCLED", {}).get(d, 0.0) + series.get("HEDGING", {}).get(d, 0.0)
        demand_keys = ("JEWELLERY", "TECHNOLOGY", "BAR_COIN", "ETF", "CENTRAL_BANKS")
        if all(d in series.get(k, {}) for k in demand_keys):
            otc[d] = round(supply - sum(series[k][d] for k in demand_keys), 3)
    series["OTC_OTHER"] = otc
    frames = [pit.series_frame(f"WGC_SD_{k}", sorted(v.items()), freq="Q", source="wgc_fsapi", now=now) for k, v in series.items() if v]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parse_wgc_price(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """LBMA AM/PM (USD), SGE AM/PM (CNY/g) and the MCX AM reference (INR) — provisional reference marks (A9)."""
    cd = _chart(obj)
    frames = []
    for key, sid in WGC_PRICE_MAP.items():
        pts = [(_ms_date(t), float(v)) for t, v in cd.get(key, []) if v is not None]
        if pts:
            frames.append(pit.series_frame(sid, pts, freq="D", source="wgc_fsapi", quality="official", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── E12 IMF IRFCL (SDMX CSV) ────────────────────────────────────────────────────────────────────────

def imf_url(countries: Iterable[str], start_period: str = "2000-01") -> tuple[str, dict[str, str]]:
    url = IMF_URL.format(countries="+".join(countries), indicators="+".join(IMF_INDICATORS))
    return url, {"startPeriod": start_period, "format": "csv"}


IMF_OZ_MAX = 300e6             # no country holds 300 Moz (USA 261.5 Moz is the ceiling): above it the row is a unit error → rejected
IMF_RESCALE_FACTORS = (1.0, 1e3, 1e6)   # the ounce value may carry 3 or 6 spurious digits (BRA: ×1000, wave 1c C-TRADER-6 / C-DATA-5)
IMF_PRICE_BAND = (0.5, 2.0)    # an ounce series is consistent with its USD series when USD/oz is within this band of the reference


def imf_oz_scale(oz: float | None, usd: float | None, ref_price: float | None) -> tuple[float, str]:
    """(divisor, quality) for one country's ounce value. The IRFCL CSV's SCALE column is 6 for every country while the
    values are plainly in units (IND 28.3 M oz = 880 t, USA 261.5 M oz), so SCALE is a display attribute, never a
    multiplier; the only check that catches a ×1000 reporting error is the country's OWN USD value: the implied USD/oz
    must sit within ``IMF_PRICE_BAND`` of the reference price for exactly one divisor in ``IMF_RESCALE_FACTORS``.
    Book-value reporters (USA at $42.22/oz) match no divisor and are kept as published (quality ``official``)."""
    if not oz or not usd or not ref_price or oz <= 0 or usd <= 0 or ref_price <= 0:
        return 1.0, "official"
    for k in IMF_RESCALE_FACTORS:
        implied = usd / (oz / k)
        if IMF_PRICE_BAND[0] <= implied / ref_price <= IMF_PRICE_BAND[1]:
            return k, ("official" if k == 1.0 else f"rescaled_x{int(k)}")
    return 1.0, "official"


def parse_imf_csv(text: str, *, now: datetime | None = None, ref_price: float | None = None) -> pd.DataFrame:
    """Rows per (country, indicator, TIME_PERIOD 'YYYY-Mmm') → gold_series monthly points. Empty periods are skipped;
    a repeated value is stored as the IMF publishes it (the UI reads TIME_PERIOD, SOURCES.md E12 trap).

    Ounce values are stored in TROY OUNCES (units; catalog unit ``oz``). Each country's ounces are cross-checked against
    its own USD value with ``ref_price`` (a recent $/oz close; without it the median implied price of the batch's
    market-value reporters stands in) and divided by 1,000 / 1,000,000 when that is the only way the two agree
    (``quality = rescaled_x1000``); a value above ``IMF_OZ_MAX`` after that is rejected (``rejected`` in the result log)."""
    pts: dict[str, list[tuple[date, float]]] = {}
    for rec in csv.DictReader(io.StringIO(text)):
        tmpl = IMF_INDICATORS.get((rec.get("INDICATOR") or "").strip())
        tp = (rec.get("TIME_PERIOD") or "").strip()
        m = re.match(r"^(\d{4})-M(\d{1,2})$", tp)
        if not tmpl or not m:
            continue
        v = _flt(rec.get("OBS_VALUE"))
        if v is None:
            continue
        sid = tmpl.format(iso=(rec.get("COUNTRY") or "").strip())
        pts.setdefault(sid, []).append((_month_end(int(m.group(1)), int(m.group(2))), v))
    # the IRFCL CSV repeats a (country, period) under several DATA_DOMAIN / FREQ rows: keep the LAST record per month,
    # otherwise two rows share (series_id, report_date, release_at) and the upsert dies on the primary key
    # (imf_official 'degraded' on 4 Nov: duplicate key IMF_GOLD_OZ_DEU 2025-01-31)
    pts = {sid: sorted(dict(p).items()) for sid, p in pts.items()}
    usd_latest: dict[str, float] = {sid[len("IMF_GOLD_USD_"):]: max(p)[1] for sid, p in pts.items() if sid.startswith("IMF_GOLD_USD_")}
    oz_latest: dict[str, float] = {sid[len("IMF_GOLD_OZ_"):]: max(p)[1] for sid, p in pts.items() if sid.startswith("IMF_GOLD_OZ_")}
    if ref_price is None:
        implied = sorted(usd_latest[c] / oz_latest[c] for c in oz_latest if c in usd_latest and oz_latest[c] > 0 and usd_latest[c] / oz_latest[c] >= 500)
        ref_price = implied[len(implied) // 2] if implied else None
    usd_by_month: dict[str, dict[date, float]] = {sid[len("IMF_GOLD_USD_"):]: dict(p) for sid, p in pts.items() if sid.startswith("IMF_GOLD_USD_")}
    frames = []
    for sid, p in pts.items():
        if sid.startswith("IMF_GOLD_OZ_"):
            # The scale is decided per (country, MONTH) from that month's own USD value: a series can switch from units
            # to ×1000 mid-stream (BRA: units to Feb 2026, ×1000 from Mar 2026), so one divisor per country would corrupt
            # the other half. A month without a USD value falls back to the latest pair's divisor.
            iso = sid[len("IMF_GOLD_OZ_"):]
            k_latest, _ = imf_oz_scale(oz_latest.get(iso), usd_latest.get(iso), ref_price)
            by_quality: dict[str, list[tuple[date, float]]] = {}
            rejected = 0
            for d, v in p:
                usd_m = usd_by_month.get(iso, {}).get(d)
                k, q = imf_oz_scale(v, usd_m, ref_price) if usd_m else (k_latest, "official" if k_latest == 1.0 else f"rescaled_x{int(k_latest)}")
                v2 = v / k
                if v2 > IMF_OZ_MAX:
                    rejected += 1
                    continue
                by_quality.setdefault(q, []).append((d, v2))
            if rejected:
                logger.warning("gold.imf.ounces_rejected", series_id=sid, months=rejected, max_value=max(v for _, v in p))
            for q, rows in by_quality.items():
                frames.append(pit.series_frame(sid, sorted(rows), freq="M", source="imf_irfcl", quality=q, now=now))
            continue
        frames.append(pit.series_frame(sid, sorted(p), freq="M", source="imf_irfcl", quality="official", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── D3 SGE daily market data (HTML table) ───────────────────────────────────────────────────────────

_SGE_GOLD = re.compile(r"^(?:i|m|NY)?Au", re.IGNORECASE)


def parse_sge_daily_html(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """The international/main-board daily table → gold_asia_daily rows (exchange SGE) for every gold contract
    (Au99.99 spot, Au(T+D) deferred incl. OI, direction and delivery lots)."""
    now = now or utcnow()
    rows: list[dict[str, Any]] = []
    for t in _tables(html_text):
        trs = t.find_all("tr")
        if not trs:
            continue
        header = [h.lower() for h in _cells(trs[0])]
        if "contract" not in header or "close" not in header:
            continue
        idx = {h: i for i, h in enumerate(header)}

        def col(cells: list[str], *names: str, idx: dict[str, int] = idx) -> str | None:
            for n in names:
                for h, i in idx.items():
                    if h.startswith(n) and i < len(cells):
                        return cells[i]
            return None

        for tr in trs[1:]:
            cells = _cells(tr)
            if len(cells) < 6:
                continue
            d = db.to_date(col(cells, "date", "trade date"))
            contract = (col(cells, "contract") or "").strip()
            if d is None or not _SGE_GOLD.match(contract):
                continue
            rows.append({"trade_date": d, "exchange": "SGE", "contract": contract, "open": _flt(col(cells, "open")),
                         "high": _flt(col(cells, "highest", "high")), "low": _flt(col(cells, "lowest", "low")),
                         "close": _flt(col(cells, "close")), "settle": None, "vwap": _flt(col(cells, "weighted")),
                         "volume_kg": _flt(col(cells, "volume (kg)", "volume(kg)", "volume")), "turnover": _flt(col(cells, "amount")),
                         "open_interest": _int(col(cells, "open interest")), "oi_change": None,
                         "direction": (col(cells, "direction") or None) or None, "delivery_lots": _int(col(cells, "delivery")),
                         "unit": "CNY/g", "source": "sge_daily_html", "release_at": min(pit.release_rule("sge_daily", d), now),
                         "first_seen_at": now})
    return pd.DataFrame(rows)


def recompute_asia_oi_change(store: Any) -> None:
    db.execute(store, """
        UPDATE gold_asia_daily SET oi_change = sub.d FROM (
            SELECT trade_date, exchange, contract, source,
                   open_interest - LAG(open_interest) OVER (PARTITION BY exchange, contract, source ORDER BY trade_date) AS d
            FROM gold_asia_daily WHERE open_interest IS NOT NULL) AS sub
        WHERE gold_asia_daily.trade_date = sub.trade_date AND gold_asia_daily.exchange = sub.exchange
          AND gold_asia_daily.contract = sub.contract AND gold_asia_daily.source = sub.source
          AND gold_asia_daily.oi_change IS NULL""")


def ingest_sge_daily(store: Any, html_text: str, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_sge_daily_html(html_text, now=now)
    n = db.upsert(store, "gold_asia_daily", df)
    if n:
        recompute_asia_oi_change(store)
    return {"inserted": n, "last": str(df["trade_date"].max()) if n else None, "contracts": sorted(df["contract"].unique().tolist()) if n else []}


# ── A11 SGE benchmark (HTML last 7 sessions; JSON since 2016) ───────────────────────────────────────

def parse_sge_benchmark_html(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    from bs4 import BeautifulSoup

    am, pm = [], []
    tables = _tables(html_text) or [BeautifulSoup(html_text, "html.parser")]     # the page serves a bare <thead>/<tbody> fragment
    for t in tables:
        trs = t.find_all("tr")
        if not trs or "benchmark" not in " ".join(_cells(trs[0])).lower():
            continue
        for tr in trs[1:]:
            c = _cells(tr)
            if len(c) < 4:
                continue
            d = db.to_date(c[0]) if "-" in c[0] else (db.strptime(c[0], "%Y%m%d").date() if c[0].isdigit() else None)
            if d is None:
                continue
            if _flt(c[2]) is not None:
                am.append((d, _flt(c[2])))
            if _flt(c[3]) is not None:
                pm.append((d, _flt(c[3])))
    frames = [pit.series_frame("SGE_SHAU_AM", am, freq="D", source="sge_html", release_kind="sge_am", now=now),
              pit.series_frame("SGE_SHAU_PM", pm, freq="D", source="sge_html", release_kind="sge_pm", now=now)]
    return pd.concat([f for f in frames if not f.empty], ignore_index=True) if (am or pm) else pd.DataFrame()


def parse_sge_benchmark_json(obj: Any, *, now: datetime | None = None, since: date | None = None) -> pd.DataFrame:
    """``{zp: [[ms, AM], …], wp: [[ms, PM], …]}`` (DayilyJzj); the JSON lags the HTML by a day."""
    o = json.loads(obj) if isinstance(obj, str) else obj
    frames = []
    for key, sid, kind in (("zp", "SGE_SHAU_AM", "sge_am"), ("wp", "SGE_SHAU_PM", "sge_pm")):
        pts = [(_ms_date(t, SHANGHAI), float(v)) for t, v in o.get(key, []) if v is not None]
        if since:
            pts = [p for p in pts if p[0] >= since]
        if pts:
            frames.append(pit.series_frame(sid, pts, freq="D", source="sge_json", release_kind=kind, now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── D4 SGE delayed intraday quotations (JSON) ───────────────────────────────────────────────────────

def parse_sge_quotations(obj: Any, *, now: datetime | None = None) -> pd.DataFrame:
    """``{times: ['20:00', …, '15:30'], data: ['865.0', …], heyue: 'Au99.99', delaystr: '2026年11月09日 20:07:54', now: '20:08'}``
    → 1-minute rows for symbol SGE_AU9999.

    **Unit: CNY per gram, as SGE publishes it.** ``gold_bars_intraday`` has no unit column, so the SYMBOL carries the
    unit: SGE_AU9999 is yuan per gram, GC=F is USD per troy ounce, INR=X is a rupee rate. Whoever serves these bars must
    convert (ui-api ``bars_unit`` / ``sge_usd_oz_bars`` does: CNY/g × 31.1034768 ÷ the USDCNY vintage on or before the
    FIRST Shanghai date of the drawn session, one rate for the whole session — a rate chosen per bar stepped the served
    line at Beijing midnight). Never convert here: the store is point-in-time and keeps what the publisher printed. CT-01 / F1
    (8 Nov 2026): nothing converted, so 868.0 CNY/g was drawn on the 24-h chart's USD/oz axis and printed as "$868.00".

    SGE's convention (seen live Fri 6 Nov 2026 20:08 Beijing, when delaystr read 09 Nov): ``delaystr`` is the TRADING DAY T
    plus the Beijing clock of the last delayed quote, and ``times`` is T's whole session template — the night session
    20:00→02:30 that runs on the evening of the business day before T, then T's day session — with every minute after
    the last quote padded with the last price. So: a minute ≥ 20:00 is on prev_business_day(T), a minute before 03:00 the
    calendar day after that, a day-session minute on T; minutes later in the session than the delaystr clock are padding
    and dropped, and nothing later than ``now`` is ever returned. (Until 6 Nov the parser read delaystr's date as the
    calendar day: a Friday-night fetch stamped the evening's quotes on Sunday and padded Monday's day session into the
    future; a weekend fetch could overwrite the previous Friday's real day bars with padding.)"""
    now = now or utcnow()
    o = json.loads(obj) if isinstance(obj, str) else obj
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", str(o.get("delaystr") or ""))
    if not m:
        return pd.DataFrame()
    trading_day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    last_quote = int(m.group(4)) * 60 + int(m.group(5))
    times, data = o.get("times") or [], o.get("data") or []
    night_day = trading_day - timedelta(days=1)
    while night_day.weekday() >= 5:                     # Monday's night session runs on Friday evening
        night_day -= timedelta(days=1)

    def offset(minute: int) -> int:                     # minutes since the session opened at 20:00 (monotonic in `times`)
        return (minute - 20 * 60) % 1440

    cut = offset(last_quote)
    now_naive = now.replace(tzinfo=None) if now.tzinfo is None else now.astimezone(timezone.utc).replace(tzinfo=None)
    rows = []
    for t, v in zip(times, data):
        try:
            hh, mm = (int(x) for x in str(t).split(":")[:2])
        except ValueError:
            continue
        minute = hh * 60 + mm
        if offset(minute) > cut:                        # after the last delayed quote: padding, not a price
            continue
        px = _flt(v)
        if px is None:
            continue
        if minute >= 20 * 60:
            day = night_day
        elif minute < 3 * 60:
            day = night_day + timedelta(days=1)
        else:
            day = trading_day
        ts = datetime(day.year, day.month, day.day, hh, mm, tzinfo=SHANGHAI).astimezone(timezone.utc).replace(tzinfo=None)
        if ts > now_naive:                              # defensive: never a bar from the future
            continue
        rows.append({"symbol": "SGE_AU9999", "ts": ts, "interval": "1m", "open": px, "high": px, "low": px, "close": px, "volume": 0,
                     "source": "sge_quotations", "first_seen_at": now})
    return pd.DataFrame(rows)


# ── D5 SGE monthly Data Highlights (PDF) ────────────────────────────────────────────────────────────

def parse_sge_monthly_pdf(pdf_bytes: bytes, *, now: datetime | None = None) -> pd.DataFrame:
    """Gold withdrawals (kg, present month) and the delivery ratio from the monthly PDF (pypdf text)."""
    from pypdf import PdfReader

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages)
    flat = re.sub(r"\s+", " ", text)
    m_month = re.search(r"Data Highlights[^A-Za-z]*(?:\(Volume & Amount\)\s*)?([A-Z][a-z]+)\s+(\d{4})", flat)
    if not m_month:
        return pd.DataFrame()
    month = db.strptime(f"{m_month.group(1)} {m_month.group(2)}", "%B %Y")
    d = _month_end(month.year, month.month)
    frames = []
    m_w = re.search(r"Withdrawal Volume \(Present Month\)\s+([\d,\.]+)", flat)
    if m_w:
        frames.append(pit.series_frame("SGE_WITHDRAWALS_KG", [(d, _flt(m_w.group(1)))], freq="M", source="sge_pdf", now=now))
    m_r = re.search(r"Delivery Ratio \(Present Month\)\s+([\d\.]+)%", flat)
    if m_r:
        frames.append(pit.series_frame("SGE_DELIVERY_RATIO", [(d, _flt(m_r.group(1)))], freq="M", source="sge_pdf", now=now))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ── D1 SHFE daily futures (kxYYYYMMDD.dat) ──────────────────────────────────────────────────────────

def parse_shfe_kx(obj: Any, trade_date: date, *, now: datetime | None = None, product: str = "au_f") -> pd.DataFrame:
    """``o_curinstrument[]`` rows for gold (``PRODUCTID == 'au_f'``), one per delivery month; subtotal rows skipped."""
    now = now or utcnow()
    if isinstance(obj, str):
        try:
            o = json.loads(obj)
        except ValueError:                      # a non-trading day answers with an HTML page (SOURCES.md D1)
            return pd.DataFrame()
    else:
        o = obj
    rows = []
    for r in o.get("o_curinstrument") or []:
        if str(r.get("PRODUCTID") or "").strip() != product:
            continue
        dm = str(r.get("DELIVERYMONTH") or "").strip()
        if not re.match(r"^\d{4}$", dm):
            continue
        rows.append({"trade_date": trade_date, "exchange": "SHFE", "contract": f"au{dm}", "open": _flt(r.get("OPENPRICE")),
                     "high": _flt(r.get("HIGHESTPRICE")), "low": _flt(r.get("LOWESTPRICE")), "close": _flt(r.get("CLOSEPRICE")),
                     "settle": _flt(r.get("SETTLEMENTPRICE")), "vwap": None, "volume_kg": _flt(r.get("VOLUME")),
                     "turnover": _flt(r.get("TURNOVER")), "open_interest": _int(r.get("OPENINTEREST")),
                     "oi_change": _int(r.get("OPENINTERESTCHG")), "direction": None, "delivery_lots": None, "unit": "CNY/g",
                     "source": "shfe_kx", "release_at": min(pit.release_rule("shfe", trade_date), now), "first_seen_at": now})
    return pd.DataFrame(rows)


def ingest_shfe(store: Any, obj: Any, trade_date: date, *, now: datetime | None = None) -> dict[str, Any]:
    df = parse_shfe_kx(obj, trade_date, now=now)
    n = db.upsert(store, "gold_asia_daily", df)
    return {"inserted": n, "trade_date": str(trade_date), "total_oi": int(df["open_interest"].fillna(0).sum()) if n else None}


# ── E14 / E15 LBMA pages ────────────────────────────────────────────────────────────────────────────

_LBMA_TURNOVER = re.compile(r"period ending (\d{1,2} [A-Za-z]+ \d{4})\.?\s*Gold:\s*\$([\d,\.]+)\s*bn\s*Silver:\s*\$([\d,\.]+)\s*bn", re.IGNORECASE)


def parse_lbma_turnover(html_text: str, *, now: datetime | None = None) -> pd.DataFrame:
    """The headline of the trade-data page: '12 week moving average … period ending 16 October 2026. Gold: $964.17 bn'.
    EVERY period the page shows is kept (wave 1d: the page carried one period on 5 Nov 2026 — 16 Oct, verified with one
    GET — and the stored history grows by one point per new period; ``upsert_series`` never drops an older one)."""
    gold: dict[date, float | None] = {}
    silver: dict[date, float | None] = {}
    for m in _LBMA_TURNOVER.finditer(_strip_tags(html_text)):
        try:
            d = db.strptime(m.group(1), "%d %B %Y").date()
        except ValueError:
            continue
        gold.setdefault(d, _flt(m.group(2)))
        silver.setdefault(d, _flt(m.group(3)))
    if not gold:
        return pd.DataFrame()
    frames = [pit.series_frame("LBMA_OTC_TURNOVER_USD_BN", sorted(gold.items()), freq="W", source="lbma_page",
                               release_kind="lbma_turnover", now=now),
              pit.series_frame("LBMA_OTC_TURNOVER_SILVER_USD_BN", sorted(silver.items()), freq="W", source="lbma_page",
                               release_kind="lbma_turnover", now=now)]
    return pd.concat(frames, ignore_index=True)


def lbma_vault_href(html_text: str) -> str | None:
    m = re.search(r"https?://cdn\.lbma\.org\.uk/[^\"'\s]*Vault[^\"'\s]*\.xlsx", html_text)
    return m.group(0) if m else None


def parse_lbma_vault_xlsx(xlsx_bytes: bytes, *, now: datetime | None = None) -> pd.DataFrame:
    """'Month End | Gold | Silver' in thousand troy ounces → tonnes (×1000 ÷ 32,150.7466); mixed '2026-09' / datetime dates."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    gold, silver = [], []
    try:
        ws = wb[wb.sheetnames[0]]
        ws.reset_dimensions()
        for row in ws.iter_rows(values_only=True):
            if not row or row[0] is None:
                continue
            d: date | None
            if isinstance(row[0], datetime):
                d = _month_end(row[0].year, row[0].month)
            else:
                m = re.match(r"^(\d{4})-(\d{1,2})$", str(row[0]).strip())
                d = _month_end(int(m.group(1)), int(m.group(2))) if m else None
            if d is None:
                continue
            g, s = _flt(row[1]), _flt(row[2]) if len(row) > 2 else None
            if g is not None:
                gold.append((d, round(g * 1000.0 / OZ_PER_TONNE, 2)))
            if s is not None:
                silver.append((d, round(s * 1000.0 / OZ_PER_TONNE, 2)))
    finally:
        wb.close()
    frames = [pit.series_frame("LBMA_VAULT_GOLD_T", sorted(gold), freq="M", source="lbma_xlsx", now=now),
              pit.series_frame("LBMA_VAULT_SILVER_T", sorted(silver), freq="M", source="lbma_xlsx", now=now)]
    return pd.concat([f for f in frames if not f.empty], ignore_index=True) if (gold or silver) else pd.DataFrame()


# ── E19 Swiss customs open data (streamed zip; format confirmed on the first live run, PLAN j.2 #5) ──

_SWISS_TARIFF = ("7108.1200", "71081200", "7108.12")


def parse_swiss_zip(path: str, *, now: datetime | None = None, partner: str = "India",
                    tariffs: tuple[str, ...] = _SWISS_TARIFF) -> pd.DataFrame:
    """Stream every CSV member line by line, keep tariff 7108.12 × partner rows, sum the quantity per month.

    Column detection is by header keyword (tariff / partner / period / quantity) because the file's exact layout and
    unit (kg) are not verified yet; the header seen is logged (never the rows) so the first run can be audited."""
    now = now or utcnow()
    monthly: dict[date, float] = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.lower().endswith((".csv", ".txt")):
                continue
            with z.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="ignore")
                reader = csv.reader(text, delimiter=_sniff_delim(text))
                header = [h.strip().lower() for h in next(reader, [])]
                logger.info("gold.swiss.header", member=name, columns=len(header), header=header[:40])   # names only, never rows
                ci = _swiss_columns(header)
                if ci is None:
                    continue
                for rec in reader:
                    if len(rec) <= max(ci.values()):
                        continue
                    tn = rec[ci["tariff"]].strip()
                    if not any(tn.startswith(t) for t in tariffs) or partner.lower() not in rec[ci["partner"]].lower():
                        continue
                    d = _swiss_period(rec, ci)
                    q = _flt(rec[ci["quantity"]])
                    if d is None or q is None:
                        continue
                    monthly[d] = monthly.get(d, 0.0) + q
    return pit.series_frame("SWISS_GOLD_EXPORT_IN_KG", sorted(monthly.items()), freq="M", source="bazg_open_data", now=now)


def _sniff_delim(text: io.TextIOWrapper) -> str:
    pos = text.tell()
    head = text.read(4096)
    text.seek(pos)
    return ";" if head.count(";") > head.count(",") else ","


def _swiss_columns(header: list[str]) -> dict[str, int] | None:
    # Keys in PRIORITY order, each tried across the whole header before the next key. The real BAZG TN8 header (seen
    # 6 Nov 2026: Traffic_direction, year, quarter, Quarter_txt, month, Month_txt, Tariffnumber8, …, Country_isoAlpha2,
    # Country_num, Country_txt, Supplementary_unit_code, Supplementary_unit_txt, Supplementary_quantity, Quantity_kg,
    # Value_CHF, …, status, Update) put Country_isoAlpha2 ('IN') before Country_txt ('India') and Supplementary_quantity
    # before Quantity_kg, so the old header-order match read the ISO code (no 'india' in 'in': 0 rows) and the unit count.
    def find(*keys: str) -> int | None:
        for k in keys:
            for i, h in enumerate(header):
                if k in h:
                    return i
        return None

    tariff = find("tariffnumber8", "tariff", "tarif", "tn")
    partner = find("country_txt", "partner", "country_name", "country", "land")
    qty = find("quantity_kg", "quantity (kg)", "kg", "menge", "net", "quantity")
    period: int | None = find("period", "month", "monat", "date")
    year, month = find("year", "jahr"), find("month", "monat")
    if tariff is None or partner is None or qty is None or (period is None and (year is None or month is None)):
        return None
    out: dict[str, int] = {"tariff": tariff, "partner": partner, "quantity": qty}
    if period is not None:
        out["period"] = period
    if year is not None and month is not None:
        out["year"], out["month"] = year, month
    return out


def _swiss_period(rec: list[str], ci: dict[str, int]) -> date | None:
    if "year" in ci and "month" in ci and ci["year"] != ci["month"]:
        try:
            return _month_end(int(rec[ci["year"]]), int(rec[ci["month"]]))
        except (ValueError, TypeError):
            return None
    raw = rec[ci["period"]].strip() if "period" in ci else ""
    m = re.match(r"^(\d{4})[-/.]?(\d{1,2})", raw)
    if m:
        return _month_end(int(m.group(1)), int(m.group(2)))
    return None


# ── generic series ingest helper (every parser above returns gold_series rows) ──────────────────────

def ingest_series(store: Any, df: pd.DataFrame, *, now: datetime | None = None) -> dict[str, Any]:
    res: dict[str, Any] = dict(pit.upsert_series(store, df, now=now))
    res["series"] = sorted(df["series_id"].unique().tolist()) if df is not None and not df.empty else []
    res["last"] = str(df["report_date"].max()) if df is not None and not df.empty else None
    return res
