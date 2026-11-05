"""
Yahoo Finance quoteSummary fundamentals provider.

Fetches PE, market cap, revenue, margins, ROCE etc. for NSE stocks.
Writes to stock_metrics table in DuckDB (the table the stocks UI router reads).
"""
from __future__ import annotations

import random
import time
from datetime import date
from typing import Optional

import requests

from shared.logging import get_logger

logger = get_logger(__name__)

NSE_SUFFIX = ".NS"
_CRORE = 1e7  # 1 crore = 10 million rupees


def _get_session() -> requests.Session:
    """Create a requests session with Yahoo Finance crumb authentication."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    s._yf_crumb: str | None = None  # type: ignore[attr-defined]
    try:
        # Step 1: hit Yahoo Finance to seed cookies
        s.get("https://fc.yahoo.com", timeout=10)
        # Step 2: obtain crumb (requires the cookies from step 1)
        cr = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if cr.status_code == 200 and cr.text.strip() and cr.text.strip() != "null":
            s._yf_crumb = cr.text.strip()
            logger.info("Yahoo Finance crumb obtained", crumb=s._yf_crumb[:6] + "…")
        else:
            logger.warning("Could not obtain Yahoo Finance crumb", status=cr.status_code)
    except Exception as exc:
        logger.warning("Crumb fetch failed", error=str(exc))
    return s


def _raw(d: dict, key: str) -> Optional[float]:
    """Extract .raw float from Yahoo Finance dict value."""
    val = d.get(key)
    if val is None:
        return None
    if isinstance(val, dict):
        r = val.get("raw")
        return float(r) if r is not None else None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fetch_fundamentals(ticker: str, session: requests.Session) -> Optional[dict]:
    """
    Fetch fundamental metrics for one NSE ticker via Yahoo Finance quoteSummary.
    Returns a flat dict with all stock_metrics fields, or None on failure.
    """
    yf_ticker = ticker if ticker.endswith(NSE_SUFFIX) else f"{ticker}{NSE_SUFFIX}"
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{yf_ticker}"
    params: dict = {
        "modules": "summaryDetail,financialData,defaultKeyStatistics,incomeStatementHistoryQuarterly"
    }
    crumb = getattr(session, "_yf_crumb", None)
    if crumb:
        params["crumb"] = crumb

    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=20)

            if r.status_code == 401:
                # Crumb expired — refresh and retry once
                try:
                    session.get("https://fc.yahoo.com", timeout=10)
                    cr = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
                    if cr.status_code == 200 and cr.text.strip() and cr.text.strip() != "null":
                        session._yf_crumb = cr.text.strip()  # type: ignore[attr-defined]
                        params["crumb"] = session._yf_crumb
                        logger.info("Yahoo Finance crumb refreshed")
                except Exception:
                    pass
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None

            if r.status_code == 429:
                wait = 30 + random.uniform(5, 15) * (attempt + 1)
                logger.warning("Rate-limited on fundamentals", ticker=ticker, wait_s=round(wait, 1))
                time.sleep(wait)
                continue

            if r.status_code != 200:
                return None

            data = r.json()
            result = data.get("quoteSummary", {}).get("result")
            if not result:
                return None

            r0 = result[0]
            sd = r0.get("summaryDetail", {})
            fd = r0.get("financialData", {})
            ks = r0.get("defaultKeyStatistics", {})

            # Quarterly income statement for NP/Sales QTR
            qis_list = (
                r0.get("incomeStatementHistoryQuarterly", {})
                .get("incomeStatementHistory", [])
            )
            latest_qtr = qis_list[0] if qis_list else {}
            prev_qtr   = qis_list[1] if len(qis_list) > 1 else {}

            # Raw values
            mktcap_raw   = _raw(sd, "marketCap") or _raw(ks, "marketCap")
            rev_qtr_raw  = _raw(latest_qtr, "totalRevenue")
            np_qtr_raw   = _raw(latest_qtr, "netIncome")
            rev_qtr_prev = _raw(prev_qtr, "totalRevenue")
            np_qtr_prev  = _raw(prev_qtr, "netIncome")
            total_rev    = _raw(fd, "totalRevenue")
            roe          = _raw(fd, "returnOnEquity")
            roa          = _raw(fd, "returnOnAssets")
            gross_margin = _raw(fd, "grossMargins")
            op_margin    = _raw(fd, "operatingMargins")

            # ROCE = EBIT / Capital Employed ≈ operatingMargins * revenue / total assets
            # We don't have total assets directly; use ROE as a proxy when ROCE unavailable.
            # Better: (operatingMargins * totalRevenue) / (totalRevenue * (1 + debtToEquity/100))
            debt_eq = _raw(fd, "debtToEquity")  # as %, e.g. 45.2 means 0.452
            roce_pct: Optional[float] = None
            if op_margin is not None and total_rev is not None and total_rev > 0:
                ebit = op_margin * total_rev
                if debt_eq is not None and debt_eq >= 0:
                    # Capital employed proportional approximation
                    cap_factor = 1 + (debt_eq / 100.0)
                    roce_pct = round((ebit / (total_rev * cap_factor)) * 100, 2)
                elif roe is not None:
                    roce_pct = round(roe * 100, 2)

            def _qtr_var(curr, prev) -> Optional[float]:
                if curr is None or prev is None or prev == 0:
                    return None
                return round((curr - prev) / abs(prev) * 100, 2)

            current_price = _raw(fd, "currentPrice")

            return {
                "ticker":       ticker,
                "as_of_date":   str(date.today()),
                "cmp":          current_price,
                "pe_ratio":     _raw(sd, "trailingPE") or _raw(ks, "trailingPE"),
                "mktcap_cr":    round(mktcap_raw / _CRORE, 2) if mktcap_raw else None,
                "div_yld_pct":  round((_raw(sd, "dividendYield") or 0) * 100, 4) or None,
                "np_qtr_cr":    round(np_qtr_raw / _CRORE, 2) if np_qtr_raw else None,
                "qtr_pft_var":  _qtr_var(np_qtr_raw, np_qtr_prev),
                "sales_qtr_cr": round(rev_qtr_raw / _CRORE, 2) if rev_qtr_raw else None,
                "qtr_sal_var":  _qtr_var(rev_qtr_raw, rev_qtr_prev),
                "roce_pct":     roce_pct,
                # Extra columns for detail view / fundamentals table
                "market_cap":       mktcap_raw,
                "trailing_pe":      _raw(sd, "trailingPE") or _raw(ks, "trailingPE"),
                "forward_pe":       _raw(sd, "forwardPE") or _raw(ks, "forwardPE"),
                "price_to_book":    _raw(sd, "priceToBook") or _raw(ks, "priceToBook"),
                "enterprise_value": _raw(ks, "enterpriseValue"),
                "ev_to_revenue":    _raw(ks, "enterpriseToRevenue"),
                "ev_to_ebitda":     _raw(ks, "enterpriseToEbitda"),
                "total_revenue":    total_rev,
                "revenue_growth":   _raw(fd, "revenueGrowth"),
                "gross_margins":    gross_margin,
                "operating_margins": op_margin,
                "profit_margins":   _raw(fd, "profitMargins"),
                "return_on_equity": roe,
                "return_on_assets": roa,
                "debt_to_equity":   debt_eq,
                "current_ratio":    _raw(fd, "currentRatio"),
                "book_value":       _raw(ks, "bookValue"),
                "dividend_yield":   _raw(sd, "dividendYield"),
                "payout_ratio":     _raw(sd, "payoutRatio"),
                "avg_volume":       _raw(sd, "averageVolume"),
                "shares_outstanding": _raw(ks, "sharesOutstanding"),
                "insider_hold_pct": _raw(ks, "heldPercentInsiders"),
                "inst_hold_pct":    _raw(ks, "heldPercentInstitutions"),
                "analyst_target_mean": _raw(fd, "targetMeanPrice"),
                "analyst_target_high": _raw(fd, "targetHighPrice"),
                "analyst_target_low":  _raw(fd, "targetLowPrice"),
                "analyst_recommendation": fd.get("recommendationKey"),
                "analyst_count":    _raw(fd, "numberOfAnalystOpinions"),
            }

        except requests.exceptions.Timeout:
            logger.warning("Timeout on fundamentals", ticker=ticker, attempt=attempt + 1)
            time.sleep(5 * (attempt + 1))
        except Exception as exc:
            logger.error("Fundamentals fetch error", ticker=ticker, error=str(exc))
            if attempt < 2:
                time.sleep(3)

    return None
