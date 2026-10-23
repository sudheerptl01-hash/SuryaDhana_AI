#!/usr/bin/env python3
"""Determinism proof of the paper ledger (ml/paper/SPEC.md section 4).

    OMP_NUM_THREADS=2 python3 -I ml/paper/prove.py

Regenerates the whole ledger from inception with the current code in a sandbox (ml/paper/state/regen/, gitignored):
every path the job writes (ledger CSVs, state.json, per-date scores, runs log, paper.json/PAPER.md) is redirected
there, the job runs with --no-ingest on the same store, frame and models, and the regenerated ledger and score files
are compared byte for byte with the committed ones.  The committed ledger is never opened for writing; its hashes are
checked before and after.  Result: ml/results/improve2/paper/regeneration.json.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse  # noqa: E402
import shutil  # noqa: E402

from ml.paper import book as B  # noqa: E402
from ml.paper import common as C  # noqa: E402
from ml.paper import job as J  # noqa: E402
from ml.paper import report as R  # noqa: E402
from ml.paper.common import log, repo_rel, sha256_file, wjson  # noqa: E402
from ml.paper.config import RESULTS_DIR, SPEC_HASH, STATE_DIR  # noqa: E402

SANDBOX = STATE_DIR / "regen"
REGEN_JSON = RESULTS_DIR / "regeneration.json"


def regenerate() -> dict:
    real_ledger = {**{k: Path(p) for k, p in C.LEDGER_FILES.items()}, "state": Path(C.STATE_JSON)}
    real_scores = sorted(Path(B.SCORES_DIR).glob("scores_*.parquet"))
    before = {k: sha256_file(p) for k, p in real_ledger.items()}
    before_scores = {p.name: sha256_file(p) for p in real_scores}
    shutil.rmtree(SANDBOX, ignore_errors=True)
    (SANDBOX / "ledger").mkdir(parents=True)
    (SANDBOX / "scores").mkdir()
    box = {k: SANDBOX / "ledger" / p.name for k, p in real_ledger.items()}
    saved = {"ledger": dict(C.LEDGER_FILES), "c_state": C.STATE_JSON, "j_state": J.STATE_JSON,
             "scores": B.SCORES_DIR, "runs": J.RUNS_FILE, "idem": J.IDEM_JSON,
             "pj": R.PAPER_JSON, "pm": R.PAPER_MD}
    try:
        for k in C.LEDGER_FILES:                       # the dict is shared by every module that imported it
            C.LEDGER_FILES[k] = box[k]
        C.STATE_JSON = J.STATE_JSON = box["state"]
        B.SCORES_DIR = SANDBOX / "scores"
        J.RUNS_FILE = SANDBOX / "runs.jsonl"
        J.IDEM_JSON = SANDBOX / "idempotency.json"
        R.PAPER_JSON, R.PAPER_MD = SANDBOX / "paper.json", SANDBOX / "PAPER.md"
        rec = J.run(argparse.Namespace(no_ingest=True, force_frame=False, prove_idempotency=False,
                                       accept_unverified_write=None))
    finally:
        C.LEDGER_FILES.clear()
        C.LEDGER_FILES.update(saved["ledger"])
        C.STATE_JSON, J.STATE_JSON = saved["c_state"], saved["j_state"]
        B.SCORES_DIR, J.RUNS_FILE, J.IDEM_JSON = saved["scores"], saved["runs"], saved["idem"]
        R.PAPER_JSON, R.PAPER_MD = saved["pj"], saved["pm"]
    after = {k: sha256_file(p) for k, p in real_ledger.items()}
    regen = {k: sha256_file(p) if p.exists() else None for k, p in box.items()}
    regen_scores = {p.name: sha256_file(p) for p in sorted((SANDBOX / "scores").glob("scores_*.parquet"))}
    files = {k: {"committed": before[k], "regenerated": regen[k], "identical": before[k] == regen[k]}
             for k in real_ledger}
    out = {"procedure": "ml/paper/prove.py: the job (--no-ingest) run from an empty ledger in ml/paper/state/regen/ with "
                        "the same store, scoring frame and month models; every write redirected to the sandbox",
           "spec_hash": SPEC_HASH,
           "ledger_files": {k: {**v, "path": repo_rel(real_ledger[k])} for k, v in files.items()},
           "ledger_identical": all(v["identical"] for v in files.values()),
           "score_files": {n: {"identical": before_scores.get(n) == h} for n, h in regen_scores.items()},
           "score_files_identical": (set(regen_scores) == set(before_scores)
                                     and all(before_scores[n] == h for n, h in regen_scores.items())),
           "committed_ledger_untouched": before == after,
           "regenerated_rows_appended": {"signals": rec["signals"]["rows_appended"],
                                         "marks": rec["marks"]["rows_appended"],
                                         "monitors": rec["monitors"]["rows_appended"]},
           "regenerated_signal_dates": rec["signals"]["appended_signal_dates"],
           "seconds": rec["seconds"]}
    wjson(REGEN_JSON, out)
    log(f"regeneration from inception: ledger identical {out['ledger_identical']}, score files identical "
        f"{out['score_files_identical']}, committed ledger untouched {out['committed_ledger_untouched']}", "prove")
    if out["ledger_identical"] and out["score_files_identical"]:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    return out


def main() -> int:
    out = regenerate()
    print(C.dumps({k: v for k, v in out.items() if k not in ("score_files",)}))
    return 0 if (out["ledger_identical"] and out["score_files_identical"] and out["committed_ledger_untouched"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
