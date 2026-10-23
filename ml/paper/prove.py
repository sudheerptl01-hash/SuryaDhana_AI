#!/usr/bin/env python3
"""Determinism proof of the paper ledger (ml/paper/SPEC.md sections 4 and 5).

    OMP_NUM_THREADS=2 python3 -I ml/paper/prove.py

Regenerates the whole ledger from inception with the current code in a sandbox (ml/paper/state/regen/, gitignored):
every path the job writes (ledger CSVs, state.json, per-date scores of the frozen books and of extension 1, runs log,
paper.json/PAPER.md) is redirected there, the job runs with --no-ingest on the same store, frame and models, and the
regenerated ledger and score files are compared byte for byte with the committed ones.  The rebuild covers the six
books: the four frozen books and the two books of extension 1 (SPEC.md amendment 10), in the ledger order of
config.SPEC_EXT['ledger_order'] (the frozen rows up to the backfill date, then the extension's backfill block, then
every later date's rows).

A second regeneration (ml/paper/state/regen_frozen/) runs the job with the extension switched off: its signals,
marks and monitors files must equal the committed ledger's frozen-book rows byte for byte, and the ledger as it stood
before the amendment must be their prefix.  That is the proof that adding the extension changed no byte of the
primary, capacity, challenger and plain-reference books.

The committed ledger is never opened for writing; its hashes are checked before and after.  Result:
ml/results/improve2/paper/regeneration.json.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse  # noqa: E402
import csv  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402

from ml.paper import book as B  # noqa: E402
from ml.paper import common as C  # noqa: E402
from ml.paper import job as J  # noqa: E402
from ml.paper import monitors as MON  # noqa: E402
from ml.paper import report as R  # noqa: E402
from ml.paper.common import log, repo_rel, sha256_file, wjson  # noqa: E402
from ml.paper.config import EXT_BOOK_ORDER, RESULTS_DIR, SPEC_EXT_HASH, SPEC_HASH, STATE_DIR  # noqa: E402

SANDBOX = STATE_DIR / "regen"
SANDBOX_FROZEN = STATE_DIR / "regen_frozen"
REGEN_JSON = RESULTS_DIR / "regeneration.json"
# The ledger as it stood when extension 1 was added (2026-10-23, before the backfill run): SHA-256 and size in bytes.
PRE_AMENDMENT = {"signals": ("d673191e6e44e48049b4fd99952bf4b03c213b075cca068b673015c227414e8e", 97188),
                 "marks": ("d82156ed4411ac17db457966846446c1e652996993c6194f07997b4b953481dc", 858),
                 "monitors": ("5258b13a813a9c4d7fa5bcc5844278af04e08cb2ec7c6ec498a9aa23e72bed55", 7956)}
PRE_AMENDMENT_STATE = "56c6baae4f208931d6090d101f1e8d1fe5ad7a2896766f626c7d844321ae1319"   # state.json at that moment


def _sandbox_run(box_dir: Path, extension: bool) -> tuple[dict, dict]:
    real_ledger = {**{k: Path(p) for k, p in C.LEDGER_FILES.items()}, "state": Path(C.STATE_JSON)}
    shutil.rmtree(box_dir, ignore_errors=True)
    (box_dir / "ledger").mkdir(parents=True)
    (box_dir / "scores").mkdir()
    (box_dir / "scores_expanding").mkdir()
    box = {k: box_dir / "ledger" / p.name for k, p in real_ledger.items()}
    saved = {"ledger": dict(C.LEDGER_FILES), "c_state": C.STATE_JSON, "j_state": J.STATE_JSON,
             "scores": B.SCORES_DIR, "scores_x": B.SCORES_EXT_DIR, "runs": J.RUNS_FILE, "idem": J.IDEM_JSON,
             "xbf": J.EXT_BACKFILL_JSON, "pj": R.PAPER_JSON, "pm": R.PAPER_MD, "ext": J.EXTENSION}
    try:
        for k in C.LEDGER_FILES:                       # the dict is shared by every module that imported it
            C.LEDGER_FILES[k] = box[k]
        C.STATE_JSON = J.STATE_JSON = box["state"]
        B.SCORES_DIR = box_dir / "scores"
        B.SCORES_EXT_DIR = box_dir / "scores_expanding"
        J.RUNS_FILE = box_dir / "runs.jsonl"
        J.IDEM_JSON = box_dir / "idempotency.json"
        J.EXT_BACKFILL_JSON = box_dir / "extension_backfill.json"
        R.PAPER_JSON, R.PAPER_MD = box_dir / "paper.json", box_dir / "PAPER.md"
        J.EXTENSION = extension
        rec = J.run(argparse.Namespace(no_ingest=True, force_frame=False, prove_idempotency=False,
                                       accept_unverified_write=None, extension_backfill_proof=False))
    finally:
        C.LEDGER_FILES.clear()
        C.LEDGER_FILES.update(saved["ledger"])
        C.STATE_JSON, J.STATE_JSON = saved["c_state"], saved["j_state"]
        B.SCORES_DIR, B.SCORES_EXT_DIR = saved["scores"], saved["scores_x"]
        J.RUNS_FILE, J.IDEM_JSON, J.EXT_BACKFILL_JSON = saved["runs"], saved["idem"], saved["xbf"]
        R.PAPER_JSON, R.PAPER_MD = saved["pj"], saved["pm"]
        J.EXTENSION = saved["ext"]
    return rec, box


def _frozen_rows_bytes(path: Path, kind: str) -> tuple[bytes, bool]:
    """The committed CSV's header and frozen-book rows, written by the ledger's own CSV writer; plus whether the
    same writer reproduces the whole committed file (so the filtered bytes are the file's own lines)."""
    raw = path.read_bytes()
    rows = list(csv.reader(io.StringIO(raw.decode(), newline="")))
    header, body = rows[0], rows[1:]

    def ext(r):
        d = dict(zip(header, r))
        return MON.is_ext_row(d) if kind == "monitors" else d["book"] in EXT_BOOK_ORDER

    def write(rs):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for r in rs:
            w.writerow(r)
        return buf.getvalue().encode()
    return write([header] + [r for r in body if not ext(r)]), write(rows) == raw


def regenerate() -> dict:
    real_ledger = {**{k: Path(p) for k, p in C.LEDGER_FILES.items()}, "state": Path(C.STATE_JSON)}
    real_scores = sorted(Path(B.SCORES_DIR).glob("scores_*.parquet"))
    real_scores_x = sorted(Path(B.SCORES_EXT_DIR).glob("scores_*.parquet"))
    before = {k: sha256_file(p) for k, p in real_ledger.items()}
    before_scores = {p.name: sha256_file(p) for p in real_scores}
    before_scores_x = {p.name: sha256_file(p) for p in real_scores_x}

    rec, box = _sandbox_run(SANDBOX, extension=True)
    regen = {k: sha256_file(p) if p.exists() else None for k, p in box.items()}
    regen_scores = {p.name: sha256_file(p) for p in sorted((SANDBOX / "scores").glob("scores_*.parquet"))}
    regen_scores_x = {p.name: sha256_file(p) for p in sorted((SANDBOX / "scores_expanding").glob("scores_*.parquet"))}

    rec_f, box_f = _sandbox_run(SANDBOX_FROZEN, extension=False)
    frozen_files = {}
    for k in ("signals", "marks", "monitors"):
        want, roundtrip = _frozen_rows_bytes(real_ledger[k], k)
        got = box_f[k].read_bytes()
        h, n = PRE_AMENDMENT[k]
        frozen_files[k] = {"regenerated_sha256": hashlib.sha256(got).hexdigest(),
                           "committed_frozen_rows_sha256": hashlib.sha256(want).hexdigest(),
                           "identical": got == want, "csv_writer_reproduces_committed_file": roundtrip,
                           "pre_amendment_sha256": h, "pre_amendment_bytes": n,
                           "pre_amendment_ledger_is_prefix": hashlib.sha256(got[:n]).hexdigest() == h,
                           "equal_to_pre_amendment_ledger": len(got) == n and hashlib.sha256(got).hexdigest() == h}
    st = json.loads(real_ledger["state"].read_text())
    st.pop("extension", None)
    want_state = C.dumps(st).encode()
    got_state = box_f["state"].read_bytes()
    frozen_files["state"] = {"regenerated_sha256": hashlib.sha256(got_state).hexdigest(),
                             "committed_without_extension_sha256": hashlib.sha256(want_state).hexdigest(),
                             "identical": got_state == want_state,
                             "pre_amendment_sha256": PRE_AMENDMENT_STATE,
                             "equal_to_pre_amendment_state": hashlib.sha256(got_state).hexdigest() == PRE_AMENDMENT_STATE,
                             "rule": "committed state.json without its 'extension' key, written by the ledger's JSON writer"}
    after = {k: sha256_file(p) for k, p in real_ledger.items()}
    files = {k: {"committed": before[k], "regenerated": regen[k], "identical": before[k] == regen[k]}
             for k in real_ledger}
    out = {"procedure": "ml/paper/prove.py: the job (--no-ingest) run from an empty ledger in ml/paper/state/regen/ with "
                        "the same store, scoring frame and month models (frozen and expanding-window); every write "
                        "redirected to the sandbox; the rebuild covers the four frozen books and the two books of "
                        "extension 1",
           "spec_hash": SPEC_HASH, "extension_spec_hash": SPEC_EXT_HASH,
           "ledger_files": {k: {**v, "path": repo_rel(real_ledger[k])} for k, v in files.items()},
           "ledger_identical": all(v["identical"] for v in files.values()),
           "score_files": {n: {"identical": before_scores.get(n) == h} for n, h in regen_scores.items()},
           "score_files_identical": (set(regen_scores) == set(before_scores)
                                     and all(before_scores[n] == h for n, h in regen_scores.items())),
           "score_files_expanding": {n: {"identical": before_scores_x.get(n) == h} for n, h in regen_scores_x.items()},
           "score_files_identical_expanding": (set(regen_scores_x) == set(before_scores_x)
                                               and all(before_scores_x[n] == h for n, h in regen_scores_x.items())),
           "committed_ledger_untouched": before == after,
           "regenerated_rows_appended": {"signals": rec["signals"]["rows_appended"],
                                         "marks": rec["marks"]["rows_appended"],
                                         "monitors": rec["monitors"]["rows_appended"],
                                         "signals_expanding": rec["signals"].get("rows_appended_expanding"),
                                         "marks_expanding": rec["marks"].get("rows_appended_expanding"),
                                         "monitors_expanding": rec["monitors"].get("rows_appended_expanding")},
           "regenerated_signal_dates": rec["signals"]["appended_signal_dates"],
           "regenerated_signal_dates_expanding": rec["signals"].get("appended_signal_dates_expanding"),
           "frozen_only": {"procedure": "the same job with the extension switched off (ml/paper/state/regen_frozen/), "
                                        "compared with the committed ledger's frozen-book rows",
                           "files": frozen_files,
                           "identical_to_committed_frozen_rows": all(v["identical"] for k, v in frozen_files.items()
                                                                     if k != "state"),
                           "pre_amendment_ledger_is_prefix": all(v["pre_amendment_ledger_is_prefix"]
                                                                 for k, v in frozen_files.items() if k != "state"),
                           "identical_to_pre_amendment_ledger": all(v["equal_to_pre_amendment_ledger"]
                                                                    for k, v in frozen_files.items() if k != "state"),
                           "state_identical_to_committed_without_extension": frozen_files["state"]["identical"],
                           "state_equal_to_pre_amendment_state": frozen_files["state"]["equal_to_pre_amendment_state"],
                           "rows_appended": {"signals": rec_f["signals"]["rows_appended"],
                                             "marks": rec_f["marks"]["rows_appended"],
                                             "monitors": rec_f["monitors"]["rows_appended"]}},
           "seconds": round(rec["seconds"] + rec_f["seconds"], 1)}
    wjson(REGEN_JSON, out)
    ok = ok_of(out)
    log(f"regeneration from inception: ledger identical {out['ledger_identical']}, score files identical "
        f"{out['score_files_identical']} (expanding {out['score_files_identical_expanding']}), frozen books without the "
        f"extension identical {out['frozen_only']['identical_to_committed_frozen_rows']}, committed ledger untouched "
        f"{out['committed_ledger_untouched']}", "prove")
    if ok:
        shutil.rmtree(SANDBOX, ignore_errors=True)
        shutil.rmtree(SANDBOX_FROZEN, ignore_errors=True)
    return out


def ok_of(out: dict) -> bool:
    return bool(out["ledger_identical"] and out["score_files_identical"] and out["score_files_identical_expanding"]
                and out["committed_ledger_untouched"] and out["frozen_only"]["identical_to_committed_frozen_rows"]
                and out["frozen_only"]["pre_amendment_ledger_is_prefix"]
                and out["frozen_only"]["state_identical_to_committed_without_extension"])


def main() -> int:
    out = regenerate()
    print(C.dumps({k: v for k, v in out.items() if k not in ("score_files", "score_files_expanding")}))
    return 0 if ok_of(out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
