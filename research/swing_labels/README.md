# Swing label study: what to train a 5–20 day NSE model on

Research into which label a 5–20 day swing-trading model should learn, run in October 2026 as three rounds of agent research on 5.75 years of NSE data (1 Jan 2021 – 14 Oct 2026). It is separate from the toolkit in the repository root and changes nothing there.

Read the report first: [`report/swing_label_study.html`](report/swing_label_study.html) (download and open it in a browser), or the published copy at https://claude.ai/artifact/5YxwFgcp5yuMCK7uLrBrAP.

## Findings in brief

- **Label.** A 20-day relative rank. For each stock and day, take the return from the next open to the close 20 trading days later, remove what shrunk market beta, 20-day volatility, log turnover and 12-1 month momentum explain (a per-day cross-sectional regression), and rank the remainder against every eligible stock that day. Top 30% = +1, bottom 30% = −1. Its event rate is 30/40/30 on every day. Direction labels ("did it go up?") swing from about 13% to 83% "up" and correlate 0.71–0.88 with the market's own 20-day return.
- **Results.** A weekly four-sleeve top-20 book made 30.3% a year against 12.0% for random picks on 2023–25, the selection window (average excess 15.3% a year, t 4.0). In the 2026 holdout it matched random picks (+0.4% a year, t 0.06). After a multiple-testing haircut, the forward planning estimate is about +4.4% a year over random picks.
- **Up and down.** Use −1 as a never-buy and exit list (+3.4% a year over the equal-weight market on 2023–25, +1.5% in 2026). Every short-selling variant lost money.
- **Process.** Rotate one sleeve a week in the opening session, hold 20 trading days with no stops, keep exposure fixed, stay under about ₹20 crore, check a weekly dashboard and follow a pre-set kill rule.

This is research, not investment advice.

## Layout

| Path | Contents |
|---|---|
| `report/` | The report, its template, and `build_report.py`, which injects `lab/results/_lead/report_data.json` into the template |
| `lab/download.py`, `lab/download_extra.py` | Download NSE bhavcopies (legacy and UDiFF formats), delivery files, index closes, weekend special sessions and book-closure records |
| `lab/build_panel.py`, `lab/ca.py` | Build the stock-day panel: ISIN-based identity, corporate-action adjustment from book closures, label blocks, segment breaks |
| `lab/lablib.py` | Features, eligibility filters, forward windows, walk-forward training and the daily mark-to-market book simulator |
| `lab/build_prod.py` | The ten-model production score, pre-registered in `lab/PREREG_R3.md` |
| `lab/r3common.py` | Shared round-3 helpers: phase-averaged books, cached baselines, paired tests |
| `lab/lead_atlas.py`, `lab/collect_report_data.py` | The event-rate atlas and the report's data file |
| `lab/sanity.py`, `lab/validate_sim.py` | Data and simulator checks; their outputs are the matching `.json` files |
| `lab/*BRIEF*.md`, `lab/round1_roles.md`, `lab/PREREG_R3.md` | The brief each research round worked from, and the round-3 pre-registration |
| `lab/workflows/round1.js` … `round3.js` | The multi-agent workflow scripts, including every agent's instructions |
| `lab/results/<agent>/` | Each agent's scripts and written report. Full `results.json` files are kept for the round-3 agents, their verifiers and the judges |
| `lab/results/_lead/` | Consolidated round summaries (`round1_results.json`, `round2_results.json`, `round3_exam.json`), the event-rate atlas and the report data |

## Reproducing

Not included, because they are large and the scripts regenerate them: the raw NSE downloads (about 0.7 GB), `panel.parquet` and `features.parquet` (about 0.7 GB), cached baselines and model scores (`*.npz`), and the per-agent `results.json` files of rounds 1–2 (about 10 MB; their headline numbers are in `lab/results/_lead/round1_results.json` and `round2_results.json`).

The core scripts find their files relative to their own folder. The briefs, workflow scripts and many agent scripts still name the temporary session folder they ran in. Point them at this folder first, from `research/swing_labels/`:

```bash
grep -rl "/tmp/claude-0" lab | xargs sed -i "s#/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab#$PWD/lab#g"
```

Then, from `research/swing_labels/lab/`:

```bash
pip install pandas numpy pyarrow duckdb lightgbm scikit-learn scipy
python download.py && python download_extra.py      # NSE files into raw/
python build_panel.py                                # panel.parquet, index.parquet, ca_events.parquet
python -c "import lablib; lablib.build_features()"   # features.parquet
python results/R3_devil/s1_label.py                  # the frozen 20-day label
python build_prod.py                                 # the production score, results/_lead/prod_h20.npz
```

Every other number traces to a script in the agent folder that saved it. The study used Python 3 with pandas 3.0, numpy 2.5, duckdb 1.5.6, LightGBM 4.7.0, scikit-learn 1.9.1, pyarrow and scipy. Random baselines use fixed seeds.

## Forward test

Data after 14 October 2026 is the clean exam. The frozen specification, retraining rule, success test, review and kill rules, and challengers are in the report's "What to expect" section and in `lab/results/R3_exam/results.json`.
