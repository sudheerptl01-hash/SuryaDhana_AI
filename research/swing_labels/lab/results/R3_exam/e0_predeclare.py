"""R3_exam stage 0: pre-declaration, saved BEFORE any R3_exam number is computed."""
import sys, time
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C
C.set_agent("R3_exam")
pre = {
 "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
 "note": ("Item 1 (independent re-computation) was done per builder by dedicated verifiers. R3_exam spot-checks "
          "what the verifiers flagged or could not reproduce, applies the PREREG adoption rule to every add-on, runs the "
          "final exam and writes the forward protocol. No selection variant is run here; every run below is a "
          "diagnostic or the pre-registered exam. 2026 is reported only."),
 "exam_definition": {
   "book": "frozen E0: weekly signal (step 5), 4 staggered sleeves, top-20 by score among elig_base, slot sizing, entry next open, pure 20-day time exit, forced exit at last valid close; 50 bps central, 80 bps stress",
   "scores": {"PROD": "results/_lead/prod_h20.npz (primary, pre-registered)",
              "single": "results/R3_devil/wf_main.npz (reported)",
              "ens3": "rank-average of R3_devil wf_main, wf_seed1, wf_seed2 (reported)"},
   "periods": {"dev": "2023-01-01..2025-12-31", "hold": "2026-01-01..end of data (2026-10-14)"},
   "phase_averaging": "5 weekly entry phases, daily returns averaged on common dates (C.phase_avg maths)",
   "baselines": ["5-seed horizon-matched random top-20 (cached, pre-registered)", "EW universe (cached, pre-registered)",
                 "25-seed random top-20 (seeds 1..25; spot-check SC1, diagnostic only)", "Nifty 500 price index (context)"],
   "primary_statistic": "annualised mean daily excess vs random, Newey-West t (lag 20)"},
 "forward_estimate_method": ("Inverse-variance (precision) weighted mean of the DEV excess and the 2026 excess. SE of each = "
     "annualised NW(20) standard error of the phase-averaged daily excess. DEV input = DEV excess after the devil's "
     "programme-wide Bonferroni (HLZ) haircut with N = 1,991 trials (primary); raw DEV and half-DEV as sensitivity. "
     "Computed vs 5-seed random (primary), vs EW, and vs 25-seed random."),
 "spot_checks": {
   "SC1": "R3_verify_R3_scen could not reproduce the 5-seed random CAGR with its own 100-book simulator (seed noise). Re-run the random top-20 with 20 extra seeds (6..25) per phase, DEV and 2026, 50 bps; report PROD excess vs the 25-seed baseline.",
   "SC2": "R3_verify_R3_twoway: D0 passes only vs EW, not vs the frozen book. Recompute D0 (EW minus PROD bottom 30%) phase-averaged vs EW and vs the frozen book, DEV and 2026.",
   "SC3": "R3_verify_R3_twoway could not reproduce 'Sharpe unchanged' for index hedges (raw vs excess-of-cash Sharpe). Compute the frozen book's Sharpe in excess of the Nifty 1D Rate from my own series, and D1a/D1b from R3_twoway's saved series.",
   "SC4": "R3_verify_R3_scen: NW lag-20 t on overlapping data may be inflated. Recompute the book-level PROD excess t with NW lags 20/40/60 and a non-overlapping 20-day-block t, DEV and 2026.",
   "SC5": "R3_verify_R3_risk: a live single-phase book is noisier than the phase average. Compute per-phase vs phase-averaged tracking error, DEV and 2026.",
   "SC6": "R3_verify_R3_book: Nifty 500 yardstick is a price index. Compute the Nifty 500 price CAGR on the exam calendars and a +1.2%/yr dividend total-return proxy."},
 "adoption_rule_application": ("Mechanical, from the builders' saved DEV numbers (verified by the verifiers): adopted iff the add-on "
     "is pre-declared (or a disclosed extra) AND executable under house rule 6 AND DEV paired NW t >= 2 vs the frozen "
     "baseline AND maxDD worsens by <= 3 pp. Post-hoc additions are labelled as such; a post-hoc add-on that passes the "
     "thresholds is adopted only as an execution convention whose skill is measured against a timing-matched baseline."),
 "variants_tested": 0,
 "variants_note": "0 selection variants. Diagnostics: 3 scores x 2 periods x 2 costs (exam), 1 extra random baseline (SC1), D0 re-run (SC2), statistics-only checks SC3-SC6."
}
C.save("predeclared", pre)
