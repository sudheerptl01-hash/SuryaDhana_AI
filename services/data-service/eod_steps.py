"""
EOD pipeline step runner — every step isolated, failures collected, nothing skipped.

Why this exists (15 Oct 2026 incident): the daily pipeline ran its steps inline, and the ML
dataset rebuild sat SECOND in line, unguarded. It hit DuckDB's memory cap (OutOfMemoryException,
1.5 GB) and the exception skipped every step after it — the NSE bhavcopy, NSE positions, the
market-monitor rebuild and the corporate calendar — so the Desk, the paper shadow, the MKT tab
and the 21:00 wrap all read a day-old market.

Contract:
  * steps run in the order given, and EVERY step runs even if an earlier one failed;
  * a failing step's result is {"error": "<Type>: <message>"} (the job record keeps it);
  * after all steps, if any FATAL step failed, raise EodStepsFailed (job status = error →
    the controller's CRITICAL alert); non-fatal failures only show up in the result, which the
    controller turns into a WARNING.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence


class EodStepsFailed(RuntimeError):
    """Raised after ALL steps ran, when at least one fatal step failed."""

    def __init__(self, failed: list[str], results: dict[str, Any]):
        self.failed = failed
        self.results = results
        detail = "; ".join(f"{n}: {results[n]['error']}" for n in failed)
        super().__init__(f"EOD steps failed: {', '.join(failed)} — {detail}")


def run_steps(steps: Sequence[tuple[str, Callable[[], Any], bool]], log: Any) -> dict[str, Any]:
    """Run (name, fn, fatal) steps in order; see the module docstring for the contract."""
    results: dict[str, Any] = {}
    failed: list[str] = []
    for name, fn, fatal in steps:
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            msg = f"{type(exc).__name__}: {exc}"
            results[name] = {"error": msg}
            (log.error if fatal else log.warning)(f"EOD step failed: {name}", error=msg)
            if fatal:
                failed.append(name)
    if failed:
        raise EodStepsFailed(failed, results)
    return results


def soft_failures(results: dict[str, Any]) -> dict[str, str]:
    """{step: error} for steps that failed without failing the job (the controller's WARNING)."""
    return {k: v["error"] for k, v in results.items() if isinstance(v, dict) and v.get("error")}
