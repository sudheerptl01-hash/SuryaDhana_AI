"""OSTR — options strategy analyzer (W3) + real SPAN margin (Terminal v2 PLAN 1.3, B3). PRICES only; never places orders.

POST /api/options/strategy/analyze: up to 4 legs (buy/sell · CE/PE/FUT · strike · lots), seeded by the UI from the
cached EOD chain (GET /api/market/option-chain/{symbol}) — no broker calls, so it works at any hour regardless of
the ICICI session. All math lives in services/ui-api/options_math.py (pure, unit-tested): Black-76 on the forward
(r = 6.5% default), exact piecewise-linear breakevens, bounded/unbounded max P&L, ₹/day theta, and margin + NSE-cost
figures that are always labelled ESTIMATE.

POST /api/options/margin (PLAN 1.3 "Real SPAN margin on OSTR"): the fallback chain, in order —
  1. BREEZE          `breeze.margin_calculator(legs, "NFO")` when the ICICI session is live, through the Breeze budget
                     ledger (shared/breeze_budget.py; refused past the cap → next source);
  2. NSE_SPAN_FILE   the NSE/NCL SPAN risk-parameter file (`nsearchives.nseindia.com/archives/nsccl/span/nsccl.YYYYMMDD.s.zip`,
                     EOD ≈ 17:02 IST; no scheduled job fetches it yet — a file placed in data/nse_archive/span/ (SPAN_ARCHIVE_DIR) is parsed here: the 16-scenario
                     risk arrays per contract → scanning risk, the intra-commodity (calendar) spread charge, the short
                     option minimum; exposure (non-SPAN) margin is NSE's published percentage, labelled as such;
  3. HEURISTIC       options_math.margin_estimate (12 % of notional per short leg + premium) — kept as the last resort
                     WITH its measured error printed: 4.8× over Breeze SPAN on the NIFTY 09-Nov-2026 iron condor
                     (₹3.9 L vs ₹81,497.07; R-OPTIONS §3.3).
The ticket shows `span_margin_required`, `non_span_margin_required` and the source chip BREEZE / NSE SPAN FILE / HEURISTIC.
Badge `arithmetic`; `paper_only: true`; nothing here routes an order.

Event-loop purity: the analyzer is sync `def` (threadpool, microseconds of arithmetic); the margin route is async and
runs the Breeze call and the file parse on worker threads.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # services/ui-api
for _p in (Path(__file__).resolve().parents[3],):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from errors import fail                                        # noqa: E402
import options_math as om                                      # noqa: E402

from shared.breeze_budget import BudgetExceeded, ledger        # noqa: E402

router = APIRouter()

MAX_LEGS = 4
IST = ZoneInfo("Asia/Kolkata")
BADGE_ARITH, BADGE_HEURISTIC = "arithmetic", "heuristic"
HEURISTIC_ERROR_FACTOR = 4.8          # measured: ₹3.9 L heuristic vs ₹81,497.07 Breeze SPAN, NIFTY 09-Nov-2026 condor (R-OPTIONS §3.3)
HEURISTIC_EVIDENCE = ("measured 4.8× too high vs Breeze SPAN on the NIFTY 09-Nov-2026 iron condor (₹3.9 L vs ₹81,497.07; "
                      "R-OPTIONS §3.3) — a trader sizing from this number is under-levered by that factor")
SPAN_SCENARIOS = 16
INDEX_UNDERLYINGS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})
EXPOSURE_PCT_INDEX, EXPOSURE_PCT_STOCK = 2.0, 3.5   # NSE exposure (non-SPAN) margin on short options / futures notional: a published rule, not the file
BREEZE_CALLER = "ui-api.margin"
SPAN_DIR_ENV = "SPAN_ARCHIVE_DIR"
SPAN_FILE_RE = re.compile(r"^nsccl\.(\d{8})\.s\.zip$")
_SPAN_PARSE_LOCK = threading.Lock()
_SPAN_CACHE: dict[tuple[str, str], Any] = {}        # (file path, pfCode) → SpanProduct (one parse per product per file)


class LegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT"]
    strike: float | None = Field(None, gt=0)
    premium: float = Field(..., ge=0, description="option premium / futures entry price, ₹ per unit")
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000, description="from the chain payload — never hardcoded")
    iv: float | None = Field(None, gt=0, le=500, description="percent, e.g. 12.5")
    days: float | None = Field(None, ge=0, le=2000, description="this leg's days to expiry")


class AnalyzeIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    forward: float = Field(..., gt=0, description="chain forward (put-call parity) or future/spot")
    days_to_expiry: float = Field(..., ge=0, le=2000)
    default_iv: float = Field(..., gt=0, le=500, description="fallback IV %, usually the chain's ATM IV")
    r: float = Field(0.065, ge=0, le=0.25)
    legs: list[LegIn] = Field(..., min_length=1, max_length=MAX_LEGS)
    fut_margin_pct: float | None = Field(None, gt=0, le=100, description="margin heuristic override")
    is_index: bool = True
    brokerage_per_order: float = Field(20.0, ge=0, le=500)


@router.post("/strategy/analyze")
def analyze(body: AnalyzeIn) -> dict:
    """Payoff at expiry + today, exact breakevens, max P&L, Greeks, margin & cost ESTIMATES."""
    try:
        legs = [om.Leg(side=l.side, kind=l.kind, strike=l.strike, premium=l.premium,
                       lots=l.lots, lot_size=l.lot_size, iv=l.iv, days=l.days)
                for l in body.legs]
    except ValueError as exc:
        fail(400, "invalid", str(exc), "check each leg's strike, lots and premium")

    days = body.days_to_expiry
    iv = body.default_iv
    option_legs = [l for l in legs if l.kind != "FUT"]
    if any(l.iv is None for l in option_legs) and iv <= 0:
        fail(400, "invalid", "no IV available", "set iv per leg or default_iv (chain ATM IV)")

    profit, loss = om.max_profit_loss(legs)
    bes = om.breakevens_any(legs, days, iv, body.r)
    grid = om.payoff_grid(legs, body.forward, days, iv, body.r)
    per_leg = [om.leg_greeks(l, body.forward, days, iv, body.r) for l in legs]
    net = om.net_greeks(legs, body.forward, days, iv, body.r)
    fut_pct = body.fut_margin_pct or (om.FUT_MARGIN_PCT_INDEX if body.is_index
                                      else om.FUT_MARGIN_PCT_STOCK)
    margin = om.margin_estimate(legs, body.forward, fut_pct, loss)
    cash = om.entry_cashflow(legs)

    return {
        "symbol": body.symbol.upper(),
        "forward": body.forward,
        "days_to_expiry": days,
        "r": body.r,
        "single_expiry": om.is_single_expiry(legs, days),
        "entry_cashflow": round(cash, 2),               # + credit · − debit, option premiums only
        "net_label": "CREDIT" if cash > 0 else "DEBIT" if cash < 0 else "FLAT",
        "breakevens": [round(b, 2) for b in bes],
        "max_profit": {"value": profit.value, "unbounded": profit.unbounded, "at": profit.at},
        "max_loss": {"value": loss.value, "unbounded": loss.unbounded, "at": loss.at},
        "greeks": {
            "per_leg": [{k: (round(v, 6) if v is not None else None) for k, v in p.items()}
                        for p in per_leg],
            "net": {k: round(v, 6) for k, v in net.items()},
            "note": "Black-76 on the forward · delta = futures-equivalent N(d1) · theta ₹/day · "
                    "vega ₹/vol-pt · rho ₹ per +1% rate · futures legs: delta only (carry ignored)",
        },
        "payoff": grid,
        "margin": {
            "estimate": True,
            "total": margin.total,
            "per_leg": margin.per_leg,
            "premium_outflow": margin.premium_outflow,
            "defined_risk_floor": margin.defined_risk_floor,
            "fut_margin_pct": fut_pct,
            "note": margin.note,
            "error_factor_measured": HEURISTIC_ERROR_FACTOR,
            "real_margin": "POST /api/options/margin (Breeze SPAN when live → NSE SPAN file → this heuristic)",
        },
        "costs": om.costs_estimate(legs, body.brokerage_per_order),
        "paper_only": True,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# POST /margin — Breeze → NSE SPAN file → heuristic (PLAN 1.3)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class MarginLegIn(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["CE", "PE", "FUT"]
    strike: float | None = Field(None, gt=0)
    expiry: date = Field(..., description="contract expiry, YYYY-MM-DD (read from the chain / the file, never assumed)")
    premium: float = Field(0.0, ge=0, description="option premium / futures price, ₹ per unit (the heuristic's input)")
    lots: int = Field(1, ge=1, le=10_000)
    lot_size: int = Field(..., ge=1, le=100_000, description="from the chain payload — never hardcoded")


class MarginIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30, description="NSE underlying (NIFTY, RELIANCE, …)")
    legs: list[MarginLegIn] = Field(..., min_length=1, max_length=MAX_LEGS)
    exchange_code: Literal["NFO"] = "NFO"
    forward: float | None = Field(None, gt=0, description="for the heuristic and the exposure estimate (default: the file's settlement price)")
    stock_code: str | None = Field(None, max_length=20, description="ICICI stock code when it differs from the NSE symbol (INFTEC for INFY)")
    sources: str = Field("breeze,span_file,heuristic", max_length=60, description="comma list to restrict the fallback chain (tests)")


@dataclass
class RiskArray:
    kind: str                  # "C" | "P" | "F"
    expiry: str                # YYYYMMDD
    strike: float
    price: float               # settlement price per unit
    delta: float               # the contract's delta
    composite_delta: float     # the <d> inside <ra>
    losses: list[float]        # 16 scenario losses for ONE LONG UNIT (positive = loss), ₹


@dataclass
class SpanProduct:
    pf_code: str
    file_date: str
    settlement: bool
    arrays: dict[tuple[str, str, float], RiskArray] = field(default_factory=dict)   # (kind, expiry, strike)
    calendar_spreads: list[dict[str, Any]] = field(default_factory=list)            # {rate, legs:[(expiry, side)]}
    som_rate: float = 0.0                                                            # short option minimum per unit
    scan_ranges: dict[str, float] = field(default_factory=dict)                      # expiry → price scan range


def _tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", text)
    return m.group(1) if m else None


def _block(text: str, tag: str, locator: str) -> str | None:
    """The first ``<tag> … </tag>`` block whose head contains ``locator`` (e.g. ``<pfCode>NIFTY</pfCode>``)."""
    start = 0
    while True:
        i = text.find(f"<{tag}>", start)
        if i < 0:
            return None
        j = text.find(f"</{tag}>", i)
        if j < 0:
            return None
        head = text[i:i + 400]
        if locator in head:
            return text[i:j + len(tag) + 3]
        start = j


_OPT_RE = re.compile(r"<opt>(.*?)</opt>", re.S)
_FUT_RE = re.compile(r"<fut>(.*?)</fut>", re.S)
_SERIES_RE = re.compile(r"<series>(.*?)</series>", re.S)
_A_RE = re.compile(r"<a>\s*([-\d.]+)\s*</a>")
_DSPREAD_RE = re.compile(r"<dSpread>(.*?)</dSpread>", re.S)
_PLEG_RE = re.compile(r"<pLeg>(.*?)</pLeg>", re.S)


def _risk_array(body: str, kind: str, expiry: str, strike: float) -> RiskArray | None:
    ra = re.search(r"<ra>(.*?)</ra>", body, re.S)
    if not ra:
        return None
    losses = [float(x) for x in _A_RE.findall(ra.group(1))]
    if len(losses) != SPAN_SCENARIOS:
        return None
    price = float(_tag(body, "p") or 0.0)
    delta = float(_tag(body, "d") or (1.0 if kind == "F" else 0.0))
    cd = _tag(ra.group(1), "d")
    return RiskArray(kind, expiry, strike, price, delta, float(cd) if cd else delta, losses)


def parse_span_product(text: str, pf_code: str) -> SpanProduct | None:
    """Parse one underlying out of an NSE/NCL SPAN file (CME SPAN 'expanded XML' format 4.00): the futures block
    (`futPf`), the options block (`oopPf`, one `series` per expiry, one `opt` per strike × C/P, each with its 16-scenario
    risk array in ₹ per unit for a long position — positive = loss) and the combined-commodity block (`ccDef`: the
    calendar-spread charges `dSpread` and the short-option-minimum tiers). Verified on nsccl.20261104.s.spn."""
    file_date = _tag(text[:4000], "date") or ""
    settlement = (_tag(text[:4000], "isSetl") or "0").strip() == "1"
    out = SpanProduct(pf_code=pf_code, file_date=file_date, settlement=settlement)
    found = False
    fut_pf = _block(text, "futPf", f"<pfCode>{pf_code}</pfCode>")
    if fut_pf:
        for m in _FUT_RE.finditer(fut_pf):
            body = m.group(1)
            exp = _tag(body, "pe") or ""
            ra = _risk_array(body, "F", exp, 0.0)
            if ra:
                out.arrays[("F", exp, 0.0)] = ra
                found = True
            ps = _tag(body, "priceScan")
            if ps:
                out.scan_ranges.setdefault(exp, float(ps))
    oop_pf = _block(text, "oopPf", f"<pfCode>{pf_code}</pfCode>")
    if oop_pf:
        for sm in _SERIES_RE.finditer(oop_pf):
            series = sm.group(1)
            exp = _tag(series, "pe") or ""
            ps = _tag(series, "priceScan")
            if ps:
                out.scan_ranges[exp] = float(ps)
            for om_ in _OPT_RE.finditer(series):
                body = om_.group(1)
                kind = (_tag(body, "o") or "").upper()
                strike = float(_tag(body, "k") or 0.0)
                ra = _risk_array(body, kind, exp, strike)
                if ra and kind in ("C", "P"):
                    out.arrays[(kind, exp, strike)] = ra
                    found = True
    cc = _block(text, "ccDef", f"<cc>{pf_code}</cc>")
    if cc:
        som = re.search(r"<somTiers>.*?<val>\s*([-\d.]+)\s*</val>", cc, re.S)
        if som:
            out.som_rate = float(som.group(1))
        for dm in _DSPREAD_RE.finditer(cc):
            d = dm.group(1)
            rate = _tag(d, "val")
            legs = [((_tag(pl.group(1), "pe") or ""), (_tag(pl.group(1), "rs") or "A").upper()) for pl in _PLEG_RE.finditer(d)]
            if rate and len(legs) >= 2:
                out.calendar_spreads.append({"rate": float(rate), "method": _tag(d, "chargeMeth") or "F", "legs": legs})
    return out if found else None


def span_margin(product: SpanProduct, legs: list[MarginLegIn]) -> dict[str, Any]:
    """SPAN initial margin for the book from the file's arrays: scanning risk (max over the 16 scenarios of the net
    loss, long = +array, short = −array, × units), + the calendar-spread charge (flat ₹ per spread formed between a net
    long delta in one expiry and a net short delta in another), with the short-option-minimum floor. No
    inter-commodity credit (none is defined for NSE's single-underlying combined commodities)."""
    totals = [0.0] * SPAN_SCENARIOS
    missing: list[str] = []
    net_delta: dict[str, float] = {}
    short_units = 0
    settle_value = 0.0
    for leg in legs:
        exp = leg.expiry.strftime("%Y%m%d")
        kind = {"CE": "C", "PE": "P", "FUT": "F"}[leg.kind]
        key = (kind, exp, float(leg.strike or 0.0))
        ra = product.arrays.get(key)
        if ra is None:
            missing.append(f"{leg.kind} {leg.strike or ''} {leg.expiry.isoformat()}".strip())
            continue
        units = leg.lots * leg.lot_size
        sign = 1.0 if leg.side == "buy" else -1.0
        for s in range(SPAN_SCENARIOS):
            totals[s] += sign * ra.losses[s] * units
        net_delta[exp] = net_delta.get(exp, 0.0) + sign * ra.composite_delta * units
        if leg.side == "sell" and kind in ("C", "P"):
            short_units += units
        settle_value += sign * ra.price * units
    if missing:
        return {"ok": False, "missing": missing}
    worst = max(range(SPAN_SCENARIOS), key=lambda s: totals[s])
    scanning = max(0.0, totals[worst])
    spread_charge = 0.0
    spreads_formed: list[dict[str, Any]] = []
    longs = {e: d for e, d in net_delta.items() if d > 0}
    shorts = {e: -d for e, d in net_delta.items() if d < 0}
    for sp in product.calendar_spreads:
        exps = [e for e, _ in sp["legs"]]
        if len(exps) < 2:
            continue
        a, b = exps[0], exps[1]
        pairs = ((a, b), (b, a))
        for lo, sh in pairs:
            n = min(longs.get(lo, 0.0), shorts.get(sh, 0.0))
            if n > 0:
                longs[lo] -= n
                shorts[sh] -= n
                spread_charge += sp["rate"] * n
                spreads_formed.append({"long": lo, "short": sh, "spreads": round(n, 2), "charge": round(sp["rate"] * n, 2)})
    som = product.som_rate * short_units
    span = max(scanning + spread_charge, som)
    return {"ok": True, "scanning_risk": round(scanning, 2), "worst_scenario": worst + 1, "scenario_losses": [round(t, 2) for t in totals],
            "calendar_spread_charge": round(spread_charge, 2), "spreads": spreads_formed, "short_option_minimum": round(som, 2),
            "span_margin": round(span, 2), "net_delta_by_expiry": {e: round(d, 2) for e, d in net_delta.items()},
            "net_option_value": round(settle_value, 2), "file_date": product.file_date, "settlement_file": product.settlement}


def exposure_estimate(legs: list[MarginLegIn], symbol: str, forward: float | None, product: SpanProduct | None) -> dict[str, Any]:
    """NSE's exposure (non-SPAN) margin: a published percentage of the notional of short options and futures (index 2 %,
    stocks 3.5 % or 1.5 σ, whichever is higher — the σ leg is NOT computed here). Labelled heuristic: it is a rule, not
    the file."""
    pct = EXPOSURE_PCT_INDEX if symbol in INDEX_UNDERLYINGS else EXPOSURE_PCT_STOCK
    notional = 0.0
    ref = forward
    if ref is None and product is not None:
        futs = sorted((k for k in product.arrays if k[0] == "F"), key=lambda k: k[1])
        ref = product.arrays[futs[0]].price if futs else None
    for leg in legs:
        if leg.kind == "FUT" or leg.side == "sell":
            notional += (ref or 0.0) * leg.lots * leg.lot_size
    return {"pct_of_notional": pct, "reference_price": ref, "value": round(notional * pct / 100, 2) if ref else None,
            "badge": BADGE_HEURISTIC, "note": f"NSE exposure margin rule ({pct} % of short/futures notional); not read from the file"}


def _span_dir() -> Path:
    env = os.environ.get(SPAN_DIR_ENV, "").strip()
    if env:
        return Path(env)
    for root in (Path(__file__).resolve().parents[3] / "data", Path("/app/data")):
        if root.is_dir():
            return root / "nse_archive" / "span"
    return Path("data/nse_archive/span")


def latest_span_file(directory: Path | None = None) -> Path | None:
    d = directory or _span_dir()
    if not d.is_dir():
        return None
    files = sorted((p for p in d.iterdir() if SPAN_FILE_RE.match(p.name)), key=lambda p: p.name)
    return files[-1] if files else None


def load_span_product(path: Path, pf_code: str) -> SpanProduct | None:
    """Read the zip (or a bare .spn/.xml), parse ONE underlying, memoise per (file, underlying)."""
    key = (str(path), pf_code)
    with _SPAN_PARSE_LOCK:
        if key in _SPAN_CACHE:
            return _SPAN_CACHE[key]
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith((".spn", ".xml"))] or z.namelist()
            text = io.TextIOWrapper(z.open(names[0]), encoding="utf-8", errors="ignore").read()
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    product = parse_span_product(text, pf_code)
    with _SPAN_PARSE_LOCK:
        _SPAN_CACHE[key] = product
        while len(_SPAN_CACHE) > 64:
            _SPAN_CACHE.pop(next(iter(_SPAN_CACHE)))
    return product


def breeze_positions(body: MarginIn, stock_code: str) -> list[dict[str, str]]:
    """The SDK's `list_of_positions` rows (the shape ICICI documents; INFY future sample in reports/breeze_catalog)."""
    rows = []
    for leg in body.legs:
        rows.append({
            "strike_price": f"{leg.strike:g}" if leg.kind != "FUT" and leg.strike else "0",
            "quantity": str(leg.lots * leg.lot_size),
            "right": {"CE": "Call", "PE": "Put", "FUT": "Others"}[leg.kind],
            "product": "Options" if leg.kind != "FUT" else "Futures",
            "action": "Buy" if leg.side == "buy" else "Sell",
            "price": f"{leg.premium:g}",
            "expiry_date": leg.expiry.strftime("%d-%b-%Y"),
            "stock_code": stock_code,
        })
    return rows


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_breeze_margin(resp: Any) -> dict[str, Any] | None:
    """`{Success: {span_margin_required, non_span_margin_required, order_value, …}, Status, Error}` → numbers."""
    if not isinstance(resp, dict):
        return None
    ok = resp.get("Success")
    if not isinstance(ok, dict) or resp.get("Error"):
        return None
    span, non_span = _num(ok.get("span_margin_required")), _num(ok.get("non_span_margin_required"))
    if span is None:
        return None
    return {"span_margin_required": span, "non_span_margin_required": non_span or 0.0,
            "order_value": _num(ok.get("order_value")), "trade_margin": _num(ok.get("trade_margin")),
            "legs_echo": len(ok.get("margin_calulation") or [])}


def _breeze_margin_sync(body: MarginIn) -> tuple[dict[str, Any] | None, str]:
    """(parsed, reason) — the Breeze leg: session check, budget ledger, the SDK call on this worker thread."""
    from routers import positions as pos
    breeze, err = pos._get_breeze_client()
    if breeze is None:
        return None, f"no live Breeze session ({err or 'not configured'})"
    code = (body.stock_code or "").strip().upper()
    if not code:
        sym = body.symbol.upper()
        if sym in INDEX_UNDERLYINGS:
            code = sym
        else:
            try:
                rev = {v: k for k, v in pos.isec_to_nse().items()}
                code = rev.get(sym, sym)
            except Exception:  # noqa: BLE001 — the master may be unavailable; try the NSE symbol as the code
                code = sym
    try:
        with ledger().guard(BREEZE_CALLER, "margin_calculator"):
            resp = breeze.margin_calculator(breeze_positions(body, code), body.exchange_code)
    except BudgetExceeded as exc:
        return None, f"Breeze budget: {exc}"
    except Exception as exc:  # noqa: BLE001 — SDK / network errors: fall through to the file
        return None, f"Breeze margin_calculator failed: {type(exc).__name__}: {str(exc)[:80]}"
    parsed = parse_breeze_margin(resp)
    if parsed is None:
        err_txt = str((resp or {}).get("Error") if isinstance(resp, dict) else resp)[:80]
        return None, f"Breeze answered without a margin ({err_txt})"
    return parsed, "ok"


def _span_file_sync(body: MarginIn) -> tuple[dict[str, Any] | None, str, SpanProduct | None]:
    path = latest_span_file()
    if path is None:
        return None, f"no SPAN file under {_span_dir()} (the 20:30 pass fetches nsccl.YYYYMMDD.s.zip)", None
    try:
        product = load_span_product(path, body.symbol.upper())
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        return None, f"SPAN file {path.name} unreadable: {type(exc).__name__}", None
    if product is None:
        return None, f"{body.symbol.upper()} not in SPAN file {path.name}", None
    res = span_margin(product, body.legs)
    if not res["ok"]:
        return None, f"contracts not in SPAN file {path.name}: {', '.join(res['missing'])}", product
    res["file"] = path.name
    return res, "ok", product


def heuristic_margin(body: MarginIn, forward: float | None) -> dict[str, Any]:
    legs = [om.Leg(side=l.side, kind=l.kind, strike=l.strike, premium=l.premium, lots=l.lots, lot_size=l.lot_size)
            for l in body.legs]
    ref = forward or max((l.strike or 0.0) for l in body.legs) or 1.0
    is_index = body.symbol.upper() in INDEX_UNDERLYINGS
    pct = om.FUT_MARGIN_PCT_INDEX if is_index else om.FUT_MARGIN_PCT_STOCK
    _, loss = om.max_profit_loss(legs)
    est = om.margin_estimate(legs, ref, pct, loss)
    return {"total": est.total, "per_leg": est.per_leg, "premium_outflow": est.premium_outflow,
            "defined_risk_floor": est.defined_risk_floor, "fut_margin_pct": pct,
            "error_factor_measured": HEURISTIC_ERROR_FACTOR, "evidence": HEURISTIC_EVIDENCE, "note": est.note}


@router.post("/margin")
async def margin(body: MarginIn) -> dict:
    """Real margin for a book of up to 4 NFO legs: Breeze SPAN when the session is live (through the budget ledger) →
    the NSE SPAN risk-parameter file parsed offline → the 12 % heuristic as the last resort with its measured 4.8× error
    printed. The source chip says which one answered; `attempts` lists why the earlier ones did not."""
    chain = [s.strip().lower() for s in body.sources.split(",") if s.strip()]
    attempts: list[dict[str, Any]] = []
    symbol = body.symbol.upper()
    source, span_req, non_span, order_value, detail = "HEURISTIC", None, None, None, {}
    product: SpanProduct | None = None
    if "breeze" in chain:
        parsed, reason = await asyncio.to_thread(_breeze_margin_sync, body)
        attempts.append({"source": "BREEZE", "ok": parsed is not None, "reason": reason})
        if parsed is not None:
            source, span_req, non_span, order_value, detail = "BREEZE", parsed["span_margin_required"], parsed["non_span_margin_required"], parsed["order_value"], parsed
    if source == "HEURISTIC" and "span_file" in chain:
        res, reason, product = await asyncio.to_thread(_span_file_sync, body)
        attempts.append({"source": "NSE_SPAN_FILE", "ok": res is not None, "reason": reason})
        if res is not None:
            source, span_req, detail = "NSE_SPAN_FILE", res["span_margin"], res
            expo = exposure_estimate(body.legs, symbol, body.forward, product)
            non_span = expo["value"]
            detail = {**res, "exposure": expo}
    heuristic = heuristic_margin(body, body.forward)
    if source == "HEURISTIC":
        attempts.append({"source": "HEURISTIC", "ok": True, "reason": "last resort — " + HEURISTIC_EVIDENCE})
        span_req, non_span = heuristic["total"], 0.0
    total = (span_req or 0.0) + (non_span or 0.0)
    chip = {"BREEZE": "BREEZE", "NSE_SPAN_FILE": "NSE SPAN FILE", "HEURISTIC": "HEURISTIC"}[source]
    return {
        "symbol": symbol, "exchange_code": body.exchange_code, "legs": len(body.legs),
        "source": source, "source_chip": chip,
        "span_margin_required": span_req, "non_span_margin_required": non_span, "total_margin": round(total, 2),
        "order_value": order_value,
        "as_of": (detail.get("file_date") and f"{detail['file_date'][:4]}-{detail['file_date'][4:6]}-{detail['file_date'][6:8]}")
        if source == "NSE_SPAN_FILE" else datetime.now(IST).isoformat(timespec="seconds"),
        "detail": detail, "heuristic": heuristic, "attempts": attempts,
        # per-field badges (check:B3-API minor): on the NSE SPAN FILE answer the exposure leg is NSE's published rule
        # (heuristic), so the total is only as strong as its weaker part; the UI prints total_margin OR heuristic.total, never both
        "badges": {"span_margin_required": BADGE_ARITH if source != "HEURISTIC" else BADGE_HEURISTIC,
                   "non_span_margin_required": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC,
                   "total_margin": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC},
        "badge": BADGE_ARITH if source == "BREEZE" else BADGE_HEURISTIC,
        "note": {"BREEZE": "ICICI's margin calculator (exchange SPAN + exposure as ICICI applies them); 0.3 s; one Breeze call through the budget ledger",
                 "NSE_SPAN_FILE": "scanning risk + calendar-spread charge with the short-option-minimum floor from NCL's EOD risk-parameter file; "
                                  "exposure margin by NSE's published rule (labelled heuristic); intraday files are not fetched",
                 "HEURISTIC": HEURISTIC_EVIDENCE}[source],
        "paper_only": True,
    }

