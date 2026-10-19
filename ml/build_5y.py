#!/usr/bin/env python3
"""Build the 5-year modeling dataset (ml/data_5y/, gitignored).

Same features, labels and universe filter as the pilot (ml/data.py); only
the window and the split layout change:
  * rows from 2022-10-03 -- one year after the Oct-2021 start of the
    ingested history, so the 252-session features are populated;
  * one purged walk-forward fold per calendar month, 2023-01 .. 2026-07
    (43 folds, 22-session embargo), training on all labeled rows before
    each fold's embargo -- an expanding window;
  * holdout 2026-08-01 .. last labeled date, used once.

Run after the 5-year ingest: cd /home/user/SuryaDhana_AI && python3 -m ml.build_5y
"""
from pathlib import Path

from ml.data import REPO, build_dataset

OUT = Path(__file__).resolve().parent / "data_5y"
FOLDS = [(y, m) for y in (2023, 2024, 2025) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]

if __name__ == "__main__":
    manifest = build_dataset(db_path=str(REPO / "nse_market.duckdb"), dataset_start="2022-10-03",
                             fold_months=FOLDS, holdout_start="2026-08-01", out_dir=OUT)
    print({k: manifest[k] for k in ("rows", "tickers", "date_min", "date_max")})
