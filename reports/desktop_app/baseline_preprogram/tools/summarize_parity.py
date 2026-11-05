"""Markdown summary of a parity.py report for the baseline README: per-tab verdict per engine, timings, seams.

Usage: python summarize_parity.py <parity.json> [--rerun <parity.json>] > summary.md
``--rerun`` is a symmetric re-probe of the DIFF tabs; its verdict is shown next to the main one.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def seam_keys(tab: dict[str, Any], side: str) -> list[str]:
    seams = (tab.get("diff") or {}).get("platform_seams") or {}
    return sorted((seams.get(side) or {}).get("api", {}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--rerun", type=Path)
    a = ap.parse_args(argv)
    rep = json.loads(a.report.read_text())
    rerun = json.loads(a.rerun.read_text()) if a.rerun else None
    engines = list(rep["engines"])
    tabs = rep["meta"]["tabs"]
    m = rep["meta"]
    head = (f"A = `{m['a']}` ({m.get('label_a', '')}) · B = `{m['b']}` ({m.get('label_b', '')}) · "
            f"started {m['started_at']} · {m.get('elapsed_s', '?')} s · seam exclusion {m['seam_exclusion']}")
    out = [head, ""]
    for e in engines:
        s = rep["engines"][e]["summary"]
        out.append(f"- **{e}** ({rep['engines'][e].get('browser_version', '')}): {s['parity']}/{s['tabs']} PARITY · "
                   f"DIFF: {', '.join(s['diff']) or 'none'} · A audit failures: {', '.join(s.get('a_failed', [])) or 'none'} · "
                   f"B audit failures: {', '.join(s['b_failed']) or 'none'}")
    out += ["", "| tab | code | " + " | ".join(f"{e} verdict | {e} ready A/B ms" for e in engines) + " | B-only seams |",
            "|---|---|" + "---|---|" * len(engines) + "---|"]
    seam_count: Counter[str] = Counter()
    ready: dict[str, dict[str, list[int]]] = {e: {"a": [], "b": []} for e in engines}
    for t in tabs:
        cells, code, seams_b = [], "", set()
        for e in engines:
            tab = rep["engines"][e]["tabs"].get(t)
            if not tab:
                cells += ["—", "—"]
                continue
            code = tab.get("code") or code
            verdict = tab["verdict"]
            if verdict == "DIFF" and rerun and t in rerun["engines"].get(e, {}).get("tabs", {}):
                verdict += f" → symmetric re-probe: **{rerun['engines'][e]['tabs'][t]['verdict']}**"
            ra, rb = tab["a"]["timing"].get("ready_ms"), tab["b"]["timing"].get("ready_ms")
            if ra is not None:
                ready[e]["a"].append(ra)
            if rb is not None:
                ready[e]["b"].append(rb)
            cells += [verdict, f"{ra}/{rb}"]
            only_b = set(seam_keys(tab, "b")) - set(seam_keys(tab, "a"))
            seams_b |= only_b
            for k in only_b:
                seam_count[f"{e}: {k}"] += 1
        out.append(f"| {t} | {code} | " + " | ".join(cells) + f" | {', '.join(sorted(seams_b)) or '—'} |")
    out += ["", "Ready time (navigation → page header, ms), median / p95:", ""]
    for e in engines:
        for side in ("a", "b"):
            v = sorted(ready[e][side])
            if v:
                p95 = v[min(len(v) - 1, round(0.95 * (len(v) - 1)))]
                out.append(f"- {e} {side.upper()}: median {statistics.median(v):.0f} · p95 {p95} · n={len(v)}")
    out += ["", "B-only platform-seam endpoints (tabs per engine):", ""]
    out += [f"- {k}: {n}" for k, n in sorted(seam_count.items())] or ["- none"]
    for e in engines:
        for t, tab in rep["engines"][e]["tabs"].items():
            if tab["verdict"] == "DIFF":
                out += ["", f"DIFF detail {e}/{t}: " + "; ".join(tab.get("reasons", []))]
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
