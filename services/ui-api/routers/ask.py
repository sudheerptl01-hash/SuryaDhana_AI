"""ASK — RSCH's cited read-only analyst (FINAL ROUND R2-ASK; RATING §7 R9-R1). Mounted at /api/ask (main.py
mount is a PM patch request).

Thin FastAPI face over `ask_engine.AskEngine` (where all eight guardrails live; see its docstring and
`tests/test_ask_guardrails.py`). Everything here is PAPER-irrelevant by construction: no order path, no Telegram,
no writes beyond the audit log, and the answers feed nothing — not the Decision Desk, not the S1 shadow, not a
directional alert, not a ticket price. Engine work runs off the event loop (asyncio.to_thread): a 10 s query or a
60 s LLM call must never stall ui-api's loop (MEMORY ui_api_event_loop).

  GET  /api/ask/health   provider, model, snapshot as-of, the guardrail list (the panel's status strip)
  POST /api/ask          {question} -> the cited answer payload (or the standing refusal / degraded shape)
  POST /api/ask/query    {sql}     -> the direct data read (no LLM; "the data reads still work")
  GET  /api/ask/audit    the last N audit lines (ts, question, sql, rows_returned, model — never row payloads)
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ask_engine import MAX_QUESTION_LEN, AskEngine, AskError

router = APIRouter()
_engine: AskEngine | None = None


def engine() -> AskEngine:
    global _engine
    if _engine is None:
        _engine = AskEngine()
    return _engine


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LEN)


class ReadRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=4000)


@router.get("/health")
async def ask_health() -> dict[str, Any]:
    return await asyncio.to_thread(engine().health)


@router.post("")
async def ask(req: AskRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(engine().ask, req.question)
    except AskError as exc:                      # calm, render-safe refusals only
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/query")
async def ask_query(req: ReadRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(engine().read, req.sql)
    except AskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/audit")
async def ask_audit(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    rows = await asyncio.to_thread(engine().audit_tail, limit)
    return {"ok": True, "rows": rows, "note": "ts · question · sql · rows_returned · model — payloads are never stored"}
