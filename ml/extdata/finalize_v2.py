#!/usr/bin/env python3
"""Final P3 rebuild on P1's v2 exports.

1. Locates eod_export_v2.parquet and features_prices_export_v2.parquet (in
   ml/data_ext/ or ml/results/improve/cache/) and ml/data_5y_v2/model_dataset.parquet;
   exits with code 2 and a message if any is missing.
2. Keeps the v1-based outputs for the record under *_v1 names (never
   overwrites an existing *_v1 file): extra_features, market_state,
   extra_features_placebo_f2, extra_features_manifest, fo_daily_stock,
   extdata.json, EXTDATA.md.
3. Runs ml/extdata/run_all.py on v2 (adjusted prices for returns/ATR/SMA,
   raw close for the price floor, the F&O spot and the option notional;
   the six special sessions and the re-dated sessions come with the export),
   with the 2016-2021 staging rows and every check, including (a)-(c).

Run: OMP_NUM_THREADS=2 python3 -I ml/extdata/finalize_v2.py [--fast]
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ml.extdata import common as C  # noqa: E402

KEEP = [(C.EXT, "extra_features.parquet", "extra_features_v1.parquet"),
        (C.EXT, "market_state.parquet", "market_state_v1.parquet"),
        (C.EXT, "extra_features_placebo_f2.parquet", "extra_features_placebo_f2_v1.parquet"),
        (C.EXT, "extra_features_manifest.json", "extra_features_v1_manifest.json"),
        (C.EXT, "fo_daily_stock.parquet", "fo_daily_stock_v1.parquet"),
        (C.OUT, "extdata.json", "extdata_v1.json"),
        (C.OUT, "EXTDATA.md", "EXTDATA_v1.md")]


def find(name: str) -> Path | None:
    for d in (C.EXT, C.CACHE):
        if (d / name).exists():
            return d / name
    return None


def main() -> int:
    eod2, fp2 = find("eod_export_v2.parquet"), find("features_prices_export_v2.parquet")
    ds2 = C.ML / "data_5y_v2" / "model_dataset.parquet"
    missing = [n for n, p in (("eod_export_v2.parquet", eod2),
                              ("features_prices_export_v2.parquet", fp2),
                              ("ml/data_5y_v2/model_dataset.parquet", ds2 if ds2.exists() else None))
               if p is None]
    if missing:
        print("v2 inputs missing: " + ", ".join(missing))
        return 2
    log = C.get_logger("extdata.v2")
    for d, src, dst in KEEP:
        if (d / src).exists() and not (d / dst).exists():
            shutil.copy2(d / src, d / dst)
            log.info("kept v1 record %s -> %s", src, dst)
    cmd = [sys.executable, "-I", str(C.ML / "extdata" / "run_all.py"), "--with-history",
           "--eod", str(eod2), "--prices", str(fp2), "--dataset", str(ds2.parent / "model_dataset.parquet"),
           "--tag", "v2"] + (["--fast"] if "--fast" in sys.argv else [])
    log.info("v2 rebuild: %s", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
