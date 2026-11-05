"""The weekly fund-driver label — the SINGLE source of truth (wave 1c, C-TRADER-3 / C-BEGINNER-1 / C-DATA-15).

Pure Python, standard library only, so ui-api (``services/ui-api/routers/gold.py``) can import it or mirror it byte for
byte. Any change here must be mirrored there (``tests/gold/test_wave1c_fixes.py`` pins every case below).

The rule is magnitude-aware — THE LABEL IS THE BIGGER OF THE TWO LEGS — and it never contradicts the net change printed
under it. ΔL / ΔS are managed money's week-on-week changes in long / short contracts, ``dp`` the Tue→Tue price change in %:

    down week (dp < 0):
        "funds bought the dip"  if ΔL − ΔS > 0                      — price fell and the net still ROSE
        "long liquidation"      if ΔL < 0 and |ΔL| ≥ max(ΔS, 0)     — closed longs are the bigger bearish leg
        "new shorts"            otherwise                            — new shorts are the bigger bearish leg
    up week (dp > 0), the mirror:
        "funds sold into it"    if ΔL − ΔS < 0                      — price rose and the net still FELL
        "short covering"        if ΔS < 0 and |ΔS| ≥ max(ΔL, 0)     — covered shorts are the bigger bullish leg
        "new longs"             otherwise                            — new longs are the bigger bullish leg

This is the critics' formula ("long liquidation if ΔL<0 and |ΔL| ≥ max(ΔS,0); new shorts if ΔS>0 and ΔS ≥ max(ΔL,0); else
funds bought the dip", mirrored for the up week) on every case they listed, with the net-sign test placed FIRST. The two
orderings differ in one sub-case per side only: a week in which funds closed both legs and the covered shorts were the
bigger leg (net rose on a down week) — the literal formula says "long liquidation" there, against the three numbers
under it, which is the very contradiction C-BEGINNER-1 flagged ("when price fell and the net still rose, funds bought
the dip"). Testing the net first closes that hole on both sides and matches ui-api's wave-1c rule.

Worked example (the week the critics caught, 27 Oct 2026): ΔL +1,538, ΔS +182, price −1.64 % → the old rule said
"new shorts" because it tested the sign of ΔS before comparing magnitudes; this rule says "funds bought the dip"
(net +1,356). Its mirror (ΔL −1,538, ΔS −182, price up) is "funds sold into it". A tie between the two bearish (bullish)
legs goes to the closing leg, tested first: long liquidation (short covering).

No word without all three inputs, on a week without a price change (dp == 0) or when neither leg moved (ΔL = ΔS = 0):
the page prints the who-did counts alone.
"""
from __future__ import annotations

import math

DOWN_LABELS: tuple[str, str, str] = ("funds bought the dip", "long liquidation", "new shorts")
UP_LABELS: tuple[str, str, str] = ("funds sold into it", "short covering", "new longs")
ALL_LABELS: frozenset[str] = frozenset(DOWN_LABELS + UP_LABELS)
RULE_TEXT = ("down week: funds bought the dip if the net rose; else long liquidation if ΔL<0 and |ΔL| ≥ max(ΔS,0); else new shorts · "
             "up week, mirrored: funds sold into it if the net fell; else short covering if ΔS<0 and |ΔS| ≥ max(ΔL,0); else new longs "
             "— the label is the bigger of the two legs and never contradicts the net change")


def _num(v: object) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def driver_label(price_chg_pct: object, d_long: object, d_short: object) -> str | None:
    """The fund-driver word for one COT week (see the module docstring); None without all three inputs, on dp == 0 or
    when neither leg changed."""
    dp, dl, ds = _num(price_chg_pct), _num(d_long), _num(d_short)
    if dp is None or dl is None or ds is None or dp == 0.0 or (dl == 0.0 and ds == 0.0):
        return None
    net = dl - ds
    if dp < 0:
        if net > 0:
            return DOWN_LABELS[0]
        if dl < 0 and abs(dl) >= max(ds, 0.0):
            return DOWN_LABELS[1]
        return DOWN_LABELS[2]
    if net < 0:
        return UP_LABELS[0]
    if ds < 0 and abs(ds) >= max(dl, 0.0):
        return UP_LABELS[1]
    return UP_LABELS[2]
