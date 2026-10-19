"""Stage 0: pre-declaration, saved to results.json BEFORE any strategy number is computed
(REPORT.md writes are blocked for this subagent; the report text is delivered in the structured answer)."""
import sys, time
sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab")
import r3common as C
C.set_agent("R3_twoway")
pre = {
 "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
 "note": "Written BEFORE any R3_twoway strategy number was computed. Only exploration done before: index availability "
         "and Nifty 50 futures carry (DEV: futures index 5.6%/yr vs spot 13.0%/yr, mean daily fut-spot gap -6.85%/yr, "
         "1D rate 6.35%/yr, Nifty 50 dividend yield ~1.0-1.2%) to set cost conventions.",
 "prereg_list": {
  "BASE": "frozen PROD long book (top-20, weekly, 4 sleeves, 20d time exit, liq2, cash, 50 bps), unhedged",
  "D0": "avoid veto only: EW elig_base minus PROD bottom 30% (select_quantile=(0.3,1), sizing equal) vs EW universe",
  "D1a": "BASE + short Nifty 50 futures, hedge ratio 1.0, weekly",
  "D1b": "BASE + short Nifty 50 futures, ex-ante rolling 60d beta (data <= t-1), weekly",
  "D1c": "as D1b with Nifty Midcap Select (synthetic futures)",
  "D2-K10-cash/D2-K10-fut/D2-K20-cash/D2-K20-fut": "F&O long top-K / short bottom-K (stock futures), dollar-neutral; long leg cash 50 bps or futures 25 bps",
  "D3": "BASE (full liq2, cash) + 50% overlay short of F&O bottom-20 (stock futures)",
  "D4": "F&O short-only bottom-20 (stock futures) on cash collateral"},
 "variants_count_rule": "10 pre-declared strategy variants + at most 1 extra (X1) = 11; 80 bps stress runs are stress tests of the same variants",
 "conventions": [
  "C1 phase averaging: 5 weekly entry phases, daily returns averaged; hedges rebalanced on each phase's own weekly signal dates; DEV 2023-01-01..2025-12-31 (exits by DEV end), 2026 = 2026-01-01..2026-10-14 fresh books, plus one contiguous 2023-01-01..2026-10-14 run for charts and ex-ante beta.",
  "C2 index hedge: notional = beta x long-book value reset at each weekly signal close; fixed units between resets, MTM settled daily in cash; P&L from 'Nifty 50 Futures Index' (embeds realised basis/roll); costs 1 bp x |delta notional| per weekly reset (incl. initial) + 2 bps x notional on the last trading day of each month; margin 15% of notional, half (7.5%) cash earning Nifty 1D Rate; long book scaled to 1/(1+0.075 beta) at each reset; no stock cost for that tiny re-scaling (absorbed by weekly sleeve rebalance).",
  "C3 ex-ante beta: OLS beta of the phase-averaged contiguous unhedged BASE daily returns on the hedge instrument over the 60 trading days ending t-1; beta=1.0 until 40 obs; clipped [0,2].",
  "C4 Midcap Select: synthetic futures r = r(Nifty Midcap Select price) - (r_1D - 0.0107/252 per day); q=1.07%/yr = mean Nifty 50 dividend yield from 'Nifty50 Dividend Points' (assumed same for MIDCPNIFTY); same costs/margin as C2; liquidity caveat.",
  "C5 stock-futures legs: same staggered-sleeve engine as L.Sim (4 sleeves, weekly, 20d time exit, forced exit at last valid close on suspension/label_block, slot sizing 1/K); picks top/bottom-K by PROD within fno_proxy & elig_base; short P&L = -(CA-adjusted total return) + Nifty 1D Rate carry while held; futures long pays the carry; futures 25 bps RT per leg, cash long 50 bps (half entry/half exit, multiplicative as L.Sim).",
  "C6 stock-futures margin (NOT in mandate, assumption): 25% of notional, half in cash earning 1D rate, half by pledging cash-long shares; cash-long books scaled to 1/(1+0.125 x short notional per unit long); futures-long D2: legs at 1.0x equity each, all equity collateral at 1D rate; D4: short notional 1.0x equity, all equity collateral at 1D rate.",
  "C7 idle cash inside the long book follows frozen L.Sim (0 yield) so BASE is bit-identical; margin/collateral cash earns the 1D rate.",
  "C8 baselines (not variants): BASE, 5-seed random top-20 (liq2), EW universe, Nifty 500 price, cash (1D rate); for short legs a 5-seed random F&O short basket and random F&O long/short with the same engine/costs/carry/margin.",
  "C9 adoption rule (PREREG, binding): DEV phase-averaged daily gain vs BASE with paired NW t>=2 (lag 20) and maxDD worsening <= 3 pp; D0 judged vs EW universe (round-2 definition). Risk-reduction stats reported but cannot override the rule.",
  "Stress 80 bps: cash legs 80 bps; futures legs scaled by 80/50 (40 bps); hedge costs x1.6.",
  "Outcome tables: elig_base rows with valid 20d window; net = open[t+1]->close[t+20] - 50 bps; PROD deciles per date among elig_base rows with finite PROD (ex-ante); label classes ex-post (coherence only); market states from PIT mkt_dist_sma200 and mkt_mom20 at t."],
 "extra_variants": {
  "X1": "D2-K20-cash-beta: short notional per sleeve scaled by mean beta_60(long picks)/mean beta_60(short picks) at the signal date, clipped [0.5,1.5]. Reason: a dollar-neutral L/S whose short basket has higher beta is net short the market (boring beta explanation). Run once; adopted only under C9."}
}
C.save("predeclared", pre)
