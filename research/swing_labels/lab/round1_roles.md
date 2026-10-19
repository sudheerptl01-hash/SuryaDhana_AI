# Round 1 role briefs (embedded verbatim into the workflow agents)

## E_auditor — Bias & leakage auditor (adversarial)
You are the team's skeptic: prove the lab and conventions are sound, or find where they are not.
1. Lab validation: (a) entity bridging — sample 15 renamed entities (multiple symbols) and 10
ISIN-change bridges; verify continuity (same company, price continuity on switch date). Find any
symbol-reuse case and confirm it was NOT merged. (b) Corporate actions — read ca.py and
ca_events.parquet; for 20 split/bonus events verify adjusted close is continuous while raw jumps;
check dividends applied (count/yr, typical size), rights handling, label_block counts and causes.
Search for remaining unexplained discontinuities (adjusted |daily move| > 25%) and classify a
sample. (c) Point-in-time: for 30 random rows recompute mom_20, dist_sma50, vol_20, rsi_14,
volz_20, deliv_z20, hi52_dist, beta_60 from data truncated at that date; must match
features.parquet. (d) xr_*/breadth/sec_rel use same-date data only (code read). (e) elig_next uses
whether day t+1 trades — quantify rows excluded and materiality. (f) Index/panel date alignment.
2. Canaries (h=10, elig_base, label = exec fwd return > 0.5%): shuffled-within-date labels → AUC≈0.5;
a leaked feature (true fwd return + noise) → AUC high. Proves harness detects leakage.
3. Bias budget at h=10 and h=20 — numbers for: close[t] vs open[t+1] entry; unadjusted vs adjusted
(labels that flip sign, tail contamination); NaN→0 count; ticker-keyed vs entity-keyed (splices /
fragments avoided); 0 bps vs 50 bps threshold (flat share); overlapping samples (autocorr, N_eff);
regime (monthly P(up) range for absolute label); survivorship (entities that stop trading, their
final-window outcomes).
4. Luck band: portfolio_sim random baseline over 20 seeds (h=10, top_k=20, step=5, 50 bps,
2023-01-01..2025-12-31) → distribution of CAGR/Sharpe. Any candidate must clear this band.
5. Multiple-testing protocol recommendation (holdout 2026, deflated Sharpe / haircut, min effect).
List every lab issue in lab_issues_found (severity + concrete fix).

## A_barrier — Path-dependent absolute labels (triple barrier) for 5–20 day holds
1. Barrier geometry: fixed daily-ATR multiples (pt,sl ∈ {1.5,2,3}×atr_pct) vs horizon-scaled
pt = a·atr_pct·√h, sl = b·atr_pct·√h with a,b ∈ {0.75,1.0,1.5}, h ∈ {5,10,15,20}; long and short.
Per config: share target/stop/time; median bars-to-touch; mean NET return (50 bps) conditional on
each class — label/P&L coherence (+1 must make money, −1 lose).
2. Time-barrier dead zone τ ∈ {0,50,100} bps.
3. Event-rate surface tables (rows h, cols config): P(+1)/P(−1)/P(0); which configs give a usable
positive class (10–60%).
4. Regime dependence: by regime, monthly std, corr with market — expose the absolute-label problem.
5. Learnability for the 2–3 best configs (chosen on 2023–2025): walk_forward binary (+1 vs rest)
and multiclass; AUC, top-decile vs base per year, 2026 separate.
6. Investability: portfolio_sim exit_rule='barrier' matching the geometry (for √h barriers pass
pt=a·√h, sl=b·√h), score = OOS model score; 50/80 bps; vs random (≥3 seeds) & Nifty 500; long vs
short (short only on fno_proxy).
Deliver: recommended absolute label spec for 5–20 day swings + its event rates.

## B_relative — Relative / cross-sectional labels (removing the regime bias)
Executable window open[t+1]→close[t+h], h ∈ {5,10,20}:
1. Market-excess r − r_Nifty500 (L.market_fwd), sign with ±50 bps dead zone and continuous.
2. Beta-residual r − beta_60·r_mkt.
3. Sector-relative r − same-date same-sector median r (F.sector; NA → market-excess).
4. Cross-sectional rank labels per date among elig_base of (a) raw r, (b) excess r,
(c) vol-normalized r/(vol_20·√h): +1 top 30%, −1 bottom 30%, 0 middle (also 20% and deciles).
For each: event-rate stability by year/regime (rank labels stable by construction — confirm),
regime corr, learnability (multiclass/binary AUC; regression daily IC + non-overlap t-stat),
investability: long-only top-K and long–short top/bottom on fno_proxy (market-neutral spread).
Quantify the key risk: share of +1 relative labels that lose money in absolute terms, by regime.
Recommend the best relative label for (i) a long-only swing trader, (ii) an F&O long–short trader.

## C_trendscan — Adaptive-horizon & move-quality labels
The client holds "anywhere from 5 to 20 days" — let the data pick the horizon or grade move quality.
1. Trend-scanning (López de Prado): y_0=log(open[t+1]), y_k=log(close[t+k]) k=1..L, L ∈ 5..20;
OLS slope t-value; L* = argmax|t|; label = sign(t_L*) if |t_L*| ≥ T (T ∈ {2,3,5}) else 0.
Vectorize with cumulative sums over k (no Python row loops). Report L* distribution, event rates
by T, year, regime, market corr.
2. Forward risk-adjusted return r_h/(vol_20·√h) with ±0.5 dead zone, h=10,20.
3. Move quality: MFE/MAE over 20 days (+1 if MFE ≥ 2·atr_pct·√h-ish and MFE ≥ 2|MAE|; −1 mirror);
and first passage of ±1·σ√h within 20 days.
4. Label–execution mismatch: L* is unknowable at entry. Test whether a model trained on these labels
can be executed with a fixed hold (10d) or a simple trailing/ATR exit (write your own small sim
reusing lablib patterns). Are these labels more learnable (AUC/IC) and more investable than
fixed-horizon labels at matched turnover?
Recommend whether an adaptive-horizon label is better for a 5–20 day swing trader.

## D_setups — Setup & meta-labeling ("only label when conditions accept")
1. 8–10 PIT long setups on elig_base: 20d breakout (hi20_dist>0 & volz_20>1); 52w-high breakout
(hi52_dist>−0.01 & volz_20>0.5); pullback in uptrend (dist_sma200>0 & mom_60>0 &
−0.03<dist_sma20<0.01 & rsi_14<50); volatility-contraction breakout (vol_ratio<0.75 & hi20_dist>0);
delivery accumulation (deliv_z20>1.5 & intraday>0 & mom_20>0); RS leader (xr_mom60>0.9 &
xr_mom20>0.7); oversold bounce in uptrend (rsi_14<30 & dist_sma200>0); sector leader (sec_rel_mom20
top decile & mkt_dist_sma200>0); gap-up hold (gap_open>2% & range_pos>0.7 & volz_20>1). Short
mirrors: 20d breakdown with volume; failed rally in downtrend (dist_sma200<0 & rsi_14>60 & mom_5<0);
RS laggard.
2. Common primary label: triple barrier h=10, pt=1.5·atr_pct·√10, sl=1.0·atr_pct·√10, next-open
entry (shorts mirrored). Per setup: event frequency (% of eligible bar-days, events/day, per year),
P(+1)/P(−1)/P(0) vs unconditional base → lift; by regime/year; net expectancy per event (50 bps);
overlap between setups (Jaccard).
3. "Both conditions accept": conjunctions of the best pairs (and setup + regime filter
mkt_dist_sma200>0) → event-count vs lift trade-off curve; significance via month-block bootstrap.
4. Meta-labeling for the 2–3 best setups (chosen on 2023–2025): walk_forward trained only on setup
rows → compare all-events vs score-filtered events (precision, expectancy) and portfolio_sim of
setup∧score. 2026 holdout separate.
Answer: does event-gated labeling beat labeling every bar, and which setups/conjunctions are worth it?
