"""EQS valuation (page review 5 Nov 2026, D-UI: M07, m076, m077, m078).

The grid's CMP used to be the `stock_metrics` enrichment snapshot's price under a "CLOSE" chip (TCS ₹2,350 vs the
₹2,495.70 close; median gap 15.8 %), P/E and market cap inherited it, the quarter disagreed with FUND / COMP, the
DSP Silver ETF (SILVERADD) carried a ₹253.44 "price" on a ₹17.90 close, 'LARGE' meant NIFTY 500 membership and four
placeholder rows (DUMMYVEDL1–4) sat in the list. Each rule has a negative control (the old behaviour fails it).
"""
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import stocks  # noqa: E402
from routers.stocks import REBASE_BAND, assign_cap_rank, eqs_valuation, is_placeholder  # noqa: E402

TCS_SNAP = {"cmp": 2350.0, "pe_ratio": 16.5, "mktcap_cr": 850251.0, "div_yld_pct": 2.08, "np_qtr_cr": 12000.0,
            "qtr_pft_var": 4.0, "sales_qtr_cr": 65000.0, "qtr_sal_var": 1.3, "roce_pct": 64.6}
TCS_FIN = {"symbol": "TCS", "pe": 17.5, "mcap": 9034434000000.0, "pat": 139340000000.0, "revenue": 731880000000.0,
           "pat_yoy": 14.9, "revenue_yoy": 11.2, "period_end": "2026-09-30", "pat_yoy_turn": None}


def _old_display_price(row: dict) -> float:
    """The pre-fix grid: `displayPrice = cmp ?? latest_price` with cmp = the snapshot price."""
    return row["cmp"] if row.get("cmp") is not None else row["latest_price"]


# ── M07: CMP is the stored NSE close, never the snapshot ─────────────────────────────────────────────────────────

def test_cmp_is_the_nse_close_not_the_snapshot():
    v = eqs_valuation(2495.70, "2026-11-05", TCS_SNAP, TCS_FIN)
    assert v["cmp"] == 2495.70 and v["cmp_basis"] == "nse_close" and v["cmp_date"] == "2026-11-05"
    assert v["snapshot_cmp"] == 2350.0                                    # kept for audit, never displayed as CMP
    # negative control: the old row showed the snapshot price under the CLOSE chip
    assert _old_display_price({"cmp": TCS_SNAP["cmp"], "latest_price": 2495.70}) == 2350.0 != v["cmp"]


def test_pe_and_mcap_come_from_the_filings_at_the_close():
    v = eqs_valuation(2495.70, "2026-11-05", TCS_SNAP, TCS_FIN)
    assert v["valuation_basis"] == "filings"
    assert v["pe_ratio"] == 17.5 and v["mktcap_cr"] == 903443.4                     # FUND / COMP: 9,03,443 cr
    assert v["np_qtr_cr"] == 13934.0 and v["qtr_pft_var"] == 14.9 and v["quarter_basis"] == "filings"
    assert v["sales_qtr_cr"] == 73188.0 and v["qtr_sal_var"] == 11.2 and v["qtr_period"] == "2026-09-30"
    # negative control (m076): the snapshot said NP ▲4.0 %, market cap 8,50,251 cr
    assert TCS_SNAP["qtr_pft_var"] != v["qtr_pft_var"] and TCS_SNAP["mktcap_cr"] != v["mktcap_cr"]


def test_snapshot_rebased_only_inside_the_band():
    snap = {"cmp": 100.0, "pe_ratio": 20.0, "mktcap_cr": 1000.0, "div_yld_pct": 2.0}
    v = eqs_valuation(125.0, "2026-11-05", snap, None)                     # ×1.25: a real move, rebase it
    assert v["valuation_basis"] == "snapshot_rebased" and v["pe_ratio"] == 25.0 and v["mktcap_cr"] == 1250.0
    assert v["div_yld_pct"] == 1.6 and v["div_basis"] == "snapshot_rebased"
    lo, hi = REBASE_BAND
    out = eqs_valuation(100.0 * (lo - 0.01), "2026-11-05", snap, None)        # just outside: withheld, not guessed
    assert out["valuation_basis"] == "withheld" and out["pe_ratio"] is None and out["mktcap_cr"] is None
    assert out["div_yld_pct"] is None and out["div_basis"] == "withheld"
    edge = eqs_valuation(100.0 * hi, "2026-11-05", snap, None)                # the band is inclusive
    assert edge["valuation_basis"] == "snapshot_rebased"


def test_a_split_sized_gap_withholds_the_valuation():
    # ZFCVINDIA-like: snapshot ₹14,884 on a ₹2,309 close (×0.155): rebasing would print a P/E 6.5× too low
    snap = {"cmp": 14884.0, "pe_ratio": 60.0, "mktcap_cr": 28000.0}
    v = eqs_valuation(2309.10, "2026-11-05", snap, None)
    assert v["valuation_basis"] == "withheld" and v["pe_ratio"] is None and v["cmp"] == 2309.10
    # negative control: a naive rebase (the rejected design) gives a meaningless P/E
    assert round(60.0 * 2309.10 / 14884.0, 1) == 9.3


def test_an_etf_carries_no_company_valuation():
    snap = {"cmp": 253.44, "pe_ratio": None, "mktcap_cr": 120.0, "div_yld_pct": 0.0, "roce_pct": 3.0}
    v = eqs_valuation(17.90, "2026-11-05", snap, None, etf_underlying="DSP Silver ETF")      # SILVERADD
    assert v["instrument"] == "ETF" and v["cmp"] == 17.90 and v["valuation_basis"] == "etf"
    assert all(v[k] is None for k in ("pe_ratio", "mktcap_cr", "div_yld_pct", "np_qtr_cr", "roce_pct"))
    # negative control: without the ETF list the snapshot's ₹253.44 was the "CMP"
    assert _old_display_price({"cmp": 253.44, "latest_price": 17.90}) == 253.44


def test_a_loss_maker_has_no_pe():
    v = eqs_valuation(50.0, "2026-11-05", {}, {"pe": -12.0, "mcap": 5e9, "pat": -1e8, "revenue": 2e9})
    assert v["pe_ratio"] is None and v["mktcap_cr"] == 500.0


# ── m077: SEBI-style size buckets by rank; m078: placeholders out ────────────────────────────────────────────────

def test_cap_rank_buckets():
    rows = [{"ticker": f"S{i}", "mktcap_cr": 1e6 - i, "instrument": "EQ"} for i in range(300)]
    rows.append({"ticker": "ETF1", "mktcap_cr": 9e9, "instrument": "ETF"})          # an ETF never takes a rank
    rows.append({"ticker": "NOCAP", "mktcap_cr": None, "instrument": "EQ"})
    assign_cap_rank(rows)
    by = {r["ticker"]: r for r in rows}
    assert by["S0"]["cap_rank"] == 1 and by["S0"]["cap_sebi"] == "Large"
    assert by["S99"]["cap_sebi"] == "Large" and by["S100"]["cap_sebi"] == "Mid"
    assert by["S249"]["cap_sebi"] == "Mid" and by["S250"]["cap_sebi"] == "Small"
    assert by["ETF1"]["cap_rank"] is None and by["NOCAP"]["cap_sebi"] is None
    # negative control: the CSV's 'Large Cap' was NIFTY 500 membership (AAVAS ₹11,046 cr read 'LARGE')
    assert by["S260"]["cap_sebi"] != "Large"


def test_placeholders():
    assert is_placeholder("DUMMYVEDL1") and is_placeholder("DUMMYVEDL4")
    assert not is_placeholder("VEDL") and not is_placeholder("TCS")     # negative control: real symbols stay


# ── the route: CMP, valuation and rank wired through /api/stocks/list ─────────────────────────────────────────────

class _FakeAsyncClient:
    responses: dict[str, httpx.Response] = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        raise AssertionError(f"unexpected upstream GET {url}")


def _resp(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request("GET", "http://localhost:8001/x"))


def test_list_route(monkeypatch):
    meta_rows = [
        {"ticker": "TCS", "latest_price": 2495.70, "price_date": "2026-11-05", "total_rows": 4000, "first_date": "2010-01-04",
         "latest_date": "2026-11-05", "years_of_data": 16, "data_density_pct": 98.0, "days_since_update": 1,
         "sessions_behind": 0, **TCS_SNAP},
        {"ticker": "SILVERADD", "latest_price": 17.90, "price_date": "2026-11-05", "total_rows": 800, "first_date": "2022-08-25",
         "latest_date": "2026-11-05", "years_of_data": 4, "data_density_pct": 98.0, "days_since_update": 1,
         "sessions_behind": 0, "cmp": 253.44, "pe_ratio": None, "mktcap_cr": 120.0},
    ]
    universe = {"TCS": {"company_name": "Tata Consultancy Services", "sector_name": "IT", "isin": None, "cap_category": "Large Cap",
                        "index_name": "NIFTY500", "nifty_bucket": "500", "midcap_bucket": None},
                "SILVERADD": {"company_name": None, "sector_name": "Unknown", "isin": None, "cap_category": "Small Cap",
                              "index_name": None, "nifty_bucket": None, "midcap_bucket": None},
                "DUMMYVEDL1": {"company_name": "Dummy Vedanta Ltd. 1", "sector_name": None, "isin": None, "cap_category": "Large Cap",
                               "index_name": "NIFTY500", "nifty_bucket": "500", "midcap_bucket": None}}
    _FakeAsyncClient.responses = {"/db/ohlcv-meta": _resp({"count": 2, "data": meta_rows}),
                                  "/db/financials-universe": _resp({"rows": [TCS_FIN], "count": 1})}
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(stocks, "_load_universe_metadata", lambda: universe)
    monkeypatch.setattr(stocks, "_load_etf_symbols", lambda: {"SILVERADD": "DSP Silver ETF"})
    stocks._FIN_CACHE.update(at=0.0, map=None)
    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/stocks")
    body = TestClient(app).get("/api/stocks/list?limit=50").json()
    by = {s["ticker"]: s for s in body["stocks"]}
    assert "DUMMYVEDL1" not in by and body["total"] == 2
    assert by["TCS"]["cmp"] == 2495.70 and by["TCS"]["pe_ratio"] == 17.5 and by["TCS"]["cap_sebi"] == "Large"
    assert by["SILVERADD"]["instrument"] == "ETF" and by["SILVERADD"]["cmp"] == 17.90
    assert by["SILVERADD"]["pe_ratio"] is None and by["SILVERADD"]["sector_name"] == "ETF · DSP Silver ETF"
    # a search never re-ranks the universe: TCS keeps rank 1 when the list is filtered to it
    stocks._FIN_CACHE.update(at=0.0, map=None)
    one = TestClient(app).get("/api/stocks/list?search=tcs").json()["stocks"]
    assert [s["ticker"] for s in one] == ["TCS"] and one[0]["cap_rank"] == 1
    stocks._FIN_CACHE.update(at=0.0, map=None)


def test_list_route_survives_a_missing_financials_route(monkeypatch):
    meta_rows = [{"ticker": "TCS", "latest_price": 2495.70, "price_date": "2026-11-05", "total_rows": 4000,
                  "latest_date": "2026-11-05", "data_density_pct": 98.0, "days_since_update": 1, "sessions_behind": 0, **TCS_SNAP}]
    _FakeAsyncClient.responses = {
        "/db/ohlcv-meta": _resp({"count": 1, "data": meta_rows}),
        "/db/financials-universe": httpx.Response(404, json={"detail": "no"}, request=httpx.Request("GET", "http://x")),
    }
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(stocks, "_load_universe_metadata", lambda: {"TCS": {"company_name": "TCS", "cap_category": "Large Cap"}})
    monkeypatch.setattr(stocks, "_load_etf_symbols", lambda: {})
    stocks._FIN_CACHE.update(at=0.0, map=None)
    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/stocks")
    row = TestClient(app).get("/api/stocks/list").json()["stocks"][0]
    # ×1.062 is inside the band: the snapshot is rebased to the close and says so
    assert row["cmp"] == 2495.70 and row["valuation_basis"] == "snapshot_rebased"
    assert row["pe_ratio"] == round(16.5 * 2495.70 / 2350.0, 2)
    stocks._FIN_CACHE.update(at=0.0, map=None)
