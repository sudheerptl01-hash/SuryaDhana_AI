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
from ml.extdata import history as H  # noqa: E402
from ml.extdata import lists as L  # noqa: E402
from ml.extdata import parse as P  # noqa: E402
from ml.extdata import report as R  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the point-in-time checks")
    ap.add_argument("--pit-month", default="2024-07")
    ap.add_argument("--reuse-json", action="store_true",
                    help="keep PIT results from an existing extdata.json")
    ap.add_argument("--with-history", action="store_true",
                    help="also parse the 2016-10..2021-09 files into the staging tables")
    ap.add_argument("--eod", default=str(C.EOD_EXPORT),
                    help="equity_eod export: raw spot close, sessions, universe turnover")
    ap.add_argument("--prices", default=None,
                    help="features_prices export with adjusted prices + close_unadj (v2)")
    ap.add_argument("--dataset", default=str(C.V1_DATASET),
                    help="model dataset for the base cross-check and the reporting-only ICs")
    ap.add_argument("--tag", default="v1")
    a = ap.parse_args()
    K.configure(eod=a.eod, prices=a.prices, dataset=a.dataset, tag=a.tag)
    eod_path, prices_path = Path(a.eod), (Path(a.prices) if a.prices else None)
    log = C.get_logger("extdata.run")
    t0 = time.perf_counter()
    out: dict = {"stream": "P3 external data (ml/IMPROVEMENT_PLAN.md section 2-P3)",
                 "built_at": datetime.now().isoformat(timespec="seconds"),
                 "seed": C.SEED, "tag": a.tag,
                 "inputs": {"eod_export": str(eod_path), "prices_export": str(prices_path),
                            "dataset": a.dataset}}

    log.info("parse: start (with_history=%s)", a.with_history)
    if a.with_history:
        hs, hs_src = H.hist_spot()
        rep = P.run(min_date=None, hist_spot=hs, eod_path=eod_path)
    else:
        rep = P.run(eod_path=eod_path)
    fo, idx, part = rep.pop("_frames")
    out["parse"] = rep
    log.info("parse: fo rows %d, index rows %d, participant rows %d", len(fo), len(idx), len(part))

    out["staging_schemas"] = {
        "fo_daily_stock.parquet": {c: str(t) for c, t in fo.dtypes.items()},
        "index_daily.parquet": {c: str(t) for c, t in idx.dtypes.items()},
        "fo_participant_oi.parquet": {c: str(t) for c, t in part.dtypes.items()},
        "fo_participant_oi_column_map": P.PART_NUMERIC,
        "fo_participant_oi_layout": "one row per (date, client_type); client_type in Client, DII, "
                                    "FII, Pro, TOTAL; the 14 numeric columns are contracts",
        "units": {"fut_oi_total, opt_call_oi, opt_put_oi": "shares (underlying quantity) in both "
                  "F&O formats", "fut_volume_contracts, opt_call_volume, opt_put_volume":
                  "contracts", "fut_turnover": "rupees", "spot_close": "rupees (EOD export close)",
                  "basis_near": "annualised fraction"},
        "roll_convention": ("near = smallest expiry >= date (the expiring contract is still near "
                            "on its expiry day, days_to_expiry 0); next = second smallest; "
                            "calendar days; UDiFF expiry = FininstrmActlXpryDt")}
    ind, ind_info = L.build_industry_map()
    out["industry_map"] = ind_info
    out["equity_master"] = L.build_equity_master()
    smap, smap_info = L.verify_sector_map(idx)
    out["sector_index_map"] = {"rows": smap.to_dict(orient="records"), **smap_info}

    log.info("features: start")
    res = F.build(eod_path, write=True, prices_path=prices_path)
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
    out["size_proxy_diagnostic"] = K.size_proxy_diag(res)
    log.info("checks: partition identifiability (leak-safe vs literal brief)")
    lit = F.build(eod_path, write=False, prices_path=prices_path,
                  policy={"unclassified": "nan", "secidx_unmapped": "nan"})
    out["partition_identifiability"] = {"leak_safe": K.partition_identifiability(res),
                                        "literal_brief": K.partition_identifiability(lit)}
    out["literal_brief_secidx_nan_indicator"] = \
        K.survivorship_diag(lit)["secidx_ret_20_nan_indicator"]
    del lit
    log.info("placebo F2 (industry labels permuted among classified symbols, seed %d)", C.SEED)
    plc = F.build(eod_path, write=False, prices_path=prices_path,
                  industry_map=F.placebo_industry_map())
    assert list(plc["extra"].columns) == list(res["extra"].columns), "placebo columns differ"
    plc["extra"].to_parquet(C.EXT / "extra_features_placebo_f2.parquet", index=False)
    out["placebo_f2"] = {"path": "ml/data_ext/extra_features_placebo_f2.parquet",
                         "rows": int(len(plc["extra"])),
                         "construction": ("industry column of industry_map.csv permuted among its "
                                          f"symbols (numpy default_rng({C.SEED})); same Unclassified "
                                          "and ETF groups, same coverage; F3 columns identical"),
                         "status": "not a registered trial; for the lead's decision"}
    del plc

    if a.with_history:
        out["history_extension"] = {"spot_source": hs_src, **H.hist_coverage(fo, idx, part)}

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
