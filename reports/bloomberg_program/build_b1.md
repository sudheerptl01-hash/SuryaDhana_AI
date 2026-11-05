# BUILD B1 — Reliability / Ops (final report)

Builder: B1 · 14 Oct 2026 · branch `feature/backtest-lab-institutional` (no commits made, per rules)
Scope executed in must-land order per directive; amendments **A4, A7, minors 9/10/12** honoured.

## Verdict

All 5 units + the sanctioned alpha_lab hook **shipped and green**: 772 tests pass
(scripts/tests **130**, tests **281**, ui-api **342**, execution-service **7**, alpha_lab **12**),
compileall clean on every touched file. No new pip installs, no Telegram sends, no service
restarts, no git operations.

---

## 1 · `.env.example` name-sync (F1.1) ✅

- `.env.example` — rewritten: every live `.env` key documented, grouped, **placeholders only**;
  LOGIN-CRITICAL block marked (ICICI_* incl. `ICICI_TOTP_SECRET`, `ICICI_AUTO_LOGIN`); commented
  `SURYA_SNAPSHOT_PATH` documents the A7 injection contract.
- `scripts/tests/test_env_example.py` — 3 tests:
  1. **name-diff proof**: every key in live `.env` exists in `.env.example` (reads live only
     inside the test, never prints values),
  2. login-critical keys present + `LOGIN-CRITICAL` marker,
  3. **no live secret value leaked** into the example (hard check on SECRET_KEYS; benign
     overlaps allowlisted, e.g. `UI_MODE=prod`).

## 2 · Shared evening snapshot (F2.3, A7, minor 9) ✅

- `scripts/build_evening_snapshot.py` (167 LOC) — APFS clone `cp -c` → `copy2` fallback
  (`_fast_copy` :41), torn-copy-safe 2-attempt build comparing source `(mtime_ns,size)`
  before/after (`build` :84), read-only verify `COUNT(nse_bhavcopy)` (`_verify` :49), WAL copied
  to the **same stem** `evening-<ts>.duckdb.wal` (minor 9), pointer
  `data/.evening_snapshot.json` {path, created_at, db_mtime_ns, db_size, rows}, `prune` keep-2
  (:72), `cleanup_orphan_tmp` >1h (:58), `current(max_age_h, allow_stale)` (:129) — strict mode
  requires the source-db mtime to still match (same-evening consumers); `allow_stale=True` for
  the 02:15 backup. CLI: `--current/--allow-stale`.
- `scripts/tests/test_shared_snapshot.py` — 4 tests: build/pointer/WAL-stem; prune+staleness;
  orphan cleanup old-only; torn-copy retry.
- **Controller wiring** (`scripts/master_controller.py`): job `shared_snapshot_build` :1278,
  registered 19:20 IST mon-fri :1821 (fail → `_alerts.warning`, jobs fall back to private
  copies); **A7** env injection `_evening_snapshot_env()` :1266 — reads the pointer **at
  job-spawn time**, strict `current(max_age_h=2)`, returns `{}` on any exception (no module
  state, can never break a spawn); merged into the 19:45 news env :1335 and 19:50 shadow env
  :1357; cron header updated :14.

## 3 · Nightly backup + restore runbook (F1.2/F1.3, minor 10) ✅

- `scripts/db_backup.py` (134 LOC) — source = evening snapshot via `current(30h,
  allow_stale=True)`, else `_consistent_private_copy` :45; verify **before** compress; zstd via
  try-import (`_compress_if_possible` :60 — falls back to uncompressed, **no new deps**);
  `meta.json` per backup {rows, sha256, src, src_mtime_ns, compressed, created_at, file, bytes};
  `rotate` :75 keeps strictly last-7-days dailies (`d > today−7d`) + last 4 Sundays (overlap
  allowed), metas follow. Dest `data/backups/duckdb/`.
- Controller: `db_backup_daily` :1301, registered 02:15 IST daily :1829, fail → `_alerts.critical`.
- `scripts/tests/test_db_backup.py` — 4 tests: snapshot-sourced + meta; private-copy fallback;
  zstd-absent fallback (import monkeypatch); rotation 7 dailies + 3 beyond-window Sundays.
- `docs/RUNBOOK_RESTORE.md` (83 lines) — blank-Mac → working terminal: env rebuild, `.env`
  key-by-key table, cp/zstd restore + row-count verify, no-backup NSE rebuild path, start +
  `ui_audit` verify, job re-arm list; **minor 10** freshness window stated: *"backups lag ≤1
  trading day of positions/results data"* (02:15 backup predates nothing — it uses the 19:20
  snapshot, which precedes the 20:30/20:45 ingests).

## 4 · CI (F1.4, A4) ✅

- `requirements-ci.txt` (77 lines) — identical pins to requirements.txt **minus**
  `xgboost/lightgbm/stable-baselines3` (kept as `# [ci-excluded]` lines; rule documented in the
  header). Plus a `[ci-added]` block — see **drift finding** below — and `pyyaml==6.0.3`
  (meta-test imports yaml; was only transitive via uvicorn[standard]).
- `.github/workflows/ci.yml` (50 lines) — `python` job (3.13, pip cache, the **5 suites** with
  correct cwd/paths, `scripts/check_event_loop.py` guarded by `if [ -f … ]` so CI is green
  regardless of B2's landing order) + `ui` job (node 20, `npm ci`, `tsc --noEmit`).
- `scripts/tests/test_ci_workflow.py` — 2 meta-tests: yml parses + lists all 5 suites + tsc +
  scanner + requirements-ci; exclusion set is exactly the heavy trio, import-time deps present,
  carried pins byte-identical to requirements.txt. **2 passed.**
- Note: CI has not executed on GitHub (no commits allowed); it is validated by the meta-test +
  the same suites passing locally. First real run happens on the PM's merge.

## 5 · Dead routes (F1.5/F1.6) — my five routers only ✅

Grep-proof protocol: exact mounted path **and** loose path-tail searched across
`ui/ services/ scripts/ tests/ shared/ alpha_lab/ docs/` (ts/tsx/js/py/sh/md), excluding the
defining router. ui-api suite then re-run: **342 passed**.

| Route | Proof | Action |
|---|---|---|
| `GET /api/data/db/screener` (data_proxy) | 0 hits. (Loose `db/screener` hits are the **data-service** route :8001 called by stocks.py — B3/B2 files, different endpoint, untouched) | deleted |
| `GET /api/ml/runs` (ml_workspace :630) | 0 hits anywhere | deleted |
| `GET /api/ml/health` (ml_workspace) | 0 hits (ui-api `/health` is the service health route, untouched) | deleted |
| `GET /api/monitor/embed` (monitor :202) | 0 code hits; 1 mention in `docs/legacy/api_architecture_map.md` (historical doc, B5's domain) | deleted |
| `POST /api/execution/order/scheduled` (execution :192) | 0 code hits; 1 mention in `docs/legacy/SOTA_GAP_REMEDIATION_SUMMARY.md` (historical). `ScheduledOrderRequest` model had 0 other users → deleted with it. **`ExecutionEngine.execute_scheduled` kept** — engine + its tests untouched (7 passed) | deleted |
| `POST /api/positions/refresh-session` (positions :675) | 0 hits; `_invalidate_breeze_state` retains 4 other callers | deleted |
| `POST /api/data/fetch/icici/daily` (data_proxy :118) | F1.6: **kept**, marked `deprecated=True` + docstring (remove after 2026-11) | deprecated |

Each deletion site carries a one-line tombstone comment naming F1.5 and the replacement.

## 6 · Sanctioned alpha_lab hook (the ONE permitted edit) ✅

- `alpha_lab/backtest/data_access.py:25` — `_shared_snapshot()`: `SURYA_SNAPSHOT_PATH` env wins
  (exists-check only — controller injects pre-verified fresh); else pointer file if snapshot
  <24h old; **never raises** → `None` → today's private-copy path. `load()` :49 connects
  `read_only=True` to the shared snapshot and skips the 4.4GB copy; private-copy branch
  byte-identical to before. Probed: env-hit ✓, env-missing-file → None ✓, no-env/no-pointer →
  None ✓. **alpha_lab: 12 passed.**

---

## Findings for the PM

1. **requirements.txt drift (not my file — did not edit):** four packages are imported by
   test-reachable code yet pinned nowhere: `apscheduler 3.10.4`, `psutil 6.0.0`
   (master_controller), `playwright 1.60.0` (shared/icici_login), `scipy 1.17.1` (evidence
   study). Pinned in requirements-ci.txt `[ci-added]`; requirements.txt needs the same sync.
   Also `scikit-learn` is pinned 1.5.2 but the local env runs 1.8.0 — CI will exercise 1.5.2.
2. **B2 coverage check:** `scripts/news_scan_performance.py` honouring the injected
   `SURYA_SNAPSHOT_PATH` internally is **B2's** per the directive — confirm B2 shipped it
   (my side of A7 — the controller injection — is done for both 19:45 and 19:50 spawns).
3. **Jobs go live on the next master-controller restart** (PM-only action). Until then the
   pointer file does not exist; backup falls back to a private consistent copy and the
   alpha_lab hook returns None — both paths tested.
4. Legacy docs still mention 2 deleted routes (`docs/legacy/*.md`) — historical records, B5's
   domain; left alone.

## Patches for other builders
None required.

## NOT done (honest)
- requirements.txt sync (ownership — flagged above, one-minute fix for the PM).
- CI run on GitHub Actions itself (needs a commit; forbidden for builders).
- A live 19:20/02:15 firing (needs controller restart; forbidden). Logic is covered by the 11
  new unit tests + registration asserted present at master_controller.py:1821/:1829.

## Test evidence (final sweep, this session)
```
scripts/tests          130 passed  in 1.66s   (includes 13 new B1 tests)
tests/                 281 passed  in 22.44s
services/ui-api/tests  342 passed  in 3.21s   (after route deletions)
services/execution-…   7 passed    in 0.03s
alpha_lab/tests        12 passed   in 0.24s   (after data_access hook)
compileall             OK (snapshot, backup, controller, data_access, all 5 routers)
```
