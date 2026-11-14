"""The PAPER MCX futures book behind the MCXG ticket (FINAL ROUND R5-FUTBOOK): book → daily MTM → close/settle.

Routes (mounted at ``/api/mcx/book``):
  GET  ""        the book: open positions with their latest stored mark, unrealised and day-MTM arithmetic; closed
                 positions with their recorded realised money; totals
  POST ""        "BOOK PAPER" from the MCXG ticket: write one futures position (PAPER ONLY, explicit action — the
                 ticket's quote path still records nothing)
  POST /mark     append today's marks from the STORED settlement reads (data-service ``/db/gold/mcx/settlement``,
                 ``settlement_source`` labelled: breeze_vwap30 | band_midpoint; ``/db/gold/mcx/daily`` broker bar as the
                 expired-contract fallback) and settle expired contracts at the stored settlement of record
  POST /close    close open positions at their latest stored mark, or at a typed price (labelled 'edited')
  GET  /journal  the append-only action log

PAPER ONLY (binding): no broker client is imported here or in ``fut_book_store``; no order method exists in this module;
the store's ``CHECK (mode = 'paper')`` refuses anything else at the database level and the request models accept
``mode: "paper"`` only. NEVER the MCX website (O-8): every read is data-service's stored gold tables over 127.0.0.1
(ICICI Breeze VWAP30 / band / broker daily bars, each source-labelled). Nothing here feeds the Decision Desk, the S1
shadow, a directional alert or the ticket's price.

Marks (point-in-time): a mark is the latest COMPLETED session's settlement proxy as data-service stores it — the Breeze
last-30-min VWAP (MCX's DSP method) when stored, else the ICICI band midpoint labelled with its REAL session — appended
once per (position, session); a revised value is a new row, never an overwrite. An EXPIRED contract settles at the
stored settlement of record ON its expiry session (VWAP30 of that session, else the band labelled band_midpoint, else
the stored Breeze daily close of that session as a labelled broker-bar fallback), never a later price; until that
session's record is stored it shows ``expired-unsettled`` and cannot be closed. Labels: badge arithmetic only — the
book describes, does not predict.
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # services/ui-api
import fut_book_store as fts                                   # noqa: E402
from errors import fail                                        # noqa: E402
from routers.mcx import contract_specs, spec_costs             # noqa: E402

from shared.http_client import UpstreamError, get_json         # noqa: E402

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
IST = ZoneInfo("Asia/Kolkata")
BADGE_ARITH = "arithmetic"
DESCRIBES = "describes, does not predict"
PAPER_NOTE = ("PAPER ONLY: a paper futures book in ui-api's SQLite; no order API exists on this desk and none is "
              "reachable from here — the ticket above still prices and records nothing")
MARK_NOTE = ("marks are the stored settlement reads (Breeze last-30-min VWAP, MCX's DSP method, else the ICICI band "
             "midpoint labelled with its real session); an expired contract settles at the stored settlement of "
             "record on its expiry session, never a later price")
UNSETTLED = "expired-unsettled"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# request models
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


class FutBookIn(BaseModel):
    contract: str = Field(..., min_length=1, max_length=20)
    expiry: date = Field(..., description="the contract's expiry (from the contract selector, never assumed)")
    side: str = Field(..., pattern="^(buy|sell)$")
    lots: int = Field(..., ge=1, le=1000)
    price: float = Field(..., gt=0, le=10_000_000, description="the paper fill, ₹ in the family's quotation unit")
    price_source: str = Field(..., min_length=1, max_length=200, description="where the fill came from (desk price source / typed)")
    brokerage_per_order: float = Field(20.0, ge=0, le=10_000)
    note: str | None = Field(None, max_length=300)
    mode: str = Field("paper", max_length=10, description="always 'paper' — the book has no live mode")
    context: dict[str, Any] | None = Field(None, description="the ticket as shown at booking — journalled point-in-time")


class FutCloseIn(BaseModel):
    position_ids: list[int] = Field(..., min_length=1, max_length=100)
    prices: dict[int, float] | None = Field(None, description="typed exit prices by position id, > 0 (labelled 'edited')")
    mode: str = Field("paper", max_length=10)


def _paper_only(mode: str) -> None:
    """The book has exactly one mode. Anything else is refused — EXECUTION_LIVE_ALLOWED does not open a live path here."""
    if (mode or "").strip().lower() != "paper":
        fail(422, "invalid", f"mode {mode!r} refused: {PAPER_NOTE}", "the paper futures book only takes mode 'paper'")


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# stored reads (data-service over 127.0.0.1; never the MCX website — O-8)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


async def _settlement_read(family: str, expiry: str, day: str | None = None) -> dict[str, Any] | None:
    """data-service's settlement block for one contract (gold/reads.mcx_settlement): ``settlement`` with its labelled
    ``settlement_source`` / ``settlement_session`` / ``settlement_quality``. None when the read does not answer."""
    params: dict[str, Any] = {"symbol": family, "expiry": expiry}
    if day:
        params["date"] = day
    try:
        body = await get_json(f"{DATA_SVC}/db/gold/mcx/settlement", route="read", params=params)
    except UpstreamError:
        return None
    return body if isinstance(body, dict) else None


async def _daily_close_on(family: str, expiry: str, day: str) -> dict[str, Any] | None:
    """The stored Breeze daily bar's close ON ``day`` for one contract (gold_mcx_daily, O-8 broker bar) — the expired-
    contract fallback when no settlement proxy of that session is stored. None when no bar of that date exists."""
    frm = (date.fromisoformat(day) - timedelta(days=6)).isoformat()
    try:
        body = await get_json(f"{DATA_SVC}/db/gold/mcx/daily", route="read",
                              params={"family": family, "expiry": expiry, "from": frm, "to": day})
    except UpstreamError:
        return None
    for r in reversed((body or {}).get("rows") or []):
        if str(r.get("trade_date"))[:10] == day and r.get("close") is not None:
            return {"price": float(r["close"]), "source": "breeze_daily_close (broker bar, not MCX's official bhavcopy)",
                    "session": day, "quality": str(body.get("quality") or "broker")}
    return None


async def _mark_record(family: str, expiry: str, *, expired: bool) -> dict[str, Any] | None:
    """The mark for one (family, expiry): the settlement proxy with its source labelled. For an EXPIRED contract only a
    record OF the expiry session counts (the settlement of record); the stored broker daily close of that session is the
    labelled fallback. None = nothing stored for the required session."""
    block = await _settlement_read(family, expiry, day=expiry if expired else None)
    if block and block.get("settlement") is not None and block.get("settlement_session"):
        session = str(block["settlement_session"])[:10]
        rec = {"price": float(block["settlement"]), "source": str(block.get("settlement_source") or "unstated"),
               "session": session, "quality": str(block.get("settlement_quality") or "unstated")}
        if not expired:
            return rec
        if session == expiry:
            return rec
    if expired:
        return await _daily_close_on(family, expiry, expiry)
    return None


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# routes
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _today_ist() -> date:
    return datetime.now(IST).date()


def _side_costs(family: str, side: str, price: float, lots: int, brokerage: float) -> float:
    """One side's statutory MCX cost for this fill (shared/mcx_specs rate card via routers.mcx.spec_costs —
    labelled indicative)."""
    return float(spec_costs(family, price, lots, brokerage_per_order=brokerage)[side]["total"])


@router.post("")
async def book_paper(body: FutBookIn) -> dict[str, Any]:
    """BOOK PAPER: write one futures position into the paper book. An explicit action, separate from the ticket's
    quote path (which keeps recording nothing). PAPER ONLY."""
    _paper_only(body.mode)
    fam = body.contract.upper()
    specs_all = contract_specs()
    if fam not in specs_all:
        fail(422, "invalid", f"Unknown MCX contract '{body.contract}'", hint=f"One of {', '.join(specs_all)}")
    if not math.isfinite(body.price):
        fail(422, "invalid", "price must be a finite number")
    today = _today_ist()
    if body.expiry < today:
        fail(422, "invalid", f"{fam} {body.expiry} is already expired — an expired contract cannot be booked")
    spec = specs_all[fam]
    entry_costs = _side_costs(fam, body.side, body.price, body.lots, body.brokerage_per_order)
    store = fts.get_store()
    pos = await asyncio.to_thread(
        store.book, family=fam, expiry=body.expiry.isoformat(), side=body.side, lots=body.lots,
        multiplier=float(spec.multiplier), entry_price=float(body.price), entry_price_source=body.price_source,
        entry_costs=entry_costs, brokerage_per_order=float(body.brokerage_per_order),
        unit=str(spec.as_dict().get("lot") or ""), note=body.note, context=body.context)
    return {"paper": True, "recorded": True, "badge": BADGE_ARITH, "position": pos,
            "entry_costs_inr": round(entry_costs, 2),
            "note": f"{PAPER_NOTE}. Entry-side costs recorded at booking (indicative rate card). {DESCRIBES}."}


@router.post("/mark")
async def mark_book(settle: bool = Query(False, description="also CLOSE expired contracts at their stored "
                                                            "settlement of record; default false")) -> dict[str, Any]:
    """Append today's marks for every open position from the STORED settlement reads (idempotent: the same session at
    the same price is skipped; a revised value is a new row). Reads stored tables only — safe after the close and
    inside freeze windows.

    Marking NEVER closes anything unless ``settle=true`` is asked for (F5, 14 Nov 2026): the page mounts this, and a
    page view must not mutate the owner's track record — booking and closing are explicit actions everywhere else in
    this module. Without the flag an expired contract is reported under ``awaiting_settlement`` with its stored exit
    price, so the UI can offer the one-click SETTLE that does ask for it."""
    store = fts.get_store()
    open_pos = await asyncio.to_thread(store.positions, status="open")
    today = _today_ist().isoformat()
    records: dict[tuple[str, str], dict[str, Any] | None] = {}
    for p in open_pos:
        key = (str(p["family"]), str(p["expiry"])[:10])
        if key not in records:
            records[key] = await _mark_record(key[0], key[1], expired=key[1] < today)
    marks: list[dict[str, Any]] = []
    settles: list[dict[str, Any]] = []
    unsettled: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for p in open_pos:
        key = (str(p["family"]), str(p["expiry"])[:10])
        rec, expired = records[key], key[1] < today
        if rec is None:
            if expired:
                unsettled.append({"position_id": p["id"], "contract": f"{key[0]} {key[1]}", "status": UNSETTLED,
                                  "note": "its expiry session's settlement of record is not stored yet — "
                                          "it cannot be closed at a later price"})
            else:
                unavailable.append(f"{key[0]} {key[1]}: no stored settlement read answered")
            continue
        marks.append({"position_id": p["id"], "as_of": rec["session"], "price": rec["price"],
                      "price_source": rec["source"], "session": rec["session"], "quality": rec["quality"]})
        if expired:
            exit_costs = _side_costs(key[0], "sell" if p["side"] == "buy" else "buy", rec["price"], int(p["lots"]),
                                     float(p["brokerage_per_order"]))
            settles.append({"position_id": p["id"], "exit_price": rec["price"],
                            "exit_price_source": f"MCX settlement of record {rec['session']} · {rec['source']} ({rec['quality']})",
                            "exit_costs": exit_costs})
    written = await asyncio.to_thread(store.add_marks, marks) if marks else 0
    # settle ONLY when explicitly asked (see the docstring): otherwise the expired ones are reported, not closed
    settled = await asyncio.to_thread(store.close, settles, action="settle") if (settles and settle) else []
    awaiting = [] if settle else [{"position_id": x["position_id"], "exit_price": x["exit_price"],
                                   "exit_price_source": x["exit_price_source"],
                                   "note": "expired — POST /mark?settle=true (or the desk's SETTLE action) closes it "
                                           "at this stored settlement of record"} for x in settles]
    return {"paper": True, "badge": BADGE_ARITH, "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "marks_written": written, "settled": settled, "awaiting_settlement": awaiting,
            "expired_unsettled": unsettled, "unavailable": unavailable,
            "note": f"{MARK_NOTE}. {DESCRIBES}."}


@router.post("/close")
async def close_positions(body: FutCloseIn) -> dict[str, Any]:
    """Close open positions at their latest stored mark (its source carried into the fill), or at a typed price
    (labelled 'edited'). An expired contract without its settlement of record stored is refused."""
    _paper_only(body.mode)
    store = fts.get_store()
    today = _today_ist().isoformat()
    fills: list[dict[str, Any]] = []
    for pid in body.position_ids:
        try:
            p = await asyncio.to_thread(store.position, int(pid))
        except fts.BookError as exc:
            fail(404, "not_found", str(exc))
        if p["status"] != "open":
            fail(409, "state", f"position {pid} is already {p['status']}")
        expiry = str(p["expiry"])[:10]
        expired = expiry < today
        typed = (body.prices or {}).get(int(pid))
        if typed is not None:
            if not (math.isfinite(float(typed)) and float(typed) > 0):
                fail(422, "invalid", f"position {pid}: a typed exit price must be a finite number > 0")
            if expired:
                fail(409, "state", f"position {pid} is expired: it settles at the stored settlement of record "
                     "(POST /api/mcx/book/mark), never at a typed price")
            price, src = float(typed), "price you typed (edited)"
        else:
            latest = await asyncio.to_thread(store.latest_marks, [int(pid)], through=expiry if expired else None)
            m = latest.get(int(pid))
            if m is None or (expired and str(m["as_of"])[:10] != expiry):
                detail = (f"position {pid} is expired and its expiry session's settlement of record is not stored "
                          "(expired-unsettled) — it cannot be closed until POST /api/mcx/book/mark finds it" if expired
                          else f"position {pid} has no stored mark — POST /api/mcx/book/mark first, or type a price")
                fail(409, "state", detail)
            price = float(m["price"])
            src = f"stored mark {m['as_of']} · {m['price_source']}"
        exit_costs = _side_costs(str(p["family"]), "sell" if p["side"] == "buy" else "buy", price, int(p["lots"]),
                                 float(p["brokerage_per_order"]))
        fills.append({"position_id": int(pid), "exit_price": price, "exit_price_source": src, "exit_costs": exit_costs})
    try:
        closed = await asyncio.to_thread(store.close, fills, action="close")
    except fts.BookError as exc:
        fail(409, "state", str(exc))
    return {"paper": True, "badge": BADGE_ARITH, "closed": closed,
            "note": f"realised is recorded point-in-time, net of the recorded entry + exit costs. {DESCRIBES}."}


@router.get("")
@router.get("/list")
async def book(limit: int = 200) -> dict[str, Any]:
    """The book: open positions with their latest STORED mark (source labelled), unrealised and day-MTM arithmetic;
    closed positions with the realised money recorded at their close. No composite score; context never coloured."""
    store = fts.get_store()
    rows = await asyncio.to_thread(store.positions)
    today = _today_ist().isoformat()
    open_rows = [p for p in rows if p["status"] == "open"]
    latest = await asyncio.to_thread(store.latest_marks, [int(p["id"]) for p in open_rows]) if open_rows else {}
    out_open: list[dict[str, Any]] = []
    tot_unreal, unmarked = 0.0, 0
    for p in open_rows:
        pid, expiry = int(p["id"]), str(p["expiry"])[:10]
        expired = expiry < today
        m = latest.get(pid)
        if expired and m is not None and str(m["as_of"])[:10] > expiry:
            m = (await asyncio.to_thread(store.latest_marks, [pid], through=expiry)).get(pid)
        q = (1 if p["side"] == "buy" else -1) * int(p["lots"]) * float(p["multiplier"])
        row: dict[str, Any] = {**p, "expired": expired, "mark": None, "unrealised_inr": None,
                               "day_mtm_inr": None, "day_mtm_basis": None,
                               "state": (UNSETTLED if expired else "open")}
        if m is not None:
            row["mark"] = {"price": float(m["price"]), "as_of": m["as_of"], "source": m["price_source"],
                           "session": m["session"], "quality": m["quality"]}
            row["unrealised_inr"] = round(q * (float(m["price"]) - float(p["entry_price"])), 2)
            tot_unreal += row["unrealised_inr"]
            prev = await asyncio.to_thread(store.prev_mark, pid, str(m["as_of"])[:10])
            base = float(prev["price"]) if prev else float(p["entry_price"])
            row["day_mtm_inr"] = round(q * (float(m["price"]) - base), 2)
            row["day_mtm_basis"] = (f"vs the previous stored mark ({prev['as_of']})" if prev
                                    else "vs the entry price (first marked session)")
        else:
            unmarked += 1
        out_open.append(row)
    out_closed: list[dict[str, Any]] = []
    tot_real = tot_gross = tot_costs = 0.0
    for p in rows:
        if p["status"] != "closed":
            continue
        got = fts.realised_from_row(p)
        rec = {**p, "realised": None}
        if got is not None:
            g, c, n = got
            rec["realised"] = {"gross_inr": g, "costs_inr": c, "realised_inr": n,
                               "basis": "net of the recorded entry + exit costs"}
            tot_real, tot_gross, tot_costs = tot_real + n, tot_gross + g, tot_costs + c
        out_closed.append(rec)
    out_closed = out_closed[-int(limit):]
    return {"paper": True, "badge": BADGE_ARITH, "as_of": datetime.now(IST).isoformat(timespec="seconds"),
            "open": out_open, "closed": out_closed,
            "totals": {"open_unrealised_inr": round(tot_unreal, 2), "unmarked": unmarked,
                       "realised_inr": round(tot_real, 2), "realised_gross_inr": round(tot_gross, 2),
                       "costs_inr": round(tot_costs, 2)},
            "notes": [PAPER_NOTE, MARK_NOTE, f"unrealised is gross of exit-side costs (arithmetic). {DESCRIBES}."]}


@router.get("/journal")
async def journal(limit: int = 50) -> dict[str, Any]:
    store = fts.get_store()
    rows = await asyncio.to_thread(store.journal, max(1, min(int(limit), 500)))
    return {"paper": True, "rows": rows, "note": f"append-only action log. {DESCRIBES}."}
