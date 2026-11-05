# Feature Research Brief — integration status (15 Oct 2026, ~04:15 IST)

Owner asked whether the India Equity Feature Research Brief (companion brief) is integrated.
Answer: it is the single most-integrated document in the repo — snapshotted, claim-tested, and
data-ingested — with the matrix (`alpha_lab/reports/claims_matrix.md`) as the record. This note
updates the matrix rows whose status CHANGED since it was written on 14 Oct.

## Integration levels (as of the matrix, 14 Oct)
1. **Snapshotted**: `alpha_lab/inputs/feature_research_brief.md` (sections 1–10, its IDs kept).
2. **Claim-tested**: ~70 distinct claims mapped; 24 already measured in-repo (EP 38-condition
   frame, HO, RD, FII, ML, IL, VA, POC, HS studies); its §13 protocol = the house gauntlet;
   its §1 P1 list = matrix §B top-5 pre-registered specs.
3. **Data-ingested**: every free §11 source with history (fo_daily 2019-10→, participant OI,
   deals/bulk/block, MTF, insider, shareholding, bhavcopy 2010→, VIX 2009→, results/XBRL).

## Status changes since the matrix (Alpha Lab night + the world-class sprint)
| Matrix row | Was | Now |
|---|---|---|
| FUT-04/05 excess carry | UNTESTED-testable-now (top candidate) | **TESTED — passed its pre-registered bar** during Alpha Lab (first robust F&O-derived signal; alpha_lab FINDINGS) |
| FUT-06 rollover (per-expiry split "not stored") | UNTESTED-needs-data | **Data gap part-closed**: W2 built the derived per-expiry futures panel from UDiFF bhavcopies (Jul-2024→, 356k rows, OI reconciles to the share) + rollover/basis history live on the DERV page |
| §6.1–6.5 futures mechanics (price×OI, basis, rollover, activity) | features only | **Live UI**: DERV term structure, basis history, rollover tracker, VIX panel |
| §7 options Greeks/IV plumbing | needs per-strike | **Partial**: OSTR computes B-76 IV/Greeks/payoffs live from the chain; per-strike HISTORY still missing (unchanged for OPT-02/03/04/06/10/12/13) |
| FG part II order-flow ("Breeze L1 could record forward data") | UNTESTED-needs-tick-data | **Recording now exists**: W6 tick store persists live ticks to parquet (forward-only; history still impossible) |
| §8 positioning (POS-01/02/03) | being tested | TESTED-NO-EDGE (FII study) — panel kept as context, matches the matrix |

## Still open from the brief (unchanged, honest)
- **P1 tests queued, specs pre-registered in matrix §B**: OPT-08 O/S ₹-volume proxy ·
  POS-05 variance risk premium · POS-06 index OI-PCR · EVT-03 F&O exclusion events.
- **Needs data not yet ingested**: per-strike option archives (§12 recipe is the build plan),
  MWPL/ban archives (FUT-03, tradability filter only), index membership-change history (EVT-01),
  lock-in/QIP/ratings/pledge feeds (EVT-04/05/07/08).
- The contradictions section (§D) stands: splits, abnormal volume, build-up quadrants and
  FII extremes all measured weaker/inverted in India vs the imported priors.
