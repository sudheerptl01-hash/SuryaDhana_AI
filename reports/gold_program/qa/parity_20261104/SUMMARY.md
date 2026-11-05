# Parity: UI release 20261025-223942 (A, pre-gold) vs 20261104-230634 (B, gold) — 4 Nov 2026 23:12–23:48 IST

Harness: `scripts/desktop_qa/parity.py --browser both --tabs all`, side A served by `scratch_server.py --block-mutations`
on :8091 (static export of the old release, /api forwarded to the live ui-api), side B the live ui-api :8010.

| Engine | PARITY | DIFF | NEW |
|---|---|---|---|
| Chromium | 38 | 4 | 1 (gold) |
| WebKit | 38 | 4 | 1 (gold) |

The four DIFFs, read one by one:
- **ostrategy, discovery, mcxgold** — every reason is a side-A artefact: the scratch server answers the pages' POSTs
  (`/api/options/strategy/analyze`, `/api/alpha/scan`, `/api/mcx/ticket`) with 403 (`--block-mutations`), so A logs a
  "Forbidden" console error and a 4xx class that B (live, 2xx) does not; discovery's extra B request
  (`/api/market/surveillance`) follows from the scan succeeding on B only. Not a build difference.
- **commodity** — table header `DRIVER | AT MCX CLOSE | NOW | CHANGE | IMPACT ON MCX` exists on A only: the pre-open desk
  moved from CMDT to the GOLD page (PLAN §b, repetition rule T9). Intended.
- **gold** — NEW page (43rd), no A side.

Verdict: 42/42 shared pages at parity once the harness artefacts and the one intended removal are set aside; 1 new page.
Log: `parity.log` (the trailing `TargetClosedError` lines are Playwright teardown noise after the run completed).
