"""
Indian cash-equity transaction-cost and capital-gains-tax model (NSE).

One source of truth for what a trade really costs. It replaces the flat 0.15%
assumption scattered across the repo, which understated a retail delivery
round trip by ~6× (see docs/PRODUCT_STRATEGY.md §1).

Statutory charges are set by law or by the exchange and are the same at every
broker. Broker charges (brokerage %, flat fee, minimum, DP charge) depend on
your plan: pick a profile with COST_PROFILE and/or override single values from
your contract note with COST_BROKERAGE_DELIVERY_PCT / COST_DP_CHARGE /
COST_MIN_BROKERAGE / COST_FLAT_PER_ORDER.

All rates are in percent of traded value unless the name says ₹.
Rates as of 2026-09; verify against a contract note and update STATUTORY_AS_OF.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Literal, Optional

Side = Literal["buy", "sell"]
Product = Literal["delivery", "intraday"]

STATUTORY_AS_OF = "2026-09"


@dataclass(frozen=True)
class Statutory:
    """Charges fixed by law or by the exchange (identical at every broker)."""
    stt_delivery_pct: float = 0.1          # on buy AND sell
    stt_intraday_sell_pct: float = 0.025   # sell side only
    stamp_delivery_buy_pct: float = 0.015  # buy side only
    stamp_intraday_buy_pct: float = 0.003
    exchange_txn_pct: float = 0.00322      # NSE cash, both sides
    sebi_fee_pct: float = 0.0001           # ₹10 per crore, both sides
    ipft_pct: float = 0.0001               # NSE investor-protection fund, ₹10 per crore
    gst_pct: float = 18.0                  # on brokerage + exchange + SEBI + IPFT + DP


@dataclass(frozen=True)
class BrokerProfile:
    name: str
    delivery_brokerage_pct: float           # per leg, % of trade value
    intraday_brokerage_pct: float
    flat_per_order: float = 0.0             # ₹ per executed order (flat-fee plans); replaces % if > 0
    min_brokerage: float = 0.0              # ₹ minimum per order
    dp_charge: float = 0.0                  # ₹ per scrip per delivery-sell day (before GST)
    one_time_fee: float = 0.0               # ₹ plan subscription (before GST), for break-even maths
    note: str = ""


PROFILES: dict[str, BrokerProfile] = {
    # ICICI Direct equity plans, from icicidirect.com/brokerage (checked 2026-09-27).
    # Delivery brokerage is set by the base plan (MoneySaver or a Prime tier); the iValue
    # add-on only makes intraday/F&O ₹20 per order and does not change delivery. Prime
    # plans are one-time and lifetime; no minimum brokerage for subscriptions after
    # 2022-11-17. DP: ₹20 + GST per scrip sold (NSDL and CDSL).
    "icici_moneysaver": BrokerProfile("icici_moneysaver", delivery_brokerage_pct=0.29,
                                      intraday_brokerage_pct=0.029, dp_charge=20.0,
                                      note="ICICI Direct MoneySaver (default plan): 0.29% delivery"),
    "icici_prime_999": BrokerProfile("icici_prime_999", delivery_brokerage_pct=0.22, intraday_brokerage_pct=0.022,
                                     dp_charge=20.0, one_time_fee=999,
                                     note="ICICI Prime ₹999 one-time: 0.22% delivery"),
    "icici_prime_4999": BrokerProfile("icici_prime_4999", delivery_brokerage_pct=0.10, intraday_brokerage_pct=0.010,
                                      dp_charge=20.0, one_time_fee=4999,
                                      note="ICICI Prime ₹4,999 one-time: 0.10% delivery"),
    "icici_prime_9999": BrokerProfile("icici_prime_9999", delivery_brokerage_pct=0.07, intraday_brokerage_pct=0.007,
                                      dp_charge=20.0, one_time_fee=9999,
                                      note="ICICI Prime ₹9,999 one-time: 0.07% delivery"),
    # Typical zero-delivery-brokerage discount broker (for comparison)
    "discount_zero": BrokerProfile("discount_zero", delivery_brokerage_pct=0.0, intraday_brokerage_pct=0.03,
                                   dp_charge=13.5, note="Zero delivery brokerage, ~₹13.5 DP per scrip"),
}


@dataclass
class CostBreakdown:
    """Itemised ₹ charges for one or more legs."""
    trade_value: float = 0.0
    brokerage: float = 0.0
    stt: float = 0.0
    stamp: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    ipft: float = 0.0
    dp: float = 0.0
    gst: float = 0.0
    legs: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.brokerage + self.stt + self.stamp + self.exchange + self.sebi + self.ipft
                     + self.dp + self.gst, 4)

    def pct_of(self, notional: float) -> float:
        return self.total / notional * 100 if notional > 0 else float("nan")

    def __add__(self, o: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(
            trade_value=self.trade_value + o.trade_value,
            **{k: getattr(self, k) + getattr(o, k)
               for k in ("brokerage", "stt", "stamp", "exchange", "sebi", "ipft", "dp", "gst")},
            legs=self.legs + o.legs)

    def as_dict(self) -> dict:
        d = {k: round(getattr(self, k), 2) for k in
             ("trade_value", "brokerage", "stt", "stamp", "exchange", "sebi", "ipft", "dp", "gst")}
        d["total"] = round(self.total, 2)
        return d


# ── model ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CostModel:
    broker: BrokerProfile
    statutory: Statutory = Statutory()

    def leg(self, value: float, side: Side, product: Product = "delivery") -> CostBreakdown:
        """Charges for one executed order of `value` ₹. DP applies to delivery sells
        once per scrip per day — pass one leg per scrip."""
        s, b = self.statutory, self.broker
        pct = b.delivery_brokerage_pct if product == "delivery" else b.intraday_brokerage_pct
        brokerage = b.flat_per_order if b.flat_per_order > 0 else value * pct / 100
        if brokerage > 0:
            brokerage = max(brokerage, b.min_brokerage)
        if product == "delivery":
            stt = value * s.stt_delivery_pct / 100
            stamp = value * s.stamp_delivery_buy_pct / 100 if side == "buy" else 0.0
            dp = b.dp_charge if side == "sell" else 0.0
        else:
            stt = value * s.stt_intraday_sell_pct / 100 if side == "sell" else 0.0
            stamp = value * s.stamp_intraday_buy_pct / 100 if side == "buy" else 0.0
            dp = 0.0
        exch = value * s.exchange_txn_pct / 100
        sebi = value * s.sebi_fee_pct / 100
        ipft = value * s.ipft_pct / 100
        gst = (brokerage + exch + sebi + ipft + dp) * s.gst_pct / 100
        return CostBreakdown(trade_value=value, brokerage=brokerage, stt=stt, stamp=stamp, exchange=exch,
                             sebi=sebi, ipft=ipft, dp=dp, gst=gst, legs=[f"{product}-{side}"])

    def round_trip(self, value: float, product: Product = "delivery") -> CostBreakdown:
        """Buy then sell the same ₹ value (price change ignored: cost of the round trip itself)."""
        return self.leg(value, "buy", product) + self.leg(value, "sell", product)

    def round_trip_pct(self, value: float, product: Product = "delivery") -> float:
        return self.round_trip(value, product).pct_of(value)

    def breakeven_move_pct(self, value: float, product: Product = "delivery") -> float:
        """Gross price move needed just to cover costs on a position of `value` ₹."""
        return self.round_trip_pct(value, product)

    def min_position_for(self, max_round_trip_pct: float, product: Product = "delivery") -> Optional[float]:
        """Smallest position (₹) whose round-trip cost is ≤ `max_round_trip_pct`.
        None if the percentage part alone already exceeds the target."""
        big = self.round_trip_pct(1e9, product)            # ≈ proportional part only
        if big >= max_round_trip_pct:
            return None
        lo, hi = 1.0, 1e9
        for _ in range(100):
            mid = (lo + hi) / 2
            if self.round_trip_pct(mid, product) <= max_round_trip_pct:
                hi = mid
            else:
                lo = mid
        return round(hi, 0)

    def annual_drag_pct(self, capital: float, n_positions: int, rebalances_per_year: float,
                        turnover_per_rebalance: float, product: Product = "delivery") -> float:
        """Yearly cost as % of capital for an equal-weight book: each rebalance replaces
        `turnover_per_rebalance` (0–1) of the positions with a full round trip."""
        pos = capital / n_positions
        trips = n_positions * turnover_per_rebalance * rebalances_per_year
        return trips * self.round_trip(pos, product).total / capital * 100


def profile_from_env(env: Optional[dict] = None) -> BrokerProfile:
    """COST_PROFILE picks a preset; single COST_* variables override its values."""
    env = env if env is not None else os.environ
    base = PROFILES.get(env.get("COST_PROFILE", "icici_moneysaver").strip().lower())
    if base is None:
        raise ValueError(f"unknown COST_PROFILE {env.get('COST_PROFILE')!r}; choose one of {sorted(PROFILES)}")
    overrides = {}
    for var, fld in (("COST_BROKERAGE_DELIVERY_PCT", "delivery_brokerage_pct"),
                     ("COST_BROKERAGE_INTRADAY_PCT", "intraday_brokerage_pct"),
                     ("COST_FLAT_PER_ORDER", "flat_per_order"), ("COST_MIN_BROKERAGE", "min_brokerage"),
                     ("COST_DP_CHARGE", "dp_charge")):
        if env.get(var, "").strip():
            overrides[fld] = float(env[var])
    if overrides:
        base = replace(base, name=f"{base.name}+calibrated", **overrides)
    return base


def default_model() -> CostModel:
    return CostModel(profile_from_env())


# ── capital-gains tax (listed equity, STT paid; Finance Act 2024 rates) ─────────

@dataclass(frozen=True)
class TaxRules:
    stcg_pct: float = 20.0                  # held ≤ 12 months
    ltcg_pct: float = 12.5                  # held > 12 months, above the exemption
    ltcg_exemption: float = 125_000.0       # per financial year
    cess_pct: float = 4.0                   # health & education cess on the tax
    long_term_after_days: int = 365
    as_of: str = "FY2025-26 (effective 2024-07-23)"


def capital_gains_tax(gain: float, holding_days: int, ltcg_exemption_left: float,
                      rules: TaxRules = TaxRules()) -> tuple[float, float]:
    """(tax ₹, exemption used ₹) on one realised gain. Losses return (0, 0); set-off
    and carry-forward belong to the ledger. Surcharge is excluded (income-dependent)."""
    if gain <= 0:
        return 0.0, 0.0
    if holding_days > rules.long_term_after_days:
        used = min(gain, max(ltcg_exemption_left, 0.0))
        tax = (gain - used) * rules.ltcg_pct / 100
    else:
        used, tax = 0.0, gain * rules.stcg_pct / 100
    return round(tax * (1 + rules.cess_pct / 100), 2), used
