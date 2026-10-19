"""Shared helpers for the E_auditor scripts."""
import json
import os
import sys

import numpy as np

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "E_auditor")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402,F401

RES = os.path.join(OUT, "results.json")


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if f != f else f
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if hasattr(o, "isoformat"):
        return str(o)[:10]
    return o


def save(section, obj):
    """Merge one section into results.json (survives interruption)."""
    d = {}
    if os.path.exists(RES):
        with open(RES) as fh:
            d = json.load(fh)
    d[section] = _clean(obj)
    with open(RES, "w") as fh:
        json.dump(d, fh, indent=1, default=str)
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}
