"""Shared paths, seed, logging, JSON output and the dependence-robust statistics of the P5 stream.

The Newey-West t and the circular moving-block bootstrap reproduce the formulas of
ml/scale5y_report.py (nw_t, _block_counts_within, ci) so that every interval in this
stream is computed the same way as the five-year report's.  They are re-implemented
here rather than imported so that nothing in this package can reach the DuckDB.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ML_DIR = REPO / "ml"
DATA_5Y = ML_DIR / "data_5y"                      # frozen v1 dataset (read-only)
SCALE = ML_DIR / "results" / "scale5y"            # frozen five-year results (read-only)
CACHE5Y = SCALE / "cache"
OUT = ML_DIR / "results" / "improve" / "hygiene"
LOG_FILE = OUT / "log.txt"

SEED = 108
BLOCK = 20          # sessions per bootstrap block (ml/scale5y_report.py BLOCK)
NW_LAG = 20         # Newey-West lags (ml/scale5y_report.py NW_LAG)
B_BOOT = 1000

MODELS9 = ["all51", "nested_lgbm", "nested_lr_l2", "lr_l2", "champion10", "baseline_mom",
           "nested_ensemble_rank", "nested_catboost", "nested_lambdarank"]


def log(msg: str, tag: str = "p5") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{tag}] {msg}"
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


def wjson(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), indent=1, allow_nan=False))
    tmp.replace(path)


def sha256(path: Path, limit_mb: int | None = None) -> str:
    """sha256 of a file (first `limit_mb` MB only when given, for very large inputs)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        if limit_mb is None:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        else:
            h.update(fh.read(limit_mb << 20))
    return h.hexdigest()


def input_record(path: Path, full_hash: bool = True) -> dict:
    st = path.stat()
    return {"path": str(path.relative_to(REPO)), "bytes": int(st.st_size),
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "sha256" if full_hash else "sha256_first_64MB": sha256(path, None if full_hash else 64)}


# --------------------------------------------------------------------------------------------- #
# dependence-robust statistics (formulas of ml/scale5y_report.py)
# --------------------------------------------------------------------------------------------- #
def nw_t(x: np.ndarray, L: int = NW_LAG) -> float:
    """Mean / Newey-West (Bartlett, L lags) standard error; ml/scale5y_report.py nw_t."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    T = len(x)
    if T < 3:
        return float("nan")
    e = x - x.mean()
    s = e @ e / T
    for l in range(1, min(L, T - 1) + 1):
        s += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / T
    return float(x.mean() / math.sqrt(s / T)) if s > 0 else float("nan")


def nw_var_of_mean(x: np.ndarray, L: int = NW_LAG) -> float:
    """Newey-West variance of the sample mean (same kernel as nw_t)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    T = len(x)
    e = x - x.mean()
    s = e @ e / T
    for l in range(1, min(L, T - 1) + 1):
        s += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / T
    return float(s / T)


def block_index(n: int, B: int = B_BOOT, L: int = BLOCK, seed: int = SEED) -> np.ndarray:
    """(B, n) positions of a circular moving-block bootstrap: ceil(n/L) blocks of L consecutive
    positions per replicate, starts uniform on [0, n), wrapped modulo n, truncated to n
    (ml/scale5y_report.py _block_counts_within / ic_block)."""
    rng = np.random.default_rng(seed)
    k = int(math.ceil(n / L))
    starts = rng.integers(0, n, size=(B, k))
    return ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(B, -1)[:, :n]


def ci95(x) -> list:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [float("nan"), float("nan")]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def block_boot_means(x: np.ndarray, B: int = B_BOOT, L: int = BLOCK, seed: int = SEED) -> np.ndarray:
    """B bootstrap replicates of the mean of the chronological series x (NaNs ignored)."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return np.full(B, np.nan)
    idx = block_index(len(x), B, L, seed)
    return x[idx].mean(1)
