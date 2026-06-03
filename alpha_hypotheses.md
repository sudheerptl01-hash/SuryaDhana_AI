# SuryaDhana Alpha Hypotheses — Phase 1 (Alpha Mining Sprint)

**Author:** Agent 1 — Principal Quantitative Researcher
**Date:** 2026-06-03
**Data source (sole, read-only):** `/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/market.duckdb`, table `ohlcv`.
**Universe:** Full NSE universe in `ohlcv` = 1,496 distinct tickers; mined exhaustively. No `^NSEI` / `NIFTY500` present (already absent). Index-like symbols in the DB are tradeable ETFs and are retained unless an individual hypothesis says otherwise.
**Holding horizon mandate:** every strategy holds **2–15 trading days** (swing band).

---

## 0. Preamble — Shared Definitions, Conventions, and Data Contract

These definitions are referenced by every hypothesis. Downstream agents (Risk, Backend, UI) must treat this section as the canonical contract.

### 0.1 Data integrity rules (verified against `ohlcv`)
- **Returns** (overnight, multi-day, forward) are computed from `adjusted_close` (back-adjusted for splits/dividends; the only place corporate actions live — `splits`/`dividends` tables are empty).
- **Intraday range/gap signatures** of the form `(high − low)/close` or `(close − open)/open` are computed from **raw** OHLC, because the per-day adjustment factor cancels in a same-day ratio. Never mix raw and adjusted in a single return.
- Filter `volume > 0` (≈8.7k halt/illiquid rows exist). OHLC is integrity-clean (0 high<low, 0 nulls).
- **No look-ahead:** every quantity in an Entry condition uses only data with timestamp `≤ T` (the decision bar's close). Forward returns appear ONLY in Exit logic and falsifiability, never in Entry. The DB's `labels`/`ml_labels` tables are forward outcomes and are *forbidden* as features.

### 0.2 Canonical notation
| Symbol | Meaning |
|---|---|
| $t$ | a trading-day index; $T$ = current decision bar (signal computed at its close) |
| $C_t, O_t, H_t, L_t, V_t$ | raw close/open/high/low/volume on day $t$ |
| $A_t$ | `adjusted_close` on day $t$ |
| $r_t = \ln(A_t / A_{t-1})$ | daily log return (adjusted) |
| $g_t = O_t / C_{t-1} - 1$ | overnight gap (raw close-to-open; factor cancels day-over-day for same instrument and is acceptable for gap sign/magnitude) |
| $\rho_t = (H_t - L_t)/C_t$ | intraday range fraction |
| $\mu_t^{(n)}, \sigma_t^{(n)}$ | rolling mean / std of $r$ over the $n$ bars ending at $t-1$ (strictly past) |
| $\text{TR}_t = \max(H_t-L_t,\ |H_t-C_{t-1}|,\ |L_t-C_{t-1}|)$ | true range |
| $\text{ATR}_t^{(n)}$ | Wilder/SMA average of $\text{TR}$ over $n$ bars ending at $t$ |
| $\overline{V}_t^{(n)}$ | mean volume over the $n$ bars ending at $t-1$ |

### 0.3 Liquidity & eligibility gate (global pre-filter, applied to ALL hypotheses)
A ticker is **eligible** on day $T$ only if all hold (defaults; tunable):
- Median daily turnover over the trailing $W_{\text{liq}}=252$ bars $> \Lambda_{\min}$.
- Trading history length $\geq N_{\text{hist}}$ bars (so rolling windows are full).
- $C_T \geq P_{\min}$ (penny-stock floor).

| Param | Notation | Default | Range |
|---|---|---|---|
| Liquidity lookback | $W_{\text{liq}}$ | 252 | [120, 504] |
| Min median turnover (INR) | $\Lambda_{\min}$ | 5e7 | [1e7, 5e8] |
| Min history (bars) | $N_{\text{hist}}$ | 252 | [120, 504] |
| Min price (INR) | $P_{\min}$ | 20 | [5, 100] |

The canonical empirically-derived liquid set is ≈939 tickers at defaults.

### 0.4 Cost & friction assumption (for downstream backtest, not entry math)
Per CLAUDE.md, assume ≥ **0.15%** round-trip transaction cost. Every edge below is reported gross; Agent 2 must net it.

### 0.5 Table of Contents
| # | Strategy | Pillar | Direction |
|---|---|---|---|
| H1 | Volatility-Gated Overreaction Reversal | Conditional reversal / overreaction | Long & Short |
| H2 | Volume-Confirmed Information Drift (PEAD analogue) | Microstructure / underreaction | Long & Short |
| H3 | Gap Polarity Engine (gap-down reversal / gap-up continuation) | Microstructure / gap dynamics | Long & Short |
| H4 | Variance-Ratio Regime Switch | Autocorrelation / regime | Long & Short |
| H5 | Compression-Then-Expansion Directional Breakout | Range dynamics / volatility | Long & Short |
| H6 | 52-Week-High Anchoring Drift | Behavioral / anchoring | Long (Short variant) |
| H7 | Cross-Sectional Lead–Lag Laggard Catch-Up | Cross-sectional microstructure | Long & Short |
| H8 | Idiosyncratic Residual Mean-Reversion (Beta-Neutral) | Stat-arb / residual reversion | Long & Short |
| H9 | Volatility-Risk-Premium Range Contraction Carry | Volatility drag / range | Long (mean-reversion carry) |
| H10 | Hurst-Persistence Trend Continuation | Fractal / persistence | Long & Short |
| H11 | Turnover-Shock Liquidity Reversal | Liquidity-driven reversal | Long & Short |

---

## H1 — Volatility-Gated Overreaction Reversal

### 1. Rationale
Single-day extreme moves driven by sentiment/forced flow overshoot fair value; absent fresh information the price reverts. **Empirically:** fwd-5d return after a daily $z<-2.5$ is **+0.78%** (53.5% win) vs +0.20% baseline. Crucially the effect is **gated by volatility regime** — it only works when the stock is already in a *high-volatility* state (high-vol: +0.57% after $z<-1.5$; low-vol: +0.03%). The friction: in calm regimes a large move is more likely to be genuine information (no reversal); in turbulent regimes it is more likely panic/liquidity overshoot (reversion). This is the classic short-horizon contrarian edge, sharpened by a regime filter.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Z-score lookback | $N_z$ | 20 | [10, 40] |
| Entry z-threshold (long) | $Z_{\text{in}}$ | −2.0 | [−3.0, −1.5] |
| Entry z-threshold (short) | $Z_{\text{in}}^{+}$ | +2.0 | [+1.5, +3.0] |
| Vol-regime lookback | $N_{\text{reg}}$ | 120 | [60, 252] |
| Vol-regime gate multiple | $k_{\text{reg}}$ | 1.0 | [0.8, 1.5] |
| Profit target (σ multiple) | $\theta_{\text{tp}}$ | 1.5 | [0.5, 3.0] |
| Stop (σ multiple) | $\theta_{\text{sl}}$ | 1.5 | [0.5, 3.0] |
| Max holding (bars) | $N_{\text{hold}}$ | 5 | [2, 10] |

### 3. Entry Logic
Rolling stats over $N_z$ bars ending at $T-1$: $\mu_T^{(N_z)}, \sigma_T^{(N_z)}$. Define the standardized daily shock
$$z_T = \frac{r_T - \mu_T^{(N_z)}}{\sigma_T^{(N_z)}}.$$
Volatility-regime gate (current realized vol exceeds its own long-run baseline):
$$\sigma_T^{(N_z)} \;>\; k_{\text{reg}}\cdot \frac{1}{N_{\text{reg}}}\sum_{i=1}^{N_{\text{reg}}} |r_{T-i}|.$$
- **LONG** at next open if $z_T \le Z_{\text{in}}$ **and** the gate holds.
- **SHORT** at next open if $z_T \ge Z_{\text{in}}^{+}$ **and** the gate holds.

### 4. Exit Logic (whichever first)
Let entry price $= A_{\text{entry}}$, $\sigma_\$ = \sigma_T^{(N_z)} \cdot A_{\text{entry}}$ (σ in price units).
- **Take-profit:** long exits if $A_t \ge A_{\text{entry}} + \theta_{\text{tp}}\sigma_\$$; short symmetric.
- **Stop-loss:** long exits if $A_t \le A_{\text{entry}} - \theta_{\text{sl}}\sigma_\$$; short symmetric.
- **Time-stop:** force exit at close of bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=5$. The reversal half-life from the diagnostics peaks in the 3–5 day window; beyond 5 days drift dominates and the reversal signal decays.

### 6. Directionality & Universe
Long & short; eligible liquid universe (§0.3). Short side requires borrow availability (flag for Agent 2). Avoid pure ETF tickers for this name-specific overreaction edge.

### 7. Falsifiability
Invalid if, on out-of-sample data, fwd-$N_{\text{hold}}$ mean return for the $z\le Z_{\text{in}}$ + high-vol-gate bucket is statistically indistinguishable from the unconditional mean, OR if the high-vol vs low-vol spread (currently +0.54% per the diagnostic) collapses to ≤ 0.10%.

---

## H2 — Volume-Confirmed Information Drift (PEAD Analogue)

### 1. Rationale
The single most discriminating conditioning variable found: **a large move WITH a volume shock behaves opposite to one WITHOUT**. A big down move (r<−3%) on <3× volume reverts up (+0.64% fwd5), but on >3× volume it *continues down* (−0.19%, 45.5% win). Symmetrically, up moves on normal volume drift further than up moves on a volume blow-off. Volume-confirmed moves carry **information** (earnings/news analogue → post-event drift, underreaction); volume-unconfirmed moves are **liquidity noise** (overreaction → reversal). This single mechanic powers two opposite trades depending on the volume gate, so it is its own structural edge distinct from H1.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Move threshold (abs daily ret) | $\delta_r$ | 0.03 | [0.02, 0.06] |
| Volume avg lookback | $N_v$ | 20 | [10, 50] |
| Volume-shock multiple | $\kappa_V$ | 3.0 | [1.5, 6.0] |
| Drift holding (bars) | $N_{\text{hold}}$ | 5 | [3, 10] |
| Trailing-stop ATR multiple | $\theta_{\text{trail}}$ | 2.0 | [1.0, 4.0] |
| ATR lookback | $N_{\text{atr}}$ | 14 | [7, 28] |
| Signal-decay floor (cum drift) | $\eta$ | 0.0 | [−0.01, 0.01] |

### 3. Entry Logic
Volume-shock flag: $\text{VS}_T = \mathbb{1}\!\left[\,V_T > \kappa_V\,\overline{V}_T^{(N_v)}\,\right]$.
- **Informational continuation (the tradeable side):**
  - **SHORT** at next open if $r_T \le -\delta_r$ **and** $\text{VS}_T=1$ (volume-confirmed breakdown → continuation down).
  - **LONG** at next open if $r_T \ge +\delta_r$ **and** $\text{VS}_T=1$ (volume-confirmed breakout → continuation up).
- The volume-*unconfirmed* leg ($\text{VS}_T=0$) is intentionally routed to H1 (reversal); do not double-trade the same bar.

### 4. Exit Logic (whichever first)
- **Trailing stop:** maintain a chandelier stop at $\theta_{\text{trail}}\cdot \text{ATR}_t^{(N_{\text{atr}})}$ from the most-favorable close since entry.
- **Signal decay:** exit if cumulative drift since entry reverses sign past $\eta$ for 2 consecutive bars (momentum exhaustion).
- **Time-stop:** close at bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=5$. Information drift (the PEAD analogue) decays over roughly a week as the market fully prices the news; 5 bars captures the bulk before decay.

### 6. Directionality & Universe
Long & short, liquid universe. Strongest for single names (information content); de-emphasize ETFs. Particularly relevant around `corporate_events.event_date` if Agent 3 chooses to join earnings dates (optional enhancement, not required).

### 7. Falsifiability
Invalid if the sign of fwd-$N_{\text{hold}}$ return for the volume-shock bucket equals that of the no-shock bucket (i.e., the volume gate no longer flips the sign), or if the continuation bucket's win rate is ≤ 50% out-of-sample.

---

## H3 — Gap Polarity Engine

### 1. Rationale
Overnight gaps in this universe show a **polarity asymmetry**: large **gap-downs reverse** (gap<−5% → +0.88% fwd3, 53.7% win) while large **gap-ups continue** (gap>5% → +1.10% fwd3, 53.4% win). Mechanism: forced overnight selling (margin, panic, MSCI/index flows) overshoots on the downside and is bought back; whereas gap-ups reflect genuine demand/news that under-reacts and continues. Trading the polarity (fade gap-downs, ride gap-ups) is a distinct microstructure edge orthogonal to intraday-move conditioning (H1/H2 condition on close-to-close; H3 conditions on the close-to-open jump specifically).

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Gap-down fade threshold | $g_{\text{dn}}$ | −0.05 | [−0.10, −0.03] |
| Gap-up ride threshold | $g_{\text{up}}$ | +0.05 | [+0.03, +0.10] |
| Confirm: close-back-into-range (gap-down) | $\phi$ | 0.5 | [0.0, 1.0] |
| Holding (bars) | $N_{\text{hold}}$ | 3 | [2, 8] |
| Profit target (×gap) | $\theta_g$ | 1.0 | [0.5, 2.0] |
| Stop (×ATR) | $\theta_{\text{sl}}$ | 1.5 | [0.5, 3.0] |
| ATR lookback | $N_{\text{atr}}$ | 14 | [7, 28] |

### 3. Entry Logic
Gap $g_T = O_T/C_{T-1} - 1$.
- **Gap-down reversal (LONG):** $g_T \le g_{\text{dn}}$ **and** intraday recovery confirm $C_T \ge O_T + \phi\,(H_T - O_T)$ (price closed back up into the day's range, signalling absorption of the panic). Enter at $C_T$ (or next open).
- **Gap-up continuation (LONG):** $g_T \ge g_{\text{up}}$ **and** $C_T \ge O_T$ (holds the gap, no intraday rejection). Enter at $C_T$ (or next open).
- **Gap-up exhaustion (SHORT, optional):** $g_T \ge g_{\text{up}}$ **and** $C_T < O_T - \phi\,(O_T - L_T)$ (gap rejected intraday → fade).

### 4. Exit Logic (whichever first)
- **Take-profit:** target $= \theta_g \times |g_T|$ measured from entry in the trade direction.
- **Stop:** $\theta_{\text{sl}} \cdot \text{ATR}_T^{(N_{\text{atr}})}$ adverse.
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=3$. Gap effects resolve fastest of all signals (the diagnostic peaked at 3 days); within the 2–15 mandate at the low end.

### 6. Directionality & Universe
Long-biased (gap-down-reversal + gap-up-continuation), with an optional gap-up-rejection short. Liquid single names; exclude ETFs (gaps are index-mechanical there).

### 7. Falsifiability
Invalid if the **polarity asymmetry vanishes** — i.e., gap-downs and gap-ups produce the same-signed forward return — or if the intraday-confirm filter $\phi$ adds no win-rate lift over the raw gap.

---

## H4 — Variance-Ratio Regime Switch

### 1. Rationale
Whether a name is mean-reverting or trending is itself **state-dependent and measurable** via the Lo–MacKinlay variance ratio. With $VR(q)<1$ the series is anti-persistent (mean-reverting): there, recent momentum **reverses** (mom5→fwd5 corr **−0.053**). With $VR(q)>1$ it is persistent (trending): there, momentum **continues** (corr **+0.049**). A single estimator ($VR$) tells you which playbook to run. This is structurally different from H1/H2 (which condition on a one-day shock) — H4 conditions on the *autocorrelation structure of the whole recent window* and dynamically switches between contrarian and momentum sub-strategies.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| VR aggregation period | $q$ | 5 | [2, 10] |
| VR estimation window | $N_{VR}$ | 60 | [40, 120] |
| Mean-revert threshold | $VR_{\text{lo}}$ | 0.80 | [0.6, 0.95] |
| Trend threshold | $VR_{\text{hi}}$ | 1.20 | [1.05, 1.5] |
| Momentum window | $N_{\text{mom}}$ | 5 | [3, 10] |
| Momentum entry threshold | $m_{\min}$ | 0.02 | [0.01, 0.05] |
| Holding (bars) | $N_{\text{hold}}$ | 5 | [3, 12] |
| Stop (×σ) | $\theta_{\text{sl}}$ | 2.0 | [1.0, 3.0] |

### 3. Entry Logic
Variance ratio over $N_{VR}$ bars ending at $T$:
$$VR_T(q) = \frac{\operatorname{Var}\!\big(\sum_{i=0}^{q-1} r_{t-i}\big)}{q\cdot \operatorname{Var}(r_t)}\quad\text{estimated over the trailing } N_{VR}\text{ bars.}$$
Recent momentum $m_T = \sum_{i=0}^{N_{\text{mom}}-1} r_{T-i}$.
- **Mean-revert regime** ($VR_T < VR_{\text{lo}}$): **fade** momentum.
  - LONG if $m_T \le -m_{\min}$; SHORT if $m_T \ge +m_{\min}$.
- **Trend regime** ($VR_T > VR_{\text{hi}}$): **follow** momentum.
  - LONG if $m_T \ge +m_{\min}$; SHORT if $m_T \le -m_{\min}$.
- **Neutral band** ($VR_{\text{lo}} \le VR_T \le VR_{\text{hi}}$): no trade.
Enter at next open.

### 4. Exit Logic (whichever first)
- **Stop:** $\theta_{\text{sl}} \cdot \sigma_T^{(N_{VR})}$ adverse (price units).
- **Regime invalidation:** exit early if $VR_t$ crosses back through the neutral band (the regime that justified the trade has ended).
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=5$. Both the reversion and continuation effects measured at the 5-day horizon; matches the VR aggregation scale $q=5$.

### 6. Directionality & Universe
Long & short, liquid universe. Works on both single names and sector ETFs (VR is scale-free).

### 7. Falsifiability
Invalid if the sign of the momentum→forward-return correlation is the **same** in both VR regimes (the switch no longer separates regimes), or if the neutral-band trades outperform the regime trades.

---

## H5 — Compression-Then-Expansion Directional Breakout

### 1. Rationale
Volatility is auto-correlated and **mean-reverting between contraction and expansion**: tight ranges precede expansions (energy build-up). The diagnostic warning here is important — *contraction alone does not raise the forward move* (NR7 |fwd5| 0.041 vs 0.043). The edge requires **directional confirmation**: a breakout *out of* the compression. Close above the prior 20-day high *after* range compression yields +0.37–0.50% fwd5 with 51.5% win. The mechanism: compression = coiled liquidity + stop clusters at range edges; the breakout triggers stop-runs and trend-follower entries, creating short-lived directional momentum. This is distinct from H4 (which is regime/autocorrelation based, no breakout level) and from H10 (persistence, no compression precondition).

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Compression lookback (recent) | $N_c$ | 10 | [5, 20] |
| Compression baseline lookback | $N_b$ | 50 | [20, 100] |
| Compression ratio threshold | $\gamma$ | 0.85 | [0.5, 1.0] |
| Breakout channel lookback | $N_{\text{ch}}$ | 20 | [10, 55] |
| Volume confirm multiple | $\kappa_V$ | 1.5 | [1.0, 3.0] |
| Holding (bars) | $N_{\text{hold}}$ | 5 | [3, 12] |
| Profit target (×ATR) | $\theta_{\text{tp}}$ | 2.5 | [1.0, 5.0] |
| Stop (back inside channel) flag | $\beta$ | 1 (on) | {0,1} |

### 3. Entry Logic
Compression metric (recent range vs prior baseline range):
$$\Gamma_T = \frac{\overline{(H-L)}\,_{[T-N_c+1,\,T]}}{\overline{(H-L)}\,_{[T-N_b,\,T-N_c]}} \;<\; \gamma .$$
Channel: $\text{HH}_T = \max_{i\in[1,N_{\text{ch}}]} H_{T-i}$, $\text{LL}_T = \min_{i\in[1,N_{\text{ch}}]} L_{T-i}$.
- **LONG** if $\Gamma_T<\gamma$ **and** $C_T > \text{HH}_T$ **and** $V_T > \kappa_V\,\overline{V}_T^{(20)}$.
- **SHORT** if $\Gamma_T<\gamma$ **and** $C_T < \text{LL}_T$ **and** $V_T > \kappa_V\,\overline{V}_T^{(20)}$.
Enter at $C_T$ or next open.

### 4. Exit Logic (whichever first)
- **Take-profit:** $\theta_{\text{tp}} \cdot \text{ATR}_T^{(14)}$ in trade direction.
- **Failed-breakout stop:** if $\beta=1$, exit immediately when price closes back inside the channel ($C_t < \text{HH}_T$ for a long), i.e., the breakout failed.
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=5$. Breakout momentum from compression is short-lived; 5 bars captures the expansion leg before the new range establishes.

### 6. Directionality & Universe
Long & short, liquid universe. Works on names and trending ETFs.

### 7. Falsifiability
Invalid if breakout-after-compression has no higher win rate or expected return than a random breakout, OR if the failed-breakout stop ($\beta$) does not reduce drawdown — implying the compression precondition carries no information.

---

## H6 — 52-Week-High Anchoring Drift

### 1. Rationale
A robust behavioral edge: investors **anchor** on the salient 52-week high and under-react as a stock approaches it (reluctance to bid up past the anchor), so prices that are *near* the high keep drifting up afterward. **Empirically the strongest measured drift:** stocks within 2% of the 252-day high drift **+0.96% over 10 days (54% win)**, vs +0.15% for stocks 75–90% below their high. Mechanism = anchoring + disposition effect (winners under-bought). This is a slower, cleaner edge than the microstructure ones and uses the longest holding in the suite.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| High lookback (bars) | $N_h$ | 252 | [120, 252] |
| Proximity threshold (to high) | $\pi$ | 0.98 | [0.92, 1.00] |
| Min trend filter (price vs prior) | $\tau$ | 0.0 | [−0.05, 0.10] |
| Holding (bars) | $N_{\text{hold}}$ | 10 | [5, 15] |
| Profit target | $\theta_{\text{tp}}$ | 0.06 | [0.03, 0.12] |
| Stop | $\theta_{\text{sl}}$ | 0.04 | [0.02, 0.08] |
| Low-proximity short threshold | $\pi^-$ | 0.80 | [0.60, 0.85] |

### 3. Entry Logic
Proximity ratio: $\Pi_T = C_T / \max_{i\in[1,N_h]} C_{T-i}$.
- **LONG** if $\Pi_T \ge \pi$ (within $(1-\pi)$ of the 52-week high) **and** trailing trend non-negative: $A_T/A_{T-20}-1 \ge \tau$.
- **SHORT (variant)** if $\Pi_T \le \pi^-$ **and** trailing 20-day trend negative (laggards far below their high keep underperforming — momentum/anchoring on the downside).
Enter at next open.

### 4. Exit Logic (whichever first)
- **Take-profit:** $+\theta_{\text{tp}}$ from entry (long); symmetric short.
- **Stop:** $-\theta_{\text{sl}}$ from entry (long); symmetric short.
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=10$. Anchoring drift is a slow underreaction; the measured edge is at the 10-day horizon — the longest practical hold within the 2–15 mandate.

### 6. Directionality & Universe
Long primary, short variant for the far-from-high laggards. Liquid single names; meaningful only where a genuine 52-week high exists (require ≥ $N_h$ bars of history).

### 7. Falsifiability
Invalid if the within-2%-of-high bucket's fwd-10d return is not materially above the broad-market bucket out-of-sample (spread ≤ 0.20%), or if the drift inverts (near-high names mean-revert down).

---

## H7 — Cross-Sectional Lead–Lag Laggard Catch-Up

### 1. Rationale
Information diffuses unevenly across the cross-section: liquid leaders price news first, less-liquid laggards react with a 1-day delay. **Empirically:** corr(today's stock return, **yesterday's** equal-weight market return) = **+0.049** — a measurable laggard underreaction. Trading laggards in the direction of the prior-day market (or, more precisely, the prior-day move of their high-correlation leaders) harvests this diffusion lag. This is a genuinely cross-sectional edge (no single-name signal can produce it) and is distinct from H8 (which is residual reversion, opposite sign).

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Leader-group size | $K$ | 20 | [5, 50] |
| Correlation lookback (for grouping) | $N_{\text{corr}}$ | 60 | [40, 120] |
| Min leader correlation | $\rho_{\min}$ | 0.4 | [0.2, 0.7] |
| Leader return trigger | $\lambda$ | 0.01 | [0.005, 0.03] |
| Laggard liquidity rank (lower = more lagged) | $q_{\text{lag}}$ | 0.5 | [0.2, 0.8] |
| Holding (bars) | $N_{\text{hold}}$ | 3 | [2, 6] |
| Stop (×ATR) | $\theta_{\text{sl}}$ | 1.5 | [1.0, 3.0] |

### 3. Entry Logic
For each eligible ticker $s$ (the laggard), construct a **leader composite**: the equal-weight return of the $K$ most-correlated *more-liquid* tickers (correlation estimated over the trailing $N_{\text{corr}}$ bars; only peers with $\rho \ge \rho_{\min}$ and higher turnover than $s$). Let $\ell_{T}$ = leader composite return on day $T$ (already observed at $T$'s close), and the laggard has **not yet** matched it: define unrealized catch-up $\Delta_T = \ell_T - r_T^{(s)}$.
- **LONG** $s$ at next open if $\ell_T \ge +\lambda$ **and** $\Delta_T > 0$ (leaders up, laggard hasn't caught up).
- **SHORT** $s$ at next open if $\ell_T \le -\lambda$ **and** $\Delta_T < 0$.
Restrict to laggards whose turnover rank $\le q_{\text{lag}}$ within their leader group (the genuinely slower names).

### 4. Exit Logic (whichever first)
- **Catch-up complete:** exit when laggard's cumulative return since entry $\ge \ell_T$ (gap closed).
- **Stop:** $\theta_{\text{sl}} \cdot \text{ATR}_T^{(14)}$ adverse.
- **Time-stop:** bar $T + N_{\text{hold}}$ (diffusion lag is ~1–2 days; short hold).

### 5. Holding Period
$N_{\text{hold}}=3$. Lead–lag diffusion resolves within 1–3 days; holding longer reintroduces idiosyncratic noise.

### 6. Directionality & Universe
Long & short, liquid universe with an *internal* liquidity split (leaders = top turnover, laggards = lower). Exclude ETFs from the laggard set.

### 7. Falsifiability
Invalid if the lead–lag correlation is ≤ 0.01 out-of-sample, or if conditioning on a custom correlated-leader basket adds no edge over the naive equal-weight-market lag (i.e., the +0.049 was pure market beta timing, not diffusion).

---

## H8 — Idiosyncratic Residual Mean-Reversion (Beta-Neutral)

### 1. Rationale
After stripping out market (and optionally a leader-basket) co-movement, the **residual** return of a stock is largely liquidity/noise and mean-reverts faster than the raw return. Raw 1-day autocorr is only +0.038 (continuation), but the *residual* (market-neutralized) component is where short-horizon reversion concentrates, because the systematic part is what trends while the idiosyncratic part is what overshoots. Trading the residual long/short produces a **beta-neutral** stat-arb edge — structurally orthogonal to all directional hypotheses and attractive to the Risk Officer for its low market exposure.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Beta estimation window | $N_\beta$ | 60 | [40, 120] |
| Residual z lookback | $N_{rz}$ | 10 | [5, 20] |
| Entry residual-z threshold | $Z_{\text{res}}$ | 1.5 | [1.0, 3.0] |
| Holding (bars) | $N_{\text{hold}}$ | 3 | [2, 7] |
| Exit residual-z (revert to) | $Z_{\text{exit}}$ | 0.3 | [0.0, 1.0] |
| Hard stop (×residual σ) | $\theta_{\text{sl}}$ | 3.0 | [2.0, 5.0] |
| Market proxy | — | equal-weight liquid | {equal-weight, cap-weight, NIFTYBEES} |

### 3. Entry Logic
Estimate market beta over $N_\beta$ bars (OLS of $r^{(s)}$ on market return $r^{(M)}$): $\hat\beta_T$. Residual:
$$\varepsilon_t = r_t^{(s)} - \hat\beta_T\, r_t^{(M)}.$$
Standardize the residual over $N_{rz}$ bars: $z^{\varepsilon}_T = \big(\varepsilon_T - \bar\varepsilon\big)/\sigma_\varepsilon$ (rolling, strictly past for $\bar\varepsilon,\sigma_\varepsilon$).
- **LONG** $s$ (hedged) at next open if $z^{\varepsilon}_T \le -Z_{\text{res}}$ (residual overshot down).
- **SHORT** $s$ (hedged) at next open if $z^{\varepsilon}_T \ge +Z_{\text{res}}$.
Position is beta-hedged: pair with $-\hat\beta_T$ units of the market proxy for neutrality (optional for the backtest; flag for Agent 3).

### 4. Exit Logic (whichever first)
- **Mean-reversion target:** exit when $|z^{\varepsilon}_t| \le Z_{\text{exit}}$ (residual normalized).
- **Hard stop:** $|z^{\varepsilon}_t| \ge \theta_{\text{sl}}$ in the adverse direction (residual kept diverging — regime break).
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=3$. Idiosyncratic reversion is fast (1–3 days); holding longer lets systematic drift dominate the residual.

### 6. Directionality & Universe
Long & short, market-neutral. Liquid single names only (residual estimation needs co-movement with the market proxy). Exclude the market-proxy instrument itself.

### 7. Falsifiability
Invalid if residual autocorrelation is ≥ 0 (residuals trend rather than revert) out-of-sample, or if the beta-neutral P&L has the same volatility/Sharpe as the un-hedged version (implying the neutralization removed the edge, not just the beta).

---

## H9 — Volatility-Risk-Premium Range-Contraction Carry

### 1. Rationale
**Volatility drag / variance-risk-premium analogue without options.** When a stock's realized range *contracts sharply* relative to its recent baseline and price is range-bound (no breakout), the most likely path is continued chop with a slight mean-reverting, positive-carry drift toward the range midpoint — because realized volatility tends to keep mean-reverting downward and the market over-prices tail risk in the just-prior expansion. This is the *non-breakout* complement to H5: H5 trades the expansion *if* a breakout occurs; H9 harvests the *range-bound* outcome (the more common one) by fading excursions to the band edges during low-realized-vol regimes. Mechanically it monetizes the gap between elevated implied/expected vol and contracting realized vol.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Realized-vol lookback | $N_{\text{rv}}$ | 20 | [10, 40] |
| Vol-contraction percentile | $P_{\text{vol}}$ | 25 | [10, 40] |
| Vol-percentile baseline window | $N_{\text{pct}}$ | 120 | [60, 252] |
| Bollinger band lookback | $N_{\text{bb}}$ | 20 | [10, 40] |
| Band width (σ) | $b$ | 2.0 | [1.5, 3.0] |
| Holding (bars) | $N_{\text{hold}}$ | 4 | [2, 8] |
| Exit at midline flag | $\mu_{\text{exit}}$ | 1 (on) | {0,1} |
| Stop (×band width) | $\theta_{\text{sl}}$ | 1.0 | [0.5, 2.0] |

### 3. Entry Logic
Realized vol $\text{RV}_T = \sigma_T^{(N_{\text{rv}})}$. Require a **low-vol (contracted) regime**: $\text{RV}_T$ below its $P_{\text{vol}}$-th percentile over the trailing $N_{\text{pct}}$ bars. Bollinger bands on $A$: midline $M_T = \text{SMA}(A, N_{\text{bb}})$, bands $M_T \pm b\,\sigma^{A}_{N_{\text{bb}}}$.
- **LONG** at next open if low-vol regime **and** $A_T \le M_T - b\,\sigma^A$ (price at lower band → fade back to midline).
- **SHORT** at next open if low-vol regime **and** $A_T \ge M_T + b\,\sigma^A$.
Explicitly **exclude** bars that simultaneously satisfy H5's breakout (do not fade a confirmed breakout): require $C_T$ within the channel ($\text{LL}_T < C_T < \text{HH}_T$).

### 4. Exit Logic (whichever first)
- **Midline reversion:** if $\mu_{\text{exit}}=1$, exit when $A_t$ crosses $M_t$.
- **Stop:** price moves $\theta_{\text{sl}}\times$ band-width beyond the entry band (range broke → contraction thesis failed).
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=4$. Range excursions revert within a few days in a contracted-vol regime; longer holds risk the eventual regime-ending expansion.

### 6. Directionality & Universe
Long & short (symmetric band fade), liquid universe. Avoid names with imminent known catalysts (the contraction thesis breaks on news).

### 7. Falsifiability
Invalid if, conditioned on the low-vol regime, band-edge excursions are followed by continued expansion (breakouts) as often as reversions, or if forward returns after a lower-band touch in low-vol are ≤ 0.

---

## H10 — Hurst-Persistence Trend Continuation

### 1. Rationale
Fractal market structure: a series with **Hurst exponent $H>0.5$** is persistent (trends self-reinforce); $H<0.5$ is anti-persistent (reverts). Estimating $H$ per ticker over a rolling window identifies names currently in a *persistent* state, where a swing-momentum trade has positive expectancy. This generalizes the binary VR regime of H4 into a continuous persistence score and uses a different estimator (rescaled-range / detrended fluctuation rather than variance ratio), letting downstream agents cross-validate the regime call. The behavioral driver: herding/under-reaction creates serial correlation that persists until the trend exhausts.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Hurst estimation window | $N_H$ | 100 | [60, 200] |
| Persistence threshold | $H_{\min}$ | 0.55 | [0.52, 0.65] |
| Trend-direction window | $N_{\text{dir}}$ | 20 | [10, 50] |
| Min absolute trend | $\tau_H$ | 0.03 | [0.01, 0.08] |
| Holding (bars) | $N_{\text{hold}}$ | 8 | [4, 15] |
| Trailing stop (×ATR) | $\theta_{\text{trail}}$ | 2.5 | [1.0, 4.0] |
| Persistence-decay exit | $H_{\text{exit}}$ | 0.50 | [0.45, 0.55] |

### 3. Entry Logic
Estimate the Hurst exponent $\hat H_T$ over the trailing $N_H$ log-returns (rescaled-range $R/S$ or DFA; Backend to implement, both monotone in persistence). Trend direction over $N_{\text{dir}}$: $D_T = A_T/A_{T-N_{\text{dir}}} - 1$.
- **LONG** at next open if $\hat H_T \ge H_{\min}$ **and** $D_T \ge +\tau_H$.
- **SHORT** at next open if $\hat H_T \ge H_{\min}$ **and** $D_T \le -\tau_H$.

### 4. Exit Logic (whichever first)
- **Trailing stop:** $\theta_{\text{trail}}\cdot\text{ATR}_t^{(14)}$ from the most-favorable close.
- **Persistence decay:** exit if $\hat H_t \le H_{\text{exit}}$ (the trending state ended).
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=8$. Persistence trades need room to let the trend run; 8 bars sits in the upper-middle of the swing band, appropriate for a continuation edge.

### 6. Directionality & Universe
Long & short, liquid universe (names and trending ETFs). Estimate $H$ only where ≥ $N_H$ bars exist.

### 7. Falsifiability
Invalid if high-$\hat H$ names do not exhibit higher forward trend-continuation than low-$\hat H$ names out-of-sample, or if $\hat H$ provides no incremental information beyond the VR regime of H4 (redundancy check by Agent 2).

---

## H11 — Turnover-Shock Liquidity Reversal

### 1. Rationale
Distinct from H2 (which conditions on *price move + volume*), H11 conditions on a **pure liquidity/turnover shock without a commensurate price move** — a spike in traded value that is *not* matched by a large return. This signature flags **absorbed forced flow** (a large seller/buyer cleared at a stable price), which is typically followed by a snap-back as the temporary price pressure unwinds (Grossman–Miller liquidity-provision premium). The trade direction fades the small concurrent price pressure. This isolates the *liquidity-provision* component of reversal cleanly, separate from informational drift.

### 2. Hyper-parameters
| Param | Notation | Default | Range |
|---|---|---|---|
| Turnover avg lookback | $N_\tau$ | 20 | [10, 50] |
| Turnover-shock multiple | $\kappa_\tau$ | 3.0 | [2.0, 6.0] |
| Max concurrent move (abs ret) | $\delta_{\max}$ | 0.015 | [0.005, 0.03] |
| Price-pressure window | $N_{pp}$ | 3 | [1, 5] |
| Holding (bars) | $N_{\text{hold}}$ | 3 | [2, 6] |
| Profit target (×ATR) | $\theta_{\text{tp}}$ | 1.0 | [0.5, 2.0] |
| Stop (×ATR) | $\theta_{\text{sl}}$ | 1.5 | [1.0, 3.0] |

### 3. Entry Logic
Turnover $U_t = C_t\,V_t$; turnover-shock flag $\text{TS}_T = \mathbb{1}\big[U_T > \kappa_\tau\,\overline{U}_T^{(N_\tau)}\big]$. Concurrent move is *small*: $|r_T| \le \delta_{\max}$. Recent price pressure direction $\text{PP}_T = \sum_{i=0}^{N_{pp}-1} r_{T-i}$.
- **LONG** at next open if $\text{TS}_T=1$ **and** $|r_T|\le\delta_{\max}$ **and** $\text{PP}_T < 0$ (heavy volume absorbed a mild sell-off → snap-back up).
- **SHORT** at next open if $\text{TS}_T=1$ **and** $|r_T|\le\delta_{\max}$ **and** $\text{PP}_T > 0$.

### 4. Exit Logic (whichever first)
- **Take-profit:** $\theta_{\text{tp}}\cdot\text{ATR}_T^{(14)}$ in trade direction (pressure unwinds).
- **Stop:** $\theta_{\text{sl}}\cdot\text{ATR}_T^{(14)}$ adverse (it was information, not liquidity → continuation).
- **Time-stop:** bar $T + N_{\text{hold}}$.

### 5. Holding Period
$N_{\text{hold}}=3$. Liquidity-provision premiums are captured within 1–3 days as temporary pressure dissipates.

### 6. Directionality & Universe
Long & short, liquid universe. Most effective in mid-liquidity names where a single large order moves turnover sharply but price only mildly (large-caps absorb without a turnover spike; micro-caps gap).

### 7. Falsifiability
Invalid if turnover shocks with small concurrent moves are followed by *continuation* of the prior pressure rather than reversal, or if H11 entries fully overlap H2 entries (no independent population) — confirming it is not a distinct liquidity-only signal.

---

## Appendix A — Look-Ahead & Computability Audit

| Hypothesis | All entry inputs ≤ T? | Columns used (all exist in `ohlcv`) | Notes |
|---|---|---|---|
| H1 | Yes — rolling $\mu,\sigma$ over $[T-N_z,T-1]$; $r_T$ known at close $T$ | adjusted_close, close, volume(gate via §0.3) | Entry at next open ⇒ no same-bar leak |
| H2 | Yes — $r_T$, $V_T$, $\overline V$ over past | adjusted_close, volume | — |
| H3 | Yes — $g_T,O_T,H_T,L_T,C_T$ all on bar $T$ | open, high, low, close, adjusted_close | Confirm uses intraday extremes of bar $T$ only |
| H4 | Yes — VR & momentum over trailing window | adjusted_close | VR estimated on past returns |
| H5 | Yes — channel from $[T-N_{ch},T-1]$; $C_T,V_T$ on bar $T$ | high, low, close, volume, adjusted_close | Breakout uses bar-$T$ close vs prior channel |
| H6 | Yes — 252d high over $[T-N_h,T-1]$; $C_T$ on $T$ | close, adjusted_close | Requires ≥ $N_h$ history |
| H7 | Yes — leader composite uses bar-$T$ closes; trade next open | close, volume, adjusted_close | Correlations over trailing window |
| H8 | Yes — $\hat\beta$ over trailing window; $\varepsilon_T$ at close $T$ | adjusted_close (+ market proxy) | Market proxy = function of same panel |
| H9 | Yes — RV percentile & bands over past; $A_T$ on $T$ | adjusted_close, high, low, close | Excludes H5 breakout bars |
| H10 | Yes — Hurst over trailing $N_H$; $D_T$ to $T$ | adjusted_close | Requires ≥ $N_H$ history |
| H11 | Yes — $U_T$ on bar $T$ vs trailing avg | close, volume, adjusted_close | — |

**Result:** every hypothesis is computable from `ohlcv` columns (`open, high, low, close, volume, adjusted_close, date, ticker`) only. No reliance on the empty `sector`/macro fields, the empty `splits`/`dividends` tables, or the forward-looking `labels`/`ml_labels` tables. Liquidity gate (§0.3) and all rolling statistics use strictly past data; every entry executes at the next open or current close, never a future bar.

## Appendix B — Distinctness Matrix (no two hypotheses are re-skins)

| Edge | Conditioning variable | Sign of trade vs recent move | Pillar |
|---|---|---|---|
| H1 | 1-day z-shock + vol regime | Contrarian | Overreaction |
| H2 | 1-day move + **volume shock** | Continuation | Underreaction/PEAD |
| H3 | **overnight gap** polarity | Mixed (fade dn / ride up) | Gap microstructure |
| H4 | **variance ratio** regime | Switches by regime | Autocorrelation |
| H5 | range **compression + breakout level** | Continuation (breakout) | Range expansion |
| H6 | **52-week-high proximity** | Continuation (slow) | Anchoring |
| H7 | **cross-sectional** leader lag | Continuation of leaders | Lead–lag diffusion |
| H8 | **beta-residual** z | Contrarian (neutral) | Residual stat-arb |
| H9 | low-vol regime + band edge (**no breakout**) | Contrarian (range fade) | Vol drag / carry |
| H10 | **Hurst** persistence | Continuation (trend) | Fractal persistence |
| H11 | **turnover shock w/o price move** | Contrarian (snap-back) | Liquidity provision |

Each row's conditioning variable is unique; where two share a pillar (H1/H11 reversal, H4/H10 regime, H5/H9 range) the entry trigger and economic mechanism differ explicitly, and H9/H11 are constructed to *exclude* the populations of H5/H2 respectively.
