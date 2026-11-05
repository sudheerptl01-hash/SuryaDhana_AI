# NSE bhavcopy panel: data-quality check

Panel: 1,735 sessions × 3,729 symbols (2019-10-01 → 2026-09-25).

## 1. Agreement with Yahoo adjusted closes
- Symbols in both sources: **1,496**; overlapping daily returns: **1,664,349**
- Days where the two differ by more than 1 point: **0.13%**; more than 5 points: **0.010%**
- One-day gaps > 20 points (missed or mis-dated corporate action in either source): **27** (listed in `qa_mismatches.csv`)
- Symbols with the most >5-point disagreements: VEDL (7), PTC (4), PNBGILTS (3), CGCL (3), GEOJITFSL (3), OFSS (3), SILVERTUC (3), COALINDIA (3), SILGO (3), SANOFI (3)

## 2. Corporate actions
- Events applied: **1,064** ({'gap_heuristic': 712, 'yahoo_split': 318, 'yahoo_confirmed_raw': 17, 'gap_heuristic_yahoo_name': 17})
- Gap rule scored against Yahoo on 395 known splits/bonuses: recall **72%**, precision **88%** (37 gaps flagged with no Yahoo split within 7 days)

## 3. Survivorship: what the Yahoo-only universe was missing
- Symbols traded in EQ series since 2019-10-01: **3,418**
- Not in today's instrument list: **1,922**, of which **163** were liquid (≥ ₹10 Cr median turnover at some point)
- Stopped trading 30+ days before the last session: **766**
- Examples (liquid, missing from the old universe): 3IINFOLTD, 3IINFOTECH, ADANIGAS, ADANITRANS, AEGISCHEM, AHL, AKZOINDIA, AMARAJABAT, AMIORG, ANDHRAPAP, ANGELBRKG, AVADHSUGAR, BANSALWIRE, BARBEQUE, BURGERKING, CADILAHC, CAPILLARY, CENTRUM, CENTURYTEX, CIGNITITEC, CMRGREEN, CORDELIA, DAAWAT, DBREALTY, DEEDEV, DEN, DHANI, DIAMONDYD, DIGITIDE, DISHTV
