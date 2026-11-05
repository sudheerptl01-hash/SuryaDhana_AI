"""One error contract for ui-api (Bloomberg program F2.4/S7, amended A2).

Two paths, both ADDITIVE so no existing frontend branch breaks:

- HTTP errors: `fail(status, code, message, hint)` raises HTTPException whose response is
  `{"detail": "<message string>", "error": {"code", "message", "hint"?}}` — `detail` STAYS a
  plain string because 20+ components render it directly as a React child (design_review.md
  finding 2); the structured block rides beside it. Plain-string HTTPExceptions from legacy
  code get the same envelope via the app-level handler (code derived from the status).

- Degraded-but-usable 200s: `degraded(payload, code, message, hint)` adds `ok: False` and a
  structured `error_info{}` NEXT TO the payload's legacy keys. The legacy `error` key in those
  payloads is a STRING today (positions/pipeline family) and must stay one, so the structured
  sibling uses a distinct name. Frontend normalizer order: error_info → error(object) →
  error(string) → detail → connected:false → network.

Fixed code enum (PM decision): not_found · upstream_down · degraded · unauthorized · invalid ·
state · internal.
"""
from __future__ import annotations

from typing import Any, Literal, NoReturn

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

Code = Literal["not_found", "upstream_down", "degraded", "unauthorized", "invalid", "state", "internal"]
CODES: tuple[str, ...] = ("not_found", "upstream_down", "degraded", "unauthorized", "invalid", "state", "internal")


def error_block(code: Code, message: str, hint: str | None = None) -> dict:
    return {"code": code, "message": message, **({"hint": hint} if hint else {})}


def fail(status: int, code: Code, message: str, hint: str | None = None) -> NoReturn:
    """Raise an HTTPException the app-level handler renders as {detail: str, error: {…}}."""
    raise HTTPException(status_code=status, detail=error_block(code, message, hint))


def degraded(payload: dict[str, Any], code: Code, message: str, hint: str | None = None) -> dict:
    """200 with usable-but-degraded data ONLY. Keeps every legacy key (incl. a string `error`)
    and adds `ok: False` + structured `error_info{}`."""
    return {**payload, "ok": False, "error_info": error_block(code, message, hint)}


def validation_message(errors: list[Any]) -> str:
    """One readable line from FastAPI's RequestValidationError items (first 3, '+N more')."""
    parts: list[str] = []
    for e in errors[:3]:
        if not isinstance(e, dict):
            parts.append(str(e))
            continue
        loc = ".".join(str(x) for x in (e.get("loc") or ()) if x not in ("query", "body", "path", "header"))
        msg = str(e.get("msg") or "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    extra = len(errors) - 3
    return "; ".join(parts) + (f" (+{extra} more)" if extra > 0 else "")


async def validation_error_handler(request: Any, exc: Any) -> JSONResponse:
    """RequestValidationError → the SAME envelope as every other error (W7, verdict D8/S7).

    FastAPI's default 422 is a bare `{"detail": [...]}` array with no `error{}` sibling — the
    one response family that escaped the contract. This keeps `detail` a human string (legacy
    renderers), rides `error{code:"invalid"}` beside it, and preserves the raw items under
    `errors` for debuggers. Registered in main.py:
        app.add_exception_handler(RequestValidationError, validation_error_handler)
    """
    try:
        errs = jsonable_encoder(exc.errors())  # items may embed non-JSON input (bytes, etc.)
    except Exception:  # noqa: BLE001 — never let the error path itself 500
        errs = []
    message = validation_message(errs) or "invalid request"
    return JSONResponse({"detail": message, "error": error_block("invalid", message), "errors": errs},
                        status_code=422)


def code_for_status(status: int) -> Code:
    if status == 404:
        return "not_found"
    if status in (401, 403):
        return "unauthorized"
    if status in (400, 422):
        return "invalid"
    if status == 503:
        return "state"
    if status in (502, 504):
        return "upstream_down"
    return "internal"
