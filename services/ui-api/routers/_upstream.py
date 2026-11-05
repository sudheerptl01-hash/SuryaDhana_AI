"""Shared helper for proxy routes: turn a data-service error response into a readable `detail`."""
from __future__ import annotations

from typing import Any


def upstream_detail(r: Any, limit: int = 300) -> Any:
    """The upstream FastAPI `detail` when the body is JSON (so the UI shows "TCS is not in the NSE bhavcopy", not
    '{"detail": "…"}'), else the first `limit` characters of the body."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:limit]
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return r.text[:limit]
