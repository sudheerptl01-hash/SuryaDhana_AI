"""The drivers metric registry (badge per number the MEMB / MOV / DESK panels may render; the gold "no row, no panel" rule).
Members / sectors / concentration are an identity (``arithmetic``, residual shown); the regime, breadth and the monthly leader
are ``context`` — never coloured, never a direction, every sentence ends "describes, does not predict"."""
from __future__ import annotations

from typing import Any

DESCRIBES = "describes, does not predict"
BADGES = ("signal", "context", "arithmetic", "heuristic")


def _s(series_id: str, name: str, table: str, column: str, badge: str, definition: str, precedent: str, *, unit: str = "index points",
       note: str | None = None) -> dict[str, Any]:
    assert badge in BADGES and badge != "signal", series_id
    return {"series_id": series_id, "name": name, "table": table, "column": column, "badge": badge, "unit": unit, "definition": definition,
            "precedent": precedent, "verdict": "PUBLISH-CORE" if badge == "arithmetic" else "PUBLISH-CONTEXT", "note": note,
            "verdict_sentence": f"{name}: {DESCRIBES}"}


def build_rows() -> list[dict[str, Any]]:
    return [
        _s("MEMBER_POINTS", "Points per member", "index_contribution_daily", "points", "arithmetic",
           "L_{d−1} × w_i,d × r_i,d, additive across days (any horizon is a slice)", "Bloomberg MEMB / IMAP"),
        _s("MEMBER_WEIGHT", "Weight (rebuilt, calibrated)", "index_weights_daily", "weight_pct", "arithmetic",
           "shares (XBRL, filed_at ≤ d) × prev close × (1 − promoter %), calibrated to NSE's top-10 file", "NSE top-10 weights file", unit="%",
           note="display-only posture for NSE's file (O-T11)"),
        _s("FIT_RESIDUAL", "Attribution residual", "index_contribution_fit", "residual_points", "arithmetic", "actual index move − Σ member points",
           "—", note="MAE > 25 pts over 60 sessions → fit.degraded"),
        _s("SECTOR_POINTS", "Sector contribution", "index_contribution_daily", "points", "arithmetic", "Σ member points by NSE industry", "Bloomberg IMAP"),
        _s("TOP5_SHARE", "Top-5 share of |points|", "index_driver_state", "top5_share", "arithmetic", "Σ of the five largest |points| ÷ Σ|points| over the window",
           "—", unit="share"),
        _s("EFFECTIVE_N", "Effective number of names", "index_driver_state", "effective_n", "arithmetic", "1 ÷ Σ weight²", "—", unit="names"),
        _s("DRIVER_LEADER", "Driver leader (hysteresis)", "index_driver_state", "leader", "context",
           "largest |rolling points| name; a challenger replaces it only after 5 consecutive sessions ≥ 1.3× (20 s) / 1.2× (60 s)", "—",
           unit="symbol", note="no colour on the leader"),
        _s("BREADTH_EW_MINUS_CW", "Breadth: equal-weight minus cap-weight", "index_driver_state", "ew_minus_cw_pp", "context",
           "EW member return − index return over the window; narrow < −1 pp, broad > +1 pp (thresholded words, no colour)", "—", unit="pp"),
        _s("MONTHLY_LEADER", "Monthly leader", "index_contribution_daily", "points", "context", "largest |Σ points| in the calendar month", "—", unit="symbol"),
    ]
