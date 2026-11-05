# Value-Area Breakout → POC Return Study

Run: `scripts/value_area_study.py --sweep` · data 2020-09-16 → 2026-09-25 · 1,278 NSE equities with ≥250 bars.
Regenerate any day with the same command (~40 s). Files here: `events.csv`, `stock_stats.csv`,
`current_state.csv`, `current_setups.csv`, `summary.json`.

## Definitions
- **Profile:** the last 20 trading days (about one month), built only from bars *before* the signal day. Each bar's volume is spread across its high–low range. POC is the highest-volume price; the value area is the band holding 70% of the volume.
- **Event:** the 5 previous closes were inside the value area (the stock was trading in a range), then the close breaks above VAH (UP) or below VAL (DOWN). A stock can't have a new event until the current follow-up window ends.
- **Follow-up:** the next 5 trading days. "POC return" means price traded back to the POC.
- **Chance:** how often this stock reaches a level the same distance away (in ATR) over 5 days on *any* day. This is the bar the effect has to beat, because a POC close by gets hit through ordinary volatility.

## Results (W=20, H=5)
| | UP breakouts | DOWN breakdowns |
|---|---|---|
| Events | 42,482 | 45,448 |
| Returned to POC | **33.0%** | 42.7% |
| Chance | 30.7% | 44.6% |
| Excess | **+2.3 pp (z = +11)** | −1.8 pp (z = −8.5) |
| Avg days in the POC zone (of 5) | 0.67 | 0.87 |
| Median days to first POC touch | 3 | 2 |
| Closed back inside value area | 52% | 58% |

Market-relative return, gross of costs, entering next open vs the equal-weight universe over the same days:

| | UP, hold H days | DOWN, hold H days |
|---|---|---|
| All, H=5 | −0.11% (t −3.4) | −0.01% (t −0.3) |
| Liquid ≥ ₹10 Cr/day, H=5 | **−0.22% (t −5.7)** | −0.04% (t −1.3) |
| Liquid, H=10 | **−0.35% (t −5.8)**, negative in 6 of 7 years | −0.10% (t −2.0) |

The UP excess holds in every window/horizon combination of the sweep (W 10/20/40 × H 5/10: +2.2 to +2.9 pp) and has grown recently: 2024 +3.1 pp, 2025 +5.2 pp, 2026 +7.5 pp.

## What it means
1. **Upside breakouts from a value area fail more often than chance, and buying them underperforms.** This is the only robust effect. In liquid names, a long entered the day after an upside VA break lags the market by about 0.2–0.35% over 1–2 weeks. Best use: a *veto* on new longs (wait for the POC retest instead of chasing the break), not a standalone signal.
2. **Downside breakdowns don't bounce back to POC more than chance.** Buying them for a POC reversion earns nothing versus the market. The +0.12% absolute average trade is just the 2020–26 bull market.
3. **Per-stock "reverter vs holder" labels are noise.** 147 of 2,489 per-stock tests reached p < 0.05, while chance alone would produce about 124. None survives a false-discovery-rate correction. The ranking doesn't carry over in time either: first-half vs second-half Spearman is 0.02 (DOWN) and 0.00 (UP). So stock-specific tendencies should not drive trading; the per-stock table is descriptive only.

## Caveats
- The profile is built from daily bars. A true volume profile needs intraday volume-at-price, which the DB doesn't have. POC/VA here are approximations.
- The fade short on upside breaks is only possible through F&O (single-stock futures). The effect is ~0.22–0.35% gross, which is thin after costs. It needs a walk-forward test before any use.
- Survivorship: the universe is today's listed names.
