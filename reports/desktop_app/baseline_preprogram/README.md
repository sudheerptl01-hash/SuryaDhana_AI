# Pre-program UI baseline (24 Oct 2026, 10:38 IST): reconstruction and parity against live :8010

Owner: FX-QA (desktop program fix round 1). This closes C3-logic-unchanged-03: the parity baseline served on :3000
was rebuilt on 24 Oct at 15:32 and already contained the program's UI code, so a parity check against it could not
show that the UI logic is unchanged. This directory holds a **true pre-program baseline**. It is the ui/ source tree
as it was before the desktop program started (FEASIBILITY.md, 24 Oct 2026 10:38 IST), reconstructed and proven
byte for byte, then built with the same release builder as the live release and compared tab by tab against the live
terminal on :8010.

**Verdict: the desktop program left the terminal's UI logic unchanged.** Of 84 tab × engine comparisons (42 tabs
in Chromium and WebKit), **78 are PARITY**. The other 6 (OSTR, ALFA and MCXG, in both engines) differ only because
the QA harness refuses those pages' on-load compute POSTs on side A. With the same refusal on both sides (§4.2), all
6 are PARITY too. Every `/api` endpoint is called equally often on both sides: 1,060 vs 1,061 calls in Chromium and
1,058 vs 1,059 in WebKit, the one extra call being the harness-caused ALFA flag fetch. B passes the audit with no
failures in either engine. The browser-visible differences that remain are the intended program changes in §5
(E1–E15): the boot gate, the prefs GET, the /health and /build-info.json probes, self-hosted fonts (σ and ₹ glyph
sources change), visible toasts, the tab warm-up and a few more. None of them touches data, API or trading logic.

## 1. What was compared

| side | what | identity |
|---|---|---|
| **A** (reference) | the reconstructed pre-program ui/ tree, built as a static export by `build_baseline.sh` and served by `scripts/desktop_qa/scratch_server.py --block-mutations` on **:8097**. The server serves the files itself and forwards `/api`, SSE, WS, `/health` and `/version` to live :8010 | tree sha256 `948a92da6e08783f7907a57cf73235206c39265a9b3127164c01314b86f2322a` (sha256 of `MANIFEST.sha256`, 134 files) · export id `20261025-121228-0000000` · build `source_sha256` `091f2afaa1e7ae7955067e905d797a13be2087717015b0efc8e13b18ed59e647` |
| **B** (candidate) | the **current live** terminal at http://127.0.0.1:8010 (ui-api serving `ui/dist/current`) | `GET /version` → `ui_build.id` **`20261025-114737-0ae66db`**, built 2026-10-25T06:17:51Z, `source_sha256` `dbced9ef5697e547af1558ae439da1b4688b8230eea6d7adff3440c71068abd3` |

The `index.html` that :8010 serves is byte-identical to `ui/dist/releases/20261025-114737-0ae66db/index.html`
(sha256 `5e949c0c…`), and :8097 serves the baseline export's (`d77071b9…`). The release id did not change during the
runs: `GET /version` returned the same id at 12:03, at 12:32 and at 12:59, after all browser runs.

Both sides talk to the same backend (live :8010). Both run the same engine in the same run, tab by tab, interleaved A
then B, so the market state is the same. Prefs mode is `readonly` on both (parity.py default): B hydrates from the
server but never writes, and A has no prefs code.

## 2. How the baseline was reconstructed

### 2.1 Starting copy

`ui/` was copied **at 2026-10-25 11:58:02 IST**, before anything else, with
`rsync -a --exclude node_modules --exclude .next --exclude .next-prod --exclude dist`. That is 173 files with their
mtimes kept; the per-file checksums are in `records/snapshot_20261025T115802IST.sha256`. FX-UI was editing ui/ at
the same time, so two checks pin the copy down:

- **No concurrent edit inside the copy.** Every file changed on 25 Oct carries the PM integration time (11:04:48) or
  the PM's build_ui test fix (11:05:11), and nothing is newer.
- **The copy is exactly the source of the live release.** `ui/scripts/release.mjs stage` (the builder's own source
  hash) over the copy gives `dbced9ef…abd3`. That equals the `source_sha256` the live :8010 release reports in
  `/version` and `/build-info.json`.

### 2.2 Recorded changes, reversed newest first (`tools/reconstruct.py`)

Every reversal asserts that the text it removes occurs **exactly once**, so an edit inside a recorded block makes
the script fail. Outside the blocks the snapshot's mtimes are checked: every file no record touches must predate the
program, and every touched file must be dated at the time of the last record that changed it (±slack), so an
unrecorded edit made after that record, anywhere in the file, also fails (`tools/test_reconstruct.py`
`test_unrecorded_edit_outside_the_recorded_blocks_of_a_touched_file_is_refused`). The recorded inputs themselves
(the parsed D3.md/D4.md blocks and `records/`) are pinned by sha256 (`RECORDS_SHA256`). What the snapshot cannot show
is an edit outside the blocks made *before* a file's last recorded change; that window is covered by the transcript
scans (`records/program_writes.tsv`, `records/bash_write_scan.tsv`) and by the PM backup, whose files must equal the
intermediate state and be dated before the program or at a recorded change.

| # | change (when) | source of truth used for the reversal | files |
|---|---|---|---|
| 1 | PM integration (25 Oct 11:04:48): **D4 P1–P11** and **D3 1d** | `patches/D4.md` and `patches/D3.md` §1, parsed the same way as the PM's `apply_patches.py` (15 D4 blocks, including P9a, the new file `lib/pageKeys.ts`, whose content is checked before it is dropped) | app/page.tsx (P1, P7, P8), MarketCommandHeader (P2), NewsTerminal (P3), StockDetailModal (P4), ToastContext (P5), ErrorCatcher (P6), Compare/OptionChain/DealsMonitor/CommandBar (P9b–e), AlphaDiscoveryDesk (P10), tailwind.config.ts (P11), AppContext (1d) |
| 2 | D3 call sites (24 Oct 11:30:55) | the **exact (old, new) pairs of D3's own edit script** (tool call `toolu_018xe8VnoyKCczBHhdv9FHe7`, 06:00:55 UTC), parsed with `ast` (`records/d3_callsites.json`, 14 pairs). Each pair is cross-checked against its D3.md §2 block, see §6.1 | lib/alerts.ts, components/WatchMonitor.tsx, lib/backtestExport.ts, components/ResearchLibrary.tsx, components/CommandBar.tsx (2 `window.open` lines + import), components/terminal/index.tsx (CSV helper) |
| 3 | D4 full rewrites (24 Oct 11:28 / 11:31) | the originals that D4 **printed before writing them** (`cat`, 05:39:02 UTC, `records/originals/app/`). Before restoring, the current files must be byte-identical to D4's Write payloads (sha256 `60686d60…` and `73989c2b…`) | app/layout.tsx (Google Fonts links back, `PlatformShell` wrapper, viewport, inline background and font preloads gone), app/global-error.tsx (**restored, not deleted**: it existed before the program, see §6.2) |
| 4 | D4 append to app/globals.css (24 Oct 11:31–11:50) | D4's first full `Read` (05:39:06 UTC): 203 lines. The current file must start with exactly those bytes, and the remainder must open with the `Desktop program (D4) — APPEND-ONLY SECTION` marker (366 − 203 lines) | app/globals.css |
| 5 | D1 next.config.js (24 Oct 11:15) | D1's first `cat` (05:38:58 UTC, before its Write at 05:45:15 UTC). The current file must equal D1's Write payload (`5d0f4815…`) | next.config.js (**not git HEAD**, see §6.2) |
| 6 | files the program created | left out: `components/desktop/` (10, including its `__tests__`), `lib/platform/` (5), `lib/prefs/` (3), `lib/__tests__/{platform,prefs}.check.ts`, `lib/pageKeys.ts`, `public/fonts/` (11; `public/` itself existed, empty), `scripts/` (D1's builder and tests, 5) | 37 files |
| – | not source | `tsconfig.tsbuildinfo` (tsc's incremental cache, rewritten by a tsc run on 24 Oct 16:26) and `.gstack/` (git-ignored local tool state from May). The release builder's stage step excludes both | 2 files |

`records/` holds every piece of evidence the reversal reads, with provenance (transcript, tool_use id and UTC
timestamp in `records/provenance.json`), except the D4.md and D3.md blocks, which `tools/reconstruct.py` reads from
`reports/desktop_app/patches/`; all of these inputs are pinned by one sha256 (`RECORDS_SHA256`), so a later edit of a
patch block is refused instead of silently changing the reconstruction. `tools/extract_records.py` regenerates them from the program's agent
transcripts (read only), and a re-run gives byte-identical records.

### 2.3 Proof that the result is the pre-program tree

All of these run inside `reconstruct.py` and are recorded in `reconstruct_report.json` → `checks`:

1. **Forward replay.** Applying the same records forward to the reconstructed tree gives back the starting copy
   byte for byte (19 patched files, plus the 3 rewrites and globals.css, which are exact by construction).
2. **PM backups.** After step 1 is undone, all 13 files of the PM's pre-patch backup
   (`~/.suryadhana_pm_backups/desktop_integration_20261025-110448/ui/…`, taken by `apply_patches.py` just before it
   wrote) are byte-identical to the intermediate state. This independently confirms every D4 P-block and D3 1d.
3. **Inventory.** The reconstructed `ui/` top level, `app/` (6), `components/` (80), `lib/` (22) and `public/` (0)
   equal the `ls` that D4 ran at 05:39 UTC, before any program write (`records/inventory_0539Z.txt`).
4. **Nothing else changed.** Every snapshot file outside the recorded set has an mtime before 24 Oct 10:38 IST.
Items 1–4 are recorded in `checks`. Item 5 comes from two transcript scans:

5. **Every write the agents made.**
   - Write/Edit calls on a ui/ source path across all the session's agents and the PM (`records/program_writes.tsv`,
     from `extract_records.py`): 32 calls on 29 paths. 26 of the paths are files the program created. The other 3 are
     pre-existing files rewritten in one Write each: D4's layout.tsx and global-error.tsx and D1's next.config.js.
     Their payloads equal the snapshot (§2.2 rows 3 and 5).
   - Bash commands that name a pre-existing ui/ file and contain any write construct (`tools/scan_bash_writes.py`
     → `records/bash_write_scan.tsv`, 36 commands up to the starting copy). Each was read. Two of them change a
     pre-existing ui/ file: D3's call-site script (06:00:55 UTC) and D4's globals.css append (06:01:45, 06:15:37 and
     06:20:09 UTC). Both are recorded. The rest read ui/ files and write only to scratch or temp copies (D1/D4 build
     staging, D3's tsc scratch, critics' scratch), to `desktop/`, or to `ui/scripts/` (D1-owned, new).
   - The PM's 25 Oct integration ran through `apply_patches.py`, which is the D4/D3 1d record.

   No write to a pre-existing ui/ file falls outside the records.

Further independent checks:

- **What the agents saw before they edited** (`tools/crosscheck_reads.py`, result in `records/crosscheck_reads.json`):
  1,243 original lines, from `Read` results and direct `grep -n` output that agents produced of a touched file
  before its first program modification, equal the reconstructed file at the same line number. 5 more match as
  `cut -c`-truncated prefixes. The 4 remaining hits are `scripts/ui_audit.py` grep output that the scanner
  attributes to `app/page.tsx`, because the command names both files (listed in the JSON). No genuine mismatch.
- `lib/backtestExport.ts`, `context/AppContext.tsx`, `context/ToastContext.tsx` and `tailwind.config.ts` reconstruct
  **byte-identical to git HEAD** (14 Jun). The other touched files also changed between June and October, so git
  cannot confirm them.
- **tsc is clean** on the reconstructed tree: `tsc --noEmit --incremental false -p tsconfig.json` exits 0, with
  121 project files checked and no program file among them. A deliberately broken copy fails (TS2322), which shows
  the run really type-checks. tsc on the starting copy is clean too.
- **D1's claim holds** against the *true* pre-program `next.config.js`: the resolved Next config
  (`ui/scripts/print-next-config.mjs`) for `dev`, `build` and `start` (`NEXT_DIST_DIR=.next-prod`) is identical
  between the pre-program file and the current one once the project dir is masked: sha256 `224618f3…` (dev) and
  `d29615c9…` (build/start), the same on both sides. Git HEAD differs from both (`distDir` `.next` instead of
  `.next-prod` under `UI_MODE=prod`).
- `tools/test_reconstruct.py` (10 tests) rebuilds a full post-program snapshot from the committed baseline plus the
  records, then requires the reconstruction to return exactly `MANIFEST.sha256`. Its negative tests require a
  refusal for each of: an edit inside a recorded block, an edit of an untouched file dated after the program start
  (and acceptance of the same edit once it is back-dated), a rewritten file that is not the recorded Write, and a
  globals.css whose original part changed.

### 2.4 Diff summary: reconstructed tree → starting copy

This is exactly the set of recorded changes (`diff_vs_snapshot.patch` holds the full unified diff, 630 lines):

| file | +lines | −lines | records |
|---|---:|---:|---|
| app/global-error.tsx | 47 | 4 | D4 Write (ChunkLoadError auto-reload; dark html) |
| app/globals.css | 163 | 0 | D4 append-only section (fonts, shell offset, strip, banner, gate) |
| app/layout.tsx | 26 | 9 | D4 Write (PlatformShell, self-hosted font preloads, viewport, inline bg) |
| app/page.tsx | 31 | 3 | D4 P1, P7, P8 |
| components/AlphaDiscoveryDesk.tsx | 1 | 1 | D4 P10 |
| components/CommandBar.tsx | 4 | 5 | D3 2e (2 pairs), D4 P9e |
| components/Compare.tsx · DealsMonitor.tsx · OptionChain.tsx | 2 each | 1 each | D4 P9b, P9d, P9c |
| components/ErrorCatcher.tsx · MarketCommandHeader.tsx · StockDetailModal.tsx · news/NewsTerminal.tsx | 1 each | 1 each | D4 P6, P2, P4, P3 |
| components/ResearchLibrary.tsx | 3 | 1 | D3 2d |
| components/WatchMonitor.tsx | 3 | 1 | D3 2b |
| components/terminal/index.tsx | 2 | 5 | D3 2f |
| context/AppContext.tsx | 14 | 0 | D3 1d |
| context/ToastContext.tsx | 2 | 1 | D4 P5 |
| lib/alerts.ts | 2 | 3 | D3 2a |
| lib/backtestExport.ts | 8 | 9 | D3 2c |
| next.config.js | 41 | 1 | D1 Write (static-export branch; dev/prod object unchanged) |
| tailwind.config.ts | 1 | 0 | D4 P11 |

Plus the 37 program-created files and the 2 non-source files listed in §2.2. That makes 134 + 37 + 2 = 173, the
whole starting copy.

### 2.5 Checksums

| artefact | sha256 |
|---|---|
| `baseline_src.tar.gz` (the reconstructed tree, 134 files, no node_modules) | `c362629b63be12d1e7df2e7e1d5fdc32d53fb89b7bb7ca7150c68a6617136753` |
| `MANIFEST.sha256` (= tree id) | `948a92da6e08783f7907a57cf73235206c39265a9b3127164c01314b86f2322a` |
| `build/build_ui.sh` (frozen; the builder that built the live release, with the PM's 11:06 fix) | `0b6ce8712001a8960ea7d72bbecb86703f17dd8c56f40ff9bf0e869c2e181e95` |
| `build/release.mjs` (frozen) | `281890fb0070dfa64956e86be79eec4bb2a7ace5c8e67cba81223e5d4d69928e` |
| `build/next.config.export.js` (the program's next.config.js, used only to build) | `5d0f48155f1de3ce6fb14b5c16caa4988017bdcb5e59195851171ef154d52524` |
| `records/originals/app/layout.tsx` · `global-error.tsx` · `globals.css` · `next.config.js` | `ccea2b91…7cfa` · `c52c7006…439f` · `fb4f4918…56b1` · `d2267d45…e468` (full values in `records/provenance.json`) |

## 3. Building it (`build_baseline.sh`)

```bash
reports/desktop_app/baseline_preprogram/build_baseline.sh --out <scratch>/baseline_export
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/scratch_server.py --ui <scratch>/baseline_export \
    --port 8097 --block-mutations
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/parity.py --a http://127.0.0.1:8097 \
    --b http://127.0.0.1:8010 --browser both --out reports/desktop_app/baseline_preprogram/parity
```

The script extracts `baseline_src.tar.gz` and checks every file against `MANIFEST.sha256` (no extra, no missing). It
lays out the minimal mirror repo that `ui/scripts/build_ui.test.mjs` `makeRepo()` uses: frozen `build/build_ui.sh`
and `build/release.mjs`, the real `ui/node_modules` symlinked (never written), and `build/next.config.export.js` as
`next.config.js`. The pre-program config has no static-export branch, and §2.3 shows that the two resolve identically
for dev and prod. It then runs `build_ui.sh --out`, so staging, export, verification, gzip siblings and
`build-info.json` come from the same code as a live release. The repo's `ui/`, `ui/.next*`, `ui/dist`,
`tsconfig.json` and `next-env.d.ts` are never written; their checksums were verified before and after. The builder
copies are frozen because `scripts/build_ui.sh` changed on disk during this round (another fixer), so later rebuilds
stay comparable. `--tree <dir>` builds from an already extracted copy instead of the tarball; it is still checked
against the manifest, so only the baseline can be built.

The result: 65 files, 2.92 MB (57 gzip siblings, 893.7 kB), built in 10.7 s with Next 15.5.18 and no build warnings
beyond Node's `--localstorage-file` notice. The route `/` is 155 kB, with 259 kB first-load JS.

**Reproducible.** A second build from the committed tarball (12:35) produced the same `source_sha256` (`091f2afa…`),
and identical CSS. 106 of the 111 files under `_next/static/chunks` are byte-identical with the same names. The other
5 are the three app entry chunks (`page`, `layout`, `global-error`) and their gzip siblings, which differ only in
webpack's numeric module ids and, with them, the key order. Those ids derive
from the staging path, which contains the release id, so every pair of `build_ui.sh` builds differs this way; live
releases do too.

Static comparison of the two exports (A = baseline, B = live `20261025-114737-0ae66db`):

| | A (pre-program) | B (live) |
|---|---|---|
| `index.html` | 26,930 B: prerendered terminal chrome | 7,422 B: prerendered BootGate only |
| `<head>` | `preconnect` fonts.googleapis.com / fonts.gstatic.com, Google Fonts stylesheet | `preload` `/fonts/jetbrains-mono-v24-latin.woff2` + `/fonts/chakra-petch-v13-700-latin.woff2`, `theme-color`, `color-scheme: dark` |
| `<html>` / `<body>` | `class="dark"` / `class="terminal"` | plus inline `background:#05070a` (and `color-scheme:dark` / `color:#d6dbe4`) |
| first-load JS (scripts referenced by index.html, gzip -9) | 8 files, 291.9 kB gz | 10 files, 295.3 kB gz |
| CSS | 13.2 kB gz | 15.2 kB gz (D4 section + P11 toast utilities) |
| other files | — | `fonts/` (8 woff2 + 2 OFL + README), carried-forward chunks of the previous release |

## 4. Parity result: pre-program baseline (A) vs live :8010 (B)

`scripts/desktop_qa/parity.py --a http://127.0.0.1:8097 --b http://127.0.0.1:8010 --browser both
--out reports/desktop_app/baseline_preprogram/parity` (defaults: prefs `readonly`, platform-seam exclusion on, dwell 3 s,
observe 12 s, 1 retry for a DIFF). Full report: `parity/parity.md`, `parity/parity.json` and the console log
`parity/parity_console.log`. Run 12:14:33–12:51:27 IST (2,214 s); parity.py exit code 1, which is its documented
code for "at least one DIFF". Harness versions: the main run loaded `scripts/desktop_qa/parity.py` and `probe.py` as
of 11:08 (`probe.py` sha256 `9288273d…`). Another fixer edited `parity.py` at 12:22 while the run was in progress;
the change visible in the file is the `--a` help text. The §4.2 re-probe used that newer file (`46c8fa15…`).

### 4.1 Main run

A = `http://127.0.0.1:8097` (pre-program baseline (reconstructed, served on scratch :8097)) · B = `http://127.0.0.1:8010` (live :8010 release 20261025-114737-0ae66db) · started 2026-10-25T12:14:33+05:30 · 2213.8 s · seam exclusion True

- **chromium** (155.0.8059.85): 39/42 PARITY · DIFF: ostrategy, discovery, mcxgold · A audit failures: ostrategy, discovery, mcxgold · B audit failures: none
- **webkit** (26.4): 39/42 PARITY · DIFF: ostrategy, discovery, mcxgold · A audit failures: ostrategy, discovery, mcxgold · B audit failures: none

| tab | code | chromium verdict | chromium ready A/B ms | webkit verdict | webkit ready A/B ms | B-only seams |
|---|---|---|---|---|---|---|
| brief | BRF | PARITY | 823/512 | PARITY | 798/534 | GET /api/prefs |
| watch | WTCH | PARITY | 439/463 | PARITY | 455/487 | GET /api/prefs |
| charts | CHRT | PARITY | 448/471 | PARITY | 493/513 | GET /api/prefs |
| compare | COMP | PARITY | 450/464 | PARITY | 472/492 | GET /api/prefs |
| screen | FUND | PARITY | 449/447 | PARITY | 496/479 | GET /api/prefs |
| alerts | ALRT | PARITY | 452/437 | PARITY | 1614/487 | GET /api/prefs |
| eco | ECO | PARITY | 493/502 | PARITY | 515/488 | GET /api/prefs |
| seag | SEAG | PARITY | 451/440 | PARITY | 495/475 | GET /api/prefs |
| memb | MEMB | PARITY | 436/455 | PARITY | 448/478 | GET /api/prefs |
| options | OMON | PARITY | 498/454 | PARITY | 468/507 | GET /api/prefs |
| ostrategy | OSTR | DIFF → symmetric re-probe: **PARITY** | 446/500 | DIFF → symmetric re-probe: **PARITY** | 475/500 | GET /api/prefs |
| derivatives | DERV | PARITY | 450/500 | PARITY | 524/510 | GET /api/prefs |
| insiders | INSD | PARITY | 453/449 | PARITY | 475/428 | GET /api/prefs |
| deals | DEAL | PARITY | 189/506 | PARITY | 467/515 | GET /api/prefs |
| preopen | PRE | PARITY | 449/456 | PARITY | 479/585 | GET /api/prefs |
| ipo | IPO | PARITY | 450/197 | PARITY | 499/490 | GET /api/prefs |
| movers | MOV | PARITY | 451/460 | PARITY | 495/485 | GET /api/prefs |
| wrap | WRAP | PARITY | 444/456 | PARITY | 489/506 | GET /api/prefs |
| filings | CF | PARITY | 247/459 | PARITY | 440/492 | GET /api/prefs |
| margin | MRGN | PARITY | 437/437 | PARITY | 458/501 | GET /api/prefs |
| holders | HDS | PARITY | 432/200 | PARITY | 452/531 | GET /api/prefs |
| world | WEI | PARITY | 124/511 | PARITY | 510/501 | GET /api/prefs |
| desk | DESK | PARITY | 440/449 | PARITY | 509/497 | GET /api/prefs |
| markets | MKT | PARITY | 192/454 | PARITY | 445/486 | GET /api/prefs |
| events | EVTS | PARITY | 191/450 | PARITY | 490/477 | GET /api/prefs |
| overview | OVRV | PARITY | 494/192 | PARITY | 562/489 | GET /api/prefs |
| stocks | EQS | PARITY | 735/750 | PARITY | 1608/1152 | GET /api/prefs |
| backtest | BTST | PARITY | 453/461 | PARITY | 471/482 | GET /api/prefs |
| positions | PORT | PARITY | 239/502 | PARITY | 446/491 | GET /api/prefs |
| broker | BRKR | PARITY | 451/458 | PARITY | 498/429 | GET /api/prefs |
| pipeline | PIPE | PARITY | 435/607 | PARITY | 461/482 | GET /api/prefs |
| scanner | LWSC | PARITY | 435/593 | PARITY | 873/478 | GET /api/prefs |
| discovery | ALFA | DIFF → symmetric re-probe: **PARITY** | 233/441 | DIFF → symmetric re-probe: **PARITY** | 193/476 | GET /api/prefs |
| commodity | CMDT | PARITY | 1530/505 | PARITY | 469/1009 | GET /api/prefs |
| mcxgold | MCXG | DIFF → symmetric re-probe: **PARITY** | 444/447 | DIFF → symmetric re-probe: **PARITY** | 468/532 | GET /api/prefs |
| glassbox | GBOX | PARITY | 444/452 | PARITY | 486/499 | GET /api/prefs |
| mlengine | MLEN | PARITY | 143/457 | PARITY | 494/505 | GET /api/prefs |
| explorer | DEXP | PARITY | 450/455 | PARITY | 442/430 | GET /api/prefs |
| warehouse | WHSE | PARITY | 540/181 | PARITY | 605/563 | GET /api/prefs |
| research | RSCH | PARITY | 438/454 | PARITY | 441/474 | GET /api/prefs |
| risk | RSK | PARITY | 439/528 | PARITY | 491/476 | GET /api/prefs |
| system | SYS | PARITY | 495/804 | PARITY | 703/804 | GET /api/prefs |

Ready time (navigation → page header, ms), median / p95:

- chromium A: median 447 · p95 735 · n=42
- chromium B: median 456 · p95 607 · n=42
- webkit A: median 488 · p95 873 · n=42
- webkit B: median 492 · p95 804 · n=42

B-only platform-seam endpoints (tabs per engine):

- chromium: GET /api/prefs: 42
- webkit: GET /api/prefs: 42

DIFF detail chromium/ostrategy: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only A [], only B ['Margin & costs — ESTIMATE']; error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []

DIFF detail chromium/discovery: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']; tables: A 0 vs B 1

DIFF detail chromium/mcxgold: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']; tables: A 2 vs B 3

DIFF detail webkit/ostrategy: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only A [], only B ['Margin & costs — ESTIMATE']; error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []

DIFF detail webkit/discovery: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']; tables: A 0 vs B 1

DIFF detail webkit/mcxgold: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']; tables: A 2 vs B 3

**Reading it.**

- **Every one of the 78 PARITY verdicts** means the same thing on both sides. Each side issued the same set
  of `/api` endpoints (method, templated path, query keys) with the same status classes. Each showed the same console
  and page errors, which here means none. Each rendered the same structure: page header, panel titles, headings,
  tables and their columns, charts, iframes and error boxes.
- **Call counts match too.** parity.py compares sets; per-endpoint call counts were checked separately from
  `parity.json`. Across all 42 tabs, A made 1,060 (B: 1,061) non-prefs `/api` calls in Chromium and 1,058 (B: 1,059) in WebKit,
  and every endpoint was called equally often on both sides. The one exception, in each engine, is the
  harness-caused ALFA flag fetch (§6).
- **B passes the audit in both engines (no failures). The only A-side audit failures are the 403s that the scratch
  server itself returns (§6).**
- **The seam set aside on every tab** is `GET /api/prefs` on B (E2). It is reported per tab in the table's last column
  and in `parity.json` → `diff.platform_seams`.
- **Timing.** Ready (navigation → page header) medians are Chromium A 447 ms vs B 456 ms, and WebKit A 488 ms vs
  B 492 ms. The boot gate (E1) does not delay the first usable page in practice, because B's prefs GET answers in
  milliseconds on loopback. First paint is *earlier* on B: §5.1 measured FCP of 100 ms vs 380 ms (Chromium) and
  105 ms vs 489 ms (WebKit) on BRF. B paints the gate at once and has no render-blocking Google Fonts stylesheet.

### 4.2 Symmetric re-probe of the DIFF tabs

`parity.py --a http://127.0.0.1:8097 --b http://127.0.0.1:8098 --tabs ostrategy,discovery,mcxgold,brief --browser both
--out reports/desktop_app/baseline_preprogram/parity_symmetric`. B' (:8098) is a byte-identical copy of the live release
`20261025-114737-0ae66db` (153 files, checksums compared), served by the same `scratch_server.py --block-mutations` as A.
`brief` is a control tab with no POST. Both sides now record the same 403 as an audit failure on the three POST tabs.
That is the harness refusing the call in the same way on both sides, and it is exactly what makes them PARITY.

A = `http://127.0.0.1:8097` (pre-program baseline (:8097, --block-mutations)) · B = `http://127.0.0.1:8098` (copy of live release 20261025-114737-0ae66db (:8098, --block-mutations)) · started 2026-10-25T12:51:43+05:30 · 198.7 s · seam exclusion True

- **chromium** (155.0.8059.85): 4/4 PARITY · DIFF: none · A audit failures: ostrategy, discovery, mcxgold · B audit failures: ostrategy, discovery, mcxgold
- **webkit** (26.4): 4/4 PARITY · DIFF: none · A audit failures: ostrategy, discovery, mcxgold · B audit failures: ostrategy, discovery, mcxgold

| tab | code | chromium verdict | chromium ready A/B ms | webkit verdict | webkit ready A/B ms | B-only seams |
|---|---|---|---|---|---|---|
| ostrategy | OSTR | PARITY | 859/536 | PARITY | 861/518 | GET /api/prefs |
| discovery | ALFA | PARITY | 461/467 | PARITY | 454/537 | GET /api/prefs |
| mcxgold | MCXG | PARITY | 505/453 | PARITY | 138/501 | GET /api/prefs |
| brief | BRF | PARITY | 462/214 | PARITY | 468/454 | GET /api/prefs |

Ready time (navigation → page header, ms), median / p95:

- chromium A: median 484 · p95 859 · n=4
- chromium B: median 460 · p95 536 · n=4
- webkit A: median 461 · p95 861 · n=4
- webkit B: median 510 · p95 537 · n=4

B-only platform-seam endpoints (tabs per engine):

- chromium: GET /api/prefs: 4
- webkit: GET /api/prefs: 4

## 5. Expected deltas: every intended program change visible in a browser

These are the differences between A (pre-program) and B (live) that the program introduced on purpose. "Seen" names
the evidence: parity (P), the supplementary probe (§5.1, D), a static comparison of the two exports (S), or source
review only (R) when a read-only browser run cannot trigger the path. File references point into the live source
(the starting copy).

| # | delta (browser mode) | origin | seen | user-visible? |
|---|---|---|---|---|
| E1 | **Boot gate.** A's prerendered `index.html` (26.9 kB) paints the terminal chrome at once: header, tape and tab strip with placeholder dashes. B's (7.4 kB) paints only the black `BootGate` ("SURYADHANA" wordmark fading in after 0.25 s; "taking longer than usual…" after 8 s). The terminal mounts once `bootstrapPlatform()` resolves: prefs hydration, ≤ 1.5 s + 250 ms, hard ceiling 1.8 s (`components/desktop/PlatformShell.tsx:42,213`, `lib/platform/index.ts:427,448`) | D4 layout.tsx + PlatformShell | S, D (chromium: gate in B's DOM from 5 ms for 86 ms; never in A; webkit: gate in B's DOM from 8 ms for 94 ms; never in A) | yes: first paint is black instead of the skeleton chrome; without JS the page shows only the gate |
| E2 | **`GET /api/prefs`** on every page load, plus a refetch on focus / visibility / `online` (`lib/prefs/sync.ts` ~765–771). Readonly mode (QA) never writes. In the owner's normal (sync) mode the page also issues `PUT /api/prefs/<key>` for synced keys and a one-time `POST /api/prefs/import`, and server values **replace** local SYNC keys before first render | D3 prefs | P (platform seam, all tabs), D | indirectly: settings now follow the server (the live store holds 1 key today: `suryadhana.watchlist`, 2-char value, `updated_at` 25 Oct 11:44:48 IST) |
| E3 | **`GET /health`** right after mount, then every 10 s while visible, confirm-after-2 s on failure, backoff 5/10/15 s (`components/desktop/health.ts:30,77`). On :3000 a fallback to `/api/health` | D4 health monitor | D (chromium: B `GET /health` ×2, A ×0; webkit: B `GET /health` ×2, A ×0) | no (one request per 10 s per tab) |
| E4 | **`GET /build-info.json`** every 60 s and on focus (≤ 1 per 15 s); only builds with a release id (`components/desktop/build.ts:35,48`) | D4 build watch | R (the 60 s poll falls outside the 15 s probe window; not seen in either run) | only when a newer release is served: the "new build" pill (E8) |
| E5 | **Fonts self-hosted.** A requests `fonts.googleapis.com` CSS and `fonts.gstatic.com` woff2. B requests `/fonts/*.woff2` from the same origin and preloads two faces (`app/layout.tsx:25`). The ALFA tab no longer `@import`s Chakra Petch from Google (P10). Same families and weights (Chakra Petch 500/600/700, JetBrains Mono 400–700), latin + latin-ext only | D4 fonts, P10 | S, D (chromium: A 5 font files via third-party fonts.googleapis.com, third-party fonts.gstatic.com; B 6 from /fonts/, 0 off-origin; webkit: A 4 font files via third-party fonts.googleapis.com, third-party fonts.gstatic.com; B 5 from /fonts/, 0 off-origin); also D4's own 24 Oct capture of the real pre-program :3000 server (`perf_baseline_3000.csv`, cold load: 5 font requests in Chromium and 4 in WebKit, **all off-origin**) vs the post-program export (`perf_export_after.csv`: 6 / 5, **none off-origin**) | barely. Greek σ (12 occurrences in 7 files of the pre-program source) now renders from a system fallback, because there is no greek subset. **₹ in the mono face now comes from Chakra Petch** (D4's U+20B9 faces; 205 occurrences in the source); before, it came from the mono stack's fallback (`'SF Mono', Menlo, monospace`), whatever each engine picked. Offline, the terminal keeps its fonts |
| E6 | **No white flash / dark UA styling.** `<html>`/`<body>` carry an inline `#05070a` background; `<meta name="theme-color">` and `color-scheme: dark` (`app/layout.tsx:16-17,29`) | D4 layout.tsx | S, D | marginal: native scrollbars and form controls follow the dark scheme |
| E7 | **Shell layout offset.** `<html data-sd-shell="browser" style="--shell-top: 0px">`, `body.terminal { padding-top: var(--shell-top) }` (`app/globals.css:275-276`), P1–P6 offsets by `var(--shell-top, 0px)`. Zero in a browser, so nothing moves, except while E8's banner shows (24 px) | D4 P1–P6 + globals.css | D (B: `data-sd-shell=browser`, `--shell-top: 0px`, body padding 0px, the same as A) | only with E8 |
| E8 | **Connection banner and "new build" pill.** A red 24 px banner while /health fails (Retry button), green "reconnected" for 2.5 s after. An amber pill when `/build-info.json` reports another release | D4 ShellNotices | R (needs ui-api down or a release swap: not done against live) | yes, by design (AC-10) |
| E9 | **ChunkLoadError recovery.** A stale lazy chunk triggers one guarded automatic reload (≤ 1/60 s per tab, waits while the server is down) instead of the error card at once. global-error.tsx is dark and keeps the error card otherwise (`app/global-error.tsx:24-33`) | D4 global-error + chunkRecovery | R | only after a release swap |
| E10 | **Toasts are visible (P11).** The 17 ToastContext utilities that Tailwind never generated before (`z-[9999]`, `right-4`, `pointer-events-auto`, `bg-*-950/90`, …) now exist. Toasts render top-right above the header with coloured backgrounds instead of transparent at the left edge under the header | D4 P11 (+ P5 offset) | S, D (CSS rules present in B only) (chromium: rules present A 0/6, B 6/6; webkit: rules present A 0/6, B 6/6) | **yes** (a latent-bug fix; also C3-logic-unchanged-10) |
| E11 | **Lazy tabs warm up and skip the skeleton (P7/P8).** 3 s after mount B loads every tab chunk in idle time, so first visits render without `TabSkeleton` and its 300 ms React fallback throttle. Same components, props and API calls | D4 P7/P8 | P (ready times), D (within 15 s of the page header B fetched 53 JS chunks vs A's 9: the idle warm-up) | yes: faster tab switches; EQS is +109 ms in Chromium (perf_baseline.md §8) |
| E12 | **Bundle split (P9).** Three key constants moved to `lib/pageKeys.ts`; same values and exports | D4 P9 | S | no |
| E13 | **Download helpers.** Browser branches are the removed code verbatim, with one documented nuance: the CSV helper (`components/terminal/index.tsx`) now appends the anchor to `<body>` before `click()`, as backtestExport always did | D3 §2f | R | no (same file name, bytes and 1 s revoke) |
| E14 | **Watchlist adopts a value synced from elsewhere** (`context/AppContext.tsx:284`, D3 1d) when the prefs engine applies a newer server value | D3 1d | R | rarely, by design (multi-window/browser + app) |
| E15 | **New localStorage bookkeeping keys**: `suryadhana.prefs.meta/hash/dirty/legacy/backup`. QA's `suryadhana.prefs.mode` is set by the harness itself | D3 prefs | D (bookkeeping only; in readonly mode nothing is uploaded. chromium: B-only keys suryadhana.prefs.dirty, suryadhana.prefs.hash, suryadhana.prefs.legacy, suryadhana.prefs.meta; webkit: B-only keys suryadhana.prefs.dirty, suryadhana.prefs.hash, suryadhana.prefs.legacy, suryadhana.prefs.meta) | no |
| E16 | **Header holiday lookup** (25 Oct fix rounds, C3-logic-unchanged-06): the page header shows HOLIDAY on NSE holidays, so every page load in browser mode sends `GET /api/market/eco-calendar` with BRIEF's own query `back=0&ahead=7` (`ui/lib/api.ts` `ECO_SHARED_QUERY`, cached and shared per page; round-1 releases sent `back=0&ahead=10`). parity.py sets it aside when it appears on one side only (`netpolicy.EXPECTED_DELTAS`, `--no-expected-deltas` to compare it) | fix rounds | P | yes on holidays only: header HOLIDAY instead of NSE OPEN |

Not present in a browser by construction (desktop only, `isDesktop()` false): TitleStrip, native window title, shell
events (Go menu, ⌘1–9), link interceptor, native notifications/downloads/external links.

### 5.1 Supplementary probe (what parity does not compare)

`tools/delta_probe.py --a http://127.0.0.1:8097 --b http://127.0.0.1:8010 --tab brief --observe 15 --browser both`
(output: `delta_probe/`). It uses a fresh readonly-prefs context per side, one browser at a time, GET only (enforced
since 25 Oct: every non-GET `/api` request is aborted in the browser and listed under `blocked_non_get`). It
records every request, including non-`/api` ones, and reads the page state 15 s after the header rendered. Both
engines tell the same story. Note that Resource Timing does not list A's cross-origin Google font loads, so the font
rows come from the network capture.

**chromium** (155.0.8059.85), tab `brief`, observed 15.0 s after the page header:

| | A (pre-program) | B (live) |
|---|---|---|
| ready (header) ms / FCP ms | 828 / 380 | 519 / 100 |
| boot gate | never in the DOM | shown at 5 ms, gone after 86 ms |
| `<html>` data-sd-shell · --shell-top · inline style | None · None · None | browser · 0px · background: rgb(5, 7, 10); color-scheme: dark; --shell-top: 0px; |
| `<body>` padding-top · inline style | 0px · None | 0px · background:#05070a;color:#d6dbe4 |
| font files fetched (network) | fonts.gstatic.com/s/chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeJI91R5_F_gUk0w.woff2<br>fonts.gstatic.com/s/chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeQI51R5_F_gUk0w.woff2<br>fonts.gstatic.com/s/chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkebIl1R5_F_gUk0w.woff2<br>fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwgknk-6nFg.woff2<br>fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwgknk-4.woff2 | /fonts/chakra-petch-v13-500-latin-ext.woff2<br>/fonts/chakra-petch-v13-500-latin.woff2<br>/fonts/chakra-petch-v13-600-latin-ext.woff2<br>/fonts/chakra-petch-v13-600-latin.woff2<br>/fonts/chakra-petch-v13-700-latin.woff2<br>/fonts/jetbrains-mono-v24-latin.woff2 |
| FontFaces loaded | Chakra Petch 500 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>Chakra Petch 600 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>Chakra Petch 700 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 400 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 400 normal [U+100-2BA, U+2BD-2C5, U+2C7-2CC, U+2CE-2]<br>JetBrains Mono 600 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 600 normal [U+100-2BA, U+2BD-2C5, U+2C7-2CC, U+2CE-2]<br>JetBrains Mono 700 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 700 normal [U+100-2BA, U+2BD-2C5, U+2C7-2CC, U+2CE-2] | Chakra Petch 500 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>Chakra Petch 500 normal [U+100-2BA, U+2BD-2C5, U+2C7-2CC, U+2CE-2]<br>Chakra Petch 600 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>Chakra Petch 600 normal [U+100-2BA, U+2BD-2C5, U+2C7-2CC, U+2CE-2]<br>Chakra Petch 700 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 400 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 400 normal [U+20B9]<br>JetBrains Mono 600 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2]<br>JetBrains Mono 600 normal [U+20B9]<br>JetBrains Mono 700 normal [U+0-FF, U+131, U+152-153, U+2BB-2BC, U+2] |
| ToastContext-only CSS rules present | none | .z-\[9999\], .right-4, .pointer-events-auto, .translate-x-4, .transition-opacity, .break-words |
| localStorage keys after the visit | suryadhana.prefs.mode, suryadhana.watchlist | suryadhana.prefs.dirty, suryadhana.prefs.hash, suryadhana.prefs.legacy, suryadhana.prefs.meta, suryadhana.prefs.mode, suryadhana.watchlist |
| /api calls (compared by parity.py) | 56 | 56 |
| other requests | GET / ×1 (200)<br>GET /icon.svg ×1 (200)<br>third-party fonts.googleapis.com ×1 (200)<br>third-party fonts.gstatic.com ×5 (200)<br>static: {'GET /_next/static/*.css': 1, 'GET /_next/static/*.js': 9} | GET / ×1 (200)<br>GET /api/prefs ×1 (200)<br>GET /fonts/chakra-petch-v13-500-latin-ext.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-500-latin.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-600-latin-ext.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-600-latin.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-700-latin.woff2 ×1 (200)<br>GET /fonts/jetbrains-mono-v24-latin.woff2 ×1 (200)<br>GET /health ×2 (200)<br>GET /icon.svg ×1 (200)<br>static: {'GET /_next/static/*.css': 1, 'GET /_next/static/*.js': 53} |

**webkit** (26.4), tab `brief`, observed 15.0 s after the page header:

| | A (pre-program) | B (live) |
|---|---|---|
| ready (header) ms / FCP ms | 875 / 489 | 549 / 105 |
| boot gate | never in the DOM | shown at 8 ms, gone after 94 ms |
| `<html>` data-sd-shell · --shell-top · inline style | None · None · None | browser · 0px · background: rgb(5, 7, 10); color-scheme: dark; --shell-top: 0px; |
| `<body>` padding-top · inline style | 0px · None | 0px · background:#05070a;color:#d6dbe4 |
| font files fetched (network) | fonts.gstatic.com/s/chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeJI91R5_F_gUk0w.woff2<br>fonts.gstatic.com/s/chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeQI51R5_F_gUk0w.woff2<br>fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwgknk-6nFg.woff2<br>fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwgknk-4.woff2 | /fonts/chakra-petch-v13-500-latin-ext.woff2<br>/fonts/chakra-petch-v13-600-latin-ext.woff2<br>/fonts/chakra-petch-v13-600-latin.woff2<br>/fonts/chakra-petch-v13-700-latin.woff2<br>/fonts/jetbrains-mono-v24-latin.woff2 |
| FontFaces loaded | Chakra Petch 600 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>Chakra Petch 700 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 400 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 400 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2]<br>JetBrains Mono 500 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2]<br>JetBrains Mono 600 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 600 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2]<br>JetBrains Mono 700 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 700 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2] | Chakra Petch 500 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2]<br>Chakra Petch 600 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>Chakra Petch 600 normal [U+100-2ba, U+2bd-2c5, U+2c7-2cc, U+2ce-2]<br>Chakra Petch 700 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 400 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 400 normal [U+20b9]<br>JetBrains Mono 500 normal [U+20b9]<br>JetBrains Mono 600 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2]<br>JetBrains Mono 600 normal [U+20b9]<br>JetBrains Mono 700 normal [U+0-ff, U+131, U+152-153, U+2bb-2bc, U+2] |
| ToastContext-only CSS rules present | none | .z-\[9999\], .right-4, .pointer-events-auto, .translate-x-4, .transition-opacity, .break-words |
| localStorage keys after the visit | suryadhana.prefs.mode, suryadhana.watchlist | suryadhana.prefs.dirty, suryadhana.prefs.hash, suryadhana.prefs.legacy, suryadhana.prefs.meta, suryadhana.prefs.mode, suryadhana.watchlist |
| /api calls (compared by parity.py) | 56 | 56 |
| other requests | GET / ×1 (200)<br>third-party fonts.googleapis.com ×1 (200)<br>third-party fonts.gstatic.com ×4 (200)<br>static: {'GET /_next/static/*.css': 1, 'GET /_next/static/*.js': 9} | GET / ×1 (200)<br>GET /api/prefs ×1 (200)<br>GET /fonts/chakra-petch-v13-500-latin-ext.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-600-latin-ext.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-600-latin.woff2 ×1 (200)<br>GET /fonts/chakra-petch-v13-700-latin.woff2 ×1 (200)<br>GET /fonts/jetbrains-mono-v24-latin.woff2 ×1 (200)<br>GET /health ×2 (200)<br>static: {'GET /_next/static/*.css': 1, 'GET /_next/static/*.js': 53} |


## 6. Unexpected deltas and findings

Every DIFF reported by the main run has the same root cause, and it is **in the harness, not in the program**:

| tab (both engines) | DIFF reported by parity.py | root cause |
|---|---|---|
| **OSTR** `ostrategy` | `POST /api/options/strategy/analyze` A 4xx / B 2xx · A console "403 (Forbidden)" · panel "Margin & costs — ESTIMATE" only on B · error box "▲ blocked by desktop-qa scratch server (--block-mutations)" only on A | A's on-load analyze POST refused by the scratch server (A failure: `failed_request: POST …/api/options/strategy/analyze → HTTP 403`) |
| **ALFA** `discovery` | only B calls `GET /api/market/surveillance?all_flagged,symbols` · `POST /api/alpha/scan` A 4xx / B 2xx · A console 403 · result table (`TICKER · SIGNAL DATE · LTP / CLOSE · CHG% · NET …`) only on B | A's initial scan POST refused → no rows → no `TickerLink` → no flag fetch |
| **MCXG** `mcxgold` | `POST /api/mcx/ticket` A 4xx / B 2xx · A console 403 · cost table (`Leg · Brokerage · Exch … · Total`) only on B (2 vs 3 tables) | A's on-load paper-ticket POST refused by the scratch server |

Three pages send a **POST to a pure-computation endpoint on load**, in both the pre-program and the live UI
(identical call sites in A and B). These are exactly the three that `reports/desktop_app/qa_harness.md:205-207` lists
as "Pages that POST on load (compute-only … nothing recorded)":

- OSTR: `components/StrategyBuilder.tsx:196`, `POST /api/options/strategy/analyze` (Black-76 payoff, "PRICES strategies
  only; never places orders").
- ALFA: `components/AlphaDiscoveryDesk.tsx:250-256` → `runAlphaScan` (`lib/api.ts:302`), `POST /api/alpha/scan`.
- MCXG: `components/McxGoldDesk.tsx:197`, `POST /api/mcx/ticket` ("PAPER pricing only … Records nothing").

Side A runs behind `scratch_server.py --block-mutations` (required by this round's rules), which answers every
non-GET `/api` call with 403 before forwarding. Side B is live :8010, which answers 2xx. On OSTR and MCXG this shows up
as a status-class difference on the POST itself. On ALFA it also changes the request set. With the scan refused, A has
no result rows, so no `TickerLink` mounts and the shared flag store (`components/terminal/index.tsx:556-569`,
`useFlagged()`) never issues `GET /api/market/surveillance?all_flagged,symbols`. B renders rows and does issue it.

**Proof (§4.2, symmetric re-probe):** the DIFF tabs are re-run with B' = a byte-identical copy of the live release
`20261025-114737-0ae66db` (153 files, checksums compared), served by the same `scratch_server.py --block-mutations`
on :8098. Both sides now refuse the POST in the same way, and every re-probed tab is PARITY in both engines.

No other difference was found: no request-set, status-class, console-error, page-error or structural-fingerprint
difference on any of the other tabs, in either engine.

### 6.1 A documentation defect in D3.md (no code impact)

D3.md §2f shows the CSV byte-order mark as a literal U+FEFF character (`'<U+FEFF>'`), while the source and the code D3
executed contain the six-character JS escape `\ufeff`. The block is therefore not an exact old/new pair, and an applier
working from D3.md would not match §2f. Every other D3.md §2 block equals the executed pair once the final newline is
stripped (markdown cannot show it). `reconstruct.py` uses the executed pairs and checks each against D3.md, with this
one normalisation. The PM corrected D3.md on 25 Oct (§2f now shows the escape); the normalisation accepts either form,
and both parse to the same pinned record digest (`RECORDS_SHA256` in `tools/reconstruct.py`).

### 6.2 Corrections to the brief's assumptions

- **`ui/app/global-error.tsx` existed before the program.** D4's first command printed it (a 62-line "Client-side
  Exception" boundary, `records/originals/app/global-error.tsx`), and D4 rewrote it at 05:58:41 UTC. The baseline
  restores it rather than deleting it.
- **The pre-program `ui/next.config.js` is not git HEAD.** HEAD (14 Jun) lacks the
  `distDir: process.env.NEXT_DIST_DIR || '.next'` line, which was added before the program and which `UI_MODE=prod`
  relies on. The pre-program file is D1's first `cat` (`records/originals/next.config.js`), and D1's
  "resolved config unchanged" claim holds against that file (§2.3), not against HEAD.
- The `globals.css` D4 section is append-only as claimed: lines 1–203 are byte-identical to the original, and lines
  204–366 are D4's section.

## 7. Files

| path | what |
|---|---|
| `README.md` | this report |
| `baseline_src.tar.gz`, `MANIFEST.sha256` | the reconstructed pre-program ui/ tree and its per-file checksums |
| `build_baseline.sh`, `build/` | rebuild script and frozen builder (`SHA256SUMS` checked on every run) |
| `reconstruct_report.json`, `diff_vs_snapshot.patch` | the reconstruction's steps, checks and the full diff against the starting copy |
| `records/` | evidence: `originals/` (printed before the program's writes), `d3_callsites.json` (D3's executed pairs), `inventory_0539Z.txt` (D4's ls), `program_writes.tsv` and `bash_write_scan.tsv` (every write), `crosscheck_reads.json`, `program_final/` (post-program copies of the rewritten files, used by the tests), `snapshot_20261025T115802IST.sha256` (the starting copy), `provenance.json` |
| `tools/extract_records.py` · `reconstruct.py` · `test_reconstruct.py` | record extraction from the transcripts, reconstruction + proofs, regression tests (10) |
| `tools/crosscheck_reads.py` · `scan_bash_writes.py` | independent transcript cross-checks (§2.3) |
| `tools/delta_probe.py` · `summarize_parity.py` | the supplementary A/B probe (§5.1) and the parity summariser |
| `parity/` | parity.py output: `parity.json`, `parity.md` (main run) |
| `parity_symmetric/` | symmetric re-probe of the DIFF tabs (§4.2) |
| `delta_probe/` | supplementary probe output (§5.1) |

Regression check later: `build_baseline.sh --out <dir>`, serve it with `scratch_server.py --block-mutations`, then run
parity.py against the candidate. Serve the candidate the same way: copy its release out of `ui/dist/releases/` into a
scratch dir and serve that with `--block-mutations` too. Then both sides refuse the three on-load compute POSTs alike,
and only the expected deltas (§5) remain. Against live :8010 directly, OSTR, ALFA and MCXG also show the harness
DIFF described in §6.
