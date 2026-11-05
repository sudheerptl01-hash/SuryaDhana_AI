#!/usr/bin/env python
"""Batched, memory-safe Phase 3 feature generation.

Replicates the ui-api HTTP feature pipeline (data-service OHLCV -> feature-service
/calculate/features -> forward-5d labels) but writes parquet INCREMENTALLY, one
batch at a time, via a single pyarrow.ParquetWriter. It never holds the full
~1.04M-row universe in RAM, so it can't OOM the way the in-process ui-api task did.

Output is written to <data>/computed_features.parquet and computed_labels.parquet
ATOMICALLY (temp file -> os.replace) so a mid-run failure can never corrupt the
existing artifacts. Runs against the live, healthy services on localhost.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DATA_SVC = os.getenv("DATA_SVC_URL", "http://localhost:8001")
FEAT_SVC = os.getenv("FEAT_SVC_URL", "http://localhost:8002")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FEATURES_PARQUET = DATA_DIR / "computed_features.parquet"
LABELS_PARQUET = DATA_DIR / "computed_labels.parquet"
FEAT_TMP = DATA_DIR / "computed_features.parquet.tmp"
LBL_TMP = DATA_DIR / "computed_labels.parquet.tmp"

BATCH = int(os.getenv("BATCH_SIZE", "100"))
MIN_ROWS = 60          # mirror pipeline: skip tickers with < 60 bars
HORIZON = 5            # 5-day forward label horizon
TIMEOUT = 120


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return json.load(r)


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def main() -> int:
    t0 = time.time()
    tickers = [row["ticker"] for row in _get(f"{DATA_SVC}/db/ohlcv-meta").get("data", [])]
    total = len(tickers)
    print(f"[init] universe={total} tickers  batch={BATCH}  out={DATA_DIR}", flush=True)

    state = {
        "feat_writer": None, "lbl_writer": None,
        "feat_schema": None, "lbl_schema": None,
        "feat_dtypes": None, "lbl_dtypes": None,
        "n_feat": 0, "n_lbl": 0,
    }
    feat_batch: list[dict] = []
    lbl_batch: list[dict] = []
    errors = 0
    skipped = 0

    def flush() -> None:
        # Features
        if feat_batch:
            df = pd.DataFrame(feat_batch)
            if state["feat_schema"] is None:
                state["feat_dtypes"] = df.dtypes
                table = pa.Table.from_pandas(df, preserve_index=False)
                state["feat_schema"] = table.schema
                state["feat_writer"] = pq.ParquetWriter(str(FEAT_TMP), table.schema)
            else:
                df = df.reindex(columns=[f.name for f in state["feat_schema"]])
                df = df.astype(state["feat_dtypes"], errors="ignore")
                table = pa.Table.from_pandas(df, schema=state["feat_schema"], preserve_index=False)
            state["feat_writer"].write_table(table)
            state["n_feat"] += len(df)
            feat_batch.clear()
        # Labels
        if lbl_batch:
            df = pd.DataFrame(lbl_batch)
            if state["lbl_schema"] is None:
                state["lbl_dtypes"] = df.dtypes
                table = pa.Table.from_pandas(df, preserve_index=False)
                state["lbl_schema"] = table.schema
                state["lbl_writer"] = pq.ParquetWriter(str(LBL_TMP), table.schema)
            else:
                df = df.reindex(columns=[f.name for f in state["lbl_schema"]])
                df = df.astype(state["lbl_dtypes"], errors="ignore")
                table = pa.Table.from_pandas(df, schema=state["lbl_schema"], preserve_index=False)
            state["lbl_writer"].write_table(table)
            state["n_lbl"] += len(df)
            lbl_batch.clear()

    for i, ticker in enumerate(tickers, 1):
        try:
            oh = _get(f"{DATA_SVC}/ohlcv/{ticker}?limit=1500").get("data", [])
            if len(oh) < MIN_ROWS:
                skipped += 1
            else:
                feats = _post(f"{FEAT_SVC}/calculate/features",
                              {"ticker": ticker, "ohlcv": oh}).get("features", [])
                for row in feats:
                    row["ticker"] = ticker
                    feat_batch.append(row)

                df = pd.DataFrame(oh)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df.sort_values("date").reset_index(drop=True)
                fut = df["close"].shift(-HORIZON)
                lab_dir = (fut > df["close"]).astype(float)
                lab_ret = (fut - df["close"]) / df["close"] * 100.0
                mask = lab_ret.notna()
                for d, ld, lr in zip(df.loc[mask, "date"], lab_dir[mask], lab_ret[mask]):
                    lbl_batch.append({
                        "ticker": ticker, "date": str(d)[:10],
                        "label_direction": int(ld), "label_return_pct": float(lr),
                    })
        except Exception as exc:  # noqa: BLE001 - per-ticker isolation
            errors += 1
            if errors <= 10:
                print(f"  [warn] {ticker}: {exc}", flush=True)

        if i % BATCH == 0:
            flush()
            print(f"[{i}/{total}] feat_rows={state['n_feat']:,} lbl_rows={state['n_lbl']:,} "
                  f"skipped={skipped} errors={errors} elapsed={time.time() - t0:.0f}s", flush=True)

    flush()  # final partial batch
    if state["feat_writer"]:
        state["feat_writer"].close()
    if state["lbl_writer"]:
        state["lbl_writer"].close()

    # Atomic publish — only replace if we actually produced rows.
    if state["n_feat"] > 0 and FEAT_TMP.exists():
        os.replace(FEAT_TMP, FEATURES_PARQUET)
    if state["n_lbl"] > 0 and LBL_TMP.exists():
        os.replace(LBL_TMP, LABELS_PARQUET)

    print(f"[done] feat_rows={state['n_feat']:,} lbl_rows={state['n_lbl']:,} "
          f"skipped={skipped} errors={errors} elapsed={time.time() - t0:.0f}s", flush=True)
    print(f"[saved] {FEATURES_PARQUET}", flush=True)
    print(f"[saved] {LABELS_PARQUET}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
