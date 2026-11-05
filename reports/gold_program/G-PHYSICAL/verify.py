"""Live verification harness for G-PHYSICAL sources. Public GET only, modest rate, browser-like UA.
Usage: verify.py <batch-name>   (results appended to verify_log.jsonl, samples saved under samples/)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent
SAMPLES = OUT / "samples"
SAMPLES.mkdir(exist_ok=True)
LOG = OUT / "verify_log.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36 SuryaDhana-research/0.1 (contact: owner of the terminal)",
      "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
SLEEP = 1.5


def fetch(name: str, url: str, *, headers: dict | None = None, timeout: float = 40.0, plain_ua: bool = False,
          save_as: str | None = None, max_bytes: int = 25_000_000) -> dict:
    h = {} if plain_ua else dict(UA)
    if headers:
        h.update(headers)
    t0 = time.perf_counter()
    rec: dict = {"name": name, "url": url, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), headers=h, follow_redirects=True) as c:
            r = c.get(url)
        dt = time.perf_counter() - t0
        body = r.content[:max_bytes]
        rec.update({"status": r.status_code, "latency_s": round(dt, 2), "final_url": str(r.url),
                    "content_type": r.headers.get("content-type", ""), "bytes": len(r.content),
                    "last_modified": r.headers.get("last-modified", "")})
        if save_as:
            (SAMPLES / save_as).write_bytes(body)
            rec["saved"] = str(SAMPLES / save_as)
        ct = rec["content_type"]
        if "json" in ct or "text" in ct or "csv" in ct or "xml" in ct or "html" in ct:
            txt = body.decode("utf-8", errors="replace")
            rec["head"] = txt[:600]
        else:
            rec["head"] = body[:64].hex()
    except Exception as exc:  # noqa: BLE001
        rec.update({"status": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "latency_s": round(time.perf_counter() - t0, 2)})
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[{rec.get('status')}] {rec['latency_s']:>6}s {rec['bytes'] if 'bytes' in rec else '-':>9} {name} -> "
          f"{rec.get('final_url', '')[:110]} {rec.get('error', '')}")
    time.sleep(SLEEP)
    return rec


if __name__ == "__main__":
    print("import-only harness; see batch_*.py")
