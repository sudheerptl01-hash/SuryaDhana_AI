"""Shared helpers of the paper book: logging, deterministic JSON and CSV, hashing."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

from ml.paper.config import LEDGER_DIR, RESULTS_DIR, STATE_DIR

LOG_FILE = RESULTS_DIR / "log.txt"           # gitignored (ml/results/improve2/**/log.txt)
RUNS_FILE = STATE_DIR / "runs.jsonl"         # gitignored: wall-clock record of every run

SIGNALS_COLS = ["signal_date", "book", "ticker", "rank", "score", "weight"]
MARKS_COLS = ["session", "book", "gross_return", "net_return_20bps", "benchmark_return", "exposure",
              "net_return_name_level"]
MONITORS_COLS = ["session", "monitor", "scope", "value", "threshold", "status", "detail"]
LEDGER_FILES = {"signals": LEDGER_DIR / "signals.csv", "marks": LEDGER_DIR / "marks.csv",
                "monitors": LEDGER_DIR / "monitors.csv"}
STATE_JSON = LEDGER_DIR / "state.json"


def log(msg: str, tag: str = "paper") -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} [{tag}] {msg}"
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def _clean(o):
    import numpy as np
    import pandas as pd
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
        return None if not math.isfinite(f) else f
    if isinstance(o, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(o).date())
    if isinstance(o, np.ndarray):
        return [_clean(v) for v in o.tolist()]
    if isinstance(o, Path):
        return str(o)
    return o


def dumps(obj) -> str:
    return json.dumps(_clean(obj), indent=1, ensure_ascii=False) + "\n"


def wjson(path: Path, obj) -> bool:
    """Atomic write; returns True when the bytes changed (a no-op rewrite leaves the file untouched)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = dumps(obj)
    if path.exists() and path.read_text() == txt:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(txt)
    tmp.replace(path)
    return True


def wtext(path: Path, txt: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == txt:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(txt)
    tmp.replace(path)
    return True


def fnum(x, digits: int = 12) -> str:
    """Deterministic number format for the ledger ('' for missing)."""
    if x is None:
        return ""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(f):
        return ""
    if f == 0:
        return "0"
    return f"{f:.{digits}g}"


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def append_rows(path: Path, cols: list[str], rows: list[dict]) -> int:
    """Append-only CSV writer (header written once, LF line ends, no quoting unless needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    if not rows and not new:
        return 0
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    if new:
        w.writerow(cols)
    for r in rows:
        w.writerow([r.get(c, "") for c in cols])
    with open(path, "a", newline="") as fh:
        fh.write(buf.getvalue())
        fh.flush()
        os.fsync(fh.fileno())
    return len(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_frame(df, cols: list[str]) -> str:
    """Order-sensitive SHA-256 of a frame's columns (dates as int64 ns, strings utf-8, floats as float64 bytes)."""
    import numpy as np
    import pandas as pd
    h = hashlib.sha256()
    for c in cols:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            h.update(s.to_numpy(dtype="datetime64[ns]").astype(np.int64).tobytes())
        elif pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            h.update(pd.to_numeric(s, errors="coerce").to_numpy(dtype=np.float64).tobytes())
        else:
            h.update("\x1f".join(s.astype(str).tolist()).encode())
        h.update(c.encode())
    return h.hexdigest()


def ledger_hashes() -> dict:
    out = {}
    for k, p in {**LEDGER_FILES, "state": STATE_JSON}.items():
        out[k] = sha256_file(p) if p.exists() else None
    return out


def repo_rel(p: Path) -> str:
    from ml.paper.config import REPO
    try:
        return str(Path(p).resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def python_info() -> dict:
    import duckdb
    import lightgbm
    import numpy
    import pandas
    try:
        import catboost
        cbv = catboost.__version__
    except Exception:  # noqa: BLE001
        cbv = None
    import sklearn
    return {"python": sys.version.split()[0], "numpy": numpy.__version__, "pandas": pandas.__version__,
            "lightgbm": lightgbm.__version__, "catboost": cbv, "sklearn": sklearn.__version__,
            "duckdb": duckdb.__version__}
