#!/usr/bin/env python3
"""P3 pipeline: parse -> lists -> features -> checks -> extdata.json + EXTDATA.md.

Run from the repo root (nothing runs from inside the download folders):

    OMP_NUM_THREADS=2 python3 -I ml/extdata/run_all.py            # everything
    OMP_NUM_THREADS=2 python3 -I ml/extdata/run_all.py --fast     # skip (a)-(c)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd  # noqa: E402

from ml.extdata import checks as K  # noqa: E402
from ml.extdata import common as C  # noqa: E402
from ml.extdata import features as F  # noqa: E402
from ml.extdata import lists as L  # noqa: E402
from ml.extdata import parse as P  # noqa: E402
from ml.extdata import report as R  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the point-in-time checks")
    ap.add_argument("--pit-month", default="2024-07")
    ap.add_argument("--reuse-json", action="store_true",
                    help="keep PIT results from an existing extdata.json")
    a = ap.parse_args()
    log = C.get_logger("extdata.run")
    t0 = time.perf_counter()
    out: dict = {"stream": "P3 external data (ml/IMPROVEMENT_PLAN.md section 2-P3)",
                 "built_at": datetime.now().isoformat(timespec="seconds"),
                 "seed": C.SEED}

    log.info("parse: start")
    rep = P.run()
    fo, idx, part = rep.pop("_frames")
    out["parse"] = rep
    log.info("parse: fo rows %d, index rows %d, participant rows %d", len(fo), len(idx), len(part))

    ind, ind_info = L.build_industry_map()
    out["industry_map"] = ind_info
    out["equity_master"] = L.build_equity_master()
    smap, smap_info = L.verify_sector_map(idx)
    out["sector_index_map"] = {"rows": smap.to_dict(orient="records"), **smap_info}

    log.info("features: start")
    res = F.build(write=True)
    out["features_build"] = res["info"]
    out["families"] = F.FAMILIES
    out["definitions"] = F.DEFINITIONS
    log.info("features: %d rows, %d market-state dates", len(res["extra"]),
             len(res["market_state"]))

    out["coverage"] = K.coverage(fo, idx, part, res)
    out["fo_unit_continuity"] = K.unit_continuity()
    out["fo_symbol_match"] = K.symbol_match(fo)
    out["participant_identity"] = K.participant_identity(part)
    out["basis_sanity"] = K.basis_sanity(fo)
    out["base_crosscheck_v1"] = K.base_crosscheck(res)
    out["nan_share"] = K.nan_shares(res)
    log.info("checks: descriptive IC")
    out["monthly_ic_descriptive"] = K.monthly_ic(res)
    out["industry_survivorship_diagnostic"] = K.survivorship_diag(res)

    old = {}
    jpath = C.OUT / "extdata.json"
    if a.reuse_json and jpath.exists():
        old = json.loads(jpath.read_text())
    if not a.fast:
        log.info("PIT (a): independent recomputation")
        out["pit_a_recompute_cells"] = K.pit_recompute_cells(res)
        log.info("PIT (a): passed=%s", out["pit_a_recompute_cells"]["passed"])
        log.info("PIT (b): month truncation %s", a.pit_month)
        out["pit_b_month_truncation"] = K.pit_month_truncation(res, a.pit_month)
        log.info("PIT (b): passed=%s", out["pit_b_month_truncation"]["passed"])
        log.info("PIT (c): shift test")
        out["pit_c_shift_test"] = K.pit_shift_test(res)
        log.info("PIT (c): passed=%s", out["pit_c_shift_test"]["passed"])
    else:
        for k in ("pit_a_recompute_cells", "pit_b_month_truncation", "pit_c_shift_test"):
            if k in old:
                out[k] = old[k]
    out["seconds"] = round(time.perf_counter() - t0, 1)
    jpath.write_text(json.dumps(out, indent=1, default=K._jsonable))
    R.write_markdown(out)
    log.info("wrote %s and EXTDATA.md (%.0f s)", jpath, out["seconds"])


if __name__ == "__main__":
    main()
