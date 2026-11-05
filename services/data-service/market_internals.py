"""Market internals through the session: breadth (advances / declines) and size-segment moves sampled from NSE's
allIndices every couple of minutes, archived per day to data/nse_archive/internals/<date>.jsonl.

NSE only publishes a breadth *snapshot*; the path through the day (is the rally broadening or narrowing? did
small caps roll over while NIFTY held?) exists only if someone samples it. The master-controller's
`internals_sample` job calls POST /db/internals/sample every 2 minutes in session.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SEGMENTS = {"NIFTY 50": "n50", "NIFTY 500": "n500", "NIFTY MIDCAP 150": "mid", "NIFTY SMALLCAP 250": "small", "NIFTY BANK": "bank"}


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def snapshot(all_indices: dict) -> Optional[dict[str, Any]]:
    """One sample from NSE's allIndices payload: NSE timestamp, NIFTY 50 level, % move per segment and NIFTY 500 /
    all-NSE advances and declines. None when the payload has no NIFTY 50 row."""
    rows = {r.get("index"): r for r in all_indices.get("data") or []}
    if "NIFTY 50" not in rows:
        return None
    out: dict[str, Any] = {"nse_ts": all_indices.get("timestamp"), "nifty": _num(rows["NIFTY 50"].get("last"))}
    for name, key in SEGMENTS.items():
        r = rows.get(name)
        out[f"{key}_pct"] = _num(r.get("percentChange")) if r else None
    n500 = rows.get("NIFTY 500") or {}
    out["n500_adv"], out["n500_dec"] = _num(n500.get("advances")), _num(n500.get("declines"))
    out["all_adv"], out["all_dec"] = _num(all_indices.get("advances")), _num(all_indices.get("declines"))
    return out


def session_day(nse_ts: Optional[str]) -> Optional[str]:
    """'13-Oct-2026 11:33' → '2026-10-13'."""
    try:
        return datetime.strptime(str(nse_ts)[:11], "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def append(archive: Path, snap: dict[str, Any]) -> bool:
    """Append a sample to that session's file unless NSE's timestamp has not moved since the last sample."""
    day = session_day(snap.get("nse_ts"))
    if not day:
        return False
    archive.mkdir(parents=True, exist_ok=True)
    path = archive / f"{day}.jsonl"
    last = read(archive, day)[-1:] if path.exists() else []
    if last and last[0].get("nse_ts") == snap.get("nse_ts"):
        return False
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**snap, "sampled_at": datetime.now().isoformat(timespec="seconds")}) + "\n")
    return True


def read(archive: Path, day: str) -> list[dict[str, Any]]:
    path = archive / f"{day}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Plain-language read of the session: NIFTY vs breadth, and how breadth changed since the first sample."""
    if not rows:
        return {}
    first, last = rows[0], rows[-1]
    adv, dec = last.get("n500_adv"), last.get("n500_dec")
    ratio = adv / dec if adv and dec else None
    n50 = last.get("n50_pct")
    narrow = n50 is not None and ratio is not None and ((n50 > 0.25 and ratio < 1) or (n50 < -0.25 and ratio > 1))
    net = [r["n500_adv"] - r["n500_dec"] for r in rows if r.get("n500_adv") is not None and r.get("n500_dec") is not None]
    return {"samples": len(rows), "first": first.get("nse_ts"), "last": last.get("nse_ts"),
            "n500_adv": adv, "n500_dec": dec, "ad_ratio": round(ratio, 2) if ratio else None,
            "net_now": net[-1] if net else None, "net_best": max(net) if net else None, "net_worst": min(net) if net else None,
            "divergence": "narrow: NIFTY up, most stocks down" if narrow and (n50 or 0) > 0 else
                          "narrow: NIFTY down, most stocks up" if narrow else None,
            "small_minus_n50": round(last["small_pct"] - n50, 2) if last.get("small_pct") is not None and n50 is not None else None}
