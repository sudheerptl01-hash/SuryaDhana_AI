"""R3_risk pre-declaration: written and saved BEFORE any R3_risk number is computed."""
import sys, time
sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab")
import r3common as C
C.set_agent("R3_risk")
C.save("predeclared", {
    "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "note": ("Saved before any R3_risk number was computed. The REPORT text is stored in results.json "
             "(section report_md) and in the structured answer: this subagent is instructed not to write "
             "report .md files."),
    "book": "Frozen PROD book (PREREG_R3): weekly step 5, 4 staggered sleeves, top-20 slot sizing, 20d time exit, "
            "elig_base (liq2), 50 bps central / 80 bps stress, phase-averaged over the 5 weekly entry phases.",
    "item1_drawdowns": {
        "window": "contiguous 2023-01-01 -> 2026-10-14, phase-averaged",
        "episode_definition": "peak (new equity high) -> trough (min before recovery) -> recovery (first close >= peak); "
                              "non-overlapping episodes ranked by depth; top 5",
        "comparators_same_window": ["Nifty 500 (price index, no dividends)", "EW universe book (same calendar/costs)",
                                    "5-seed random top-20 (same mask)"],
        "monthly": "calendar-month compounded returns; mean/median/sd/percentiles/% positive; % months beating random, EW, Nifty 500"},
    "item2_exposure_policies": {
        "list": {"X100": "100% invested (frozen baseline)",
                 "X80": "80% invested at every sleeve rebalance, 20% in Nifty 1D Rate Index",
                 "X60": "60% invested at every sleeve rebalance, 40% in Nifty 1D Rate Index",
                 "G50": "breadth50 (signal-date close) < 0.5 -> that sleeve invests 50% (rest Nifty 1D Rate) until its next rebalance; else 100%"},
        "books_periods": {"PROD": ["dev", "hold"], "EW_universe": ["pre 2021-09-01..2022-12-31", "dev", "hold"]},
        "pre_note": "No PROD scores exist before 2023 (walk-forward); PRE uses the EW-universe book only.",
        "stats": ["CAGR", "vol", "Sharpe", "maxDD", "Calmar", "avg exposure", "paired diff vs X100 + NW t (lag 20)"],
        "adoption": "PREREG rule applied to G50 (DEV paired NW t >= 2 and maxDD not worse by > 3 pp). X80/X60 are "
                    "risk-budget dials, reported as a menu, not alpha add-ons."},
    "item3_expectations": {
        "method": "circular block bootstrap, blocks {20, 40 (primary), 60} trading days, 10,000 paths of 504 days",
        "source": "phase-averaged daily excess (PROD book - 5-seed random) on DEV (primary); contiguous 2023-01..2026-10 as sensitivity",
        "shift": "series demeaned then shifted to +5%/yr (planning) and to 0%/yr (dead book)",
        "excess_definition": "sum of daily excess returns over the window (arithmetic)",
        "outputs": ["6/12/24-month excess percentiles", "P(excess < 0) per horizon", "P(negative excess year)",
                    "absolute return = EW universe daily + shifted excess (joint blocks; EW at its historical source-window mean)"]},
    "item4_kill_rules": {
        "singles": {"K1": "rolling 6-month (126d) excess sum < -5%",
                    "K2": "rolling 3-month (63 signal dates) mean matured rank IC < 0.02; IC of signal date t is known at t+20, "
                          "so at check date T the window is signal dates (T-20-62 .. T-20)",
                    "K3": "rolling 12-month (252d) excess sum < 0"},
        "extra_variants_justified_in_advance": {
            "C1_review": "K1 OR K2 OR K3 (a review trigger: maximise detection, accept false alarms)",
            "C2_kill": "K3 AND K2 at the same weekly check (money AND signal both failing; protects against "
                       "monetisation luck such as 2026 where IC was intact but excess ~0)",
            "C3_kill_fast": "K1 AND K2 at the same weekly check (faster version of C2)"},
        "checks": "weekly (every 5 trading days) over the first 24 months (504 days) of live trading; a rule can fire only "
                  "once its window is full",
        "hypotheses": {"H1a": "+5%/yr excess, IC mean = PROD DEV IC (IC intact, monetisation weaker, as in 2026)",
                       "H1b": "+5%/yr excess, IC mean = PROD DEV IC x (0.05 / PROD DEV excess) (IC proportional to excess)",
                       "H0": "0%/yr excess, IC mean 0 (dead book)"},
        "resampling": ["joint circular block bootstrap of daily (excess, IC) pairs on DEV, blocks 20/40/60 (dependence-preserving)",
                       "persistence-matched null books: random scores = sqrt(w)*entity constant + sqrt(1-w)*AR(1)(rho) "
                       "fitted to PROD's own rank autocorrelation (lags 5, 250); each null book's own phase-averaged "
                       "excess and IC series evaluated in rolling 24-month windows (H0 directly; H1 by adding the drift)"],
        "iid_reference": "an iid daily bootstrap is shown ONLY to illustrate the bias of ignoring dependence; never used to calibrate",
        "historical": "the rules' behaviour on the actual 2023-2026 PROD book is reported (DEV and 2026)",
        "dashboard": ["matured weekly rank IC (and 13-week mean)", "top-20 relative hit rate (label pct > 0.5) and absolute hit (net > 0)",
                      "avoid-tail (bottom 30%) realised 20d return minus universe", "turnover (top-20 overlap with the same sleeve's previous list; round trips/yr)",
                      "slippage vs open (backtest fills at the official open; budget from the 50 bps cost model)"]},
    "variants_count_plan": "exposure 4 policies (X100 baseline + 3) x books; kill rules 3 singles + 3 extras; "
                           "bootstrap block lengths are sensitivity settings, not selections"})
