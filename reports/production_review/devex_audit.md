# DevEx (operator) audit — /devex-review, live

14 Oct 2026, ~21:30 IST · agent DEVEX · method: TESTED = ran/hit it on this machine, INFERRED = read from files.
Scope honestly adapted: single-operator internal product → "developer" = the owner operating this Mac; community
dimension re-scored as bus-factor/handoff. GET-only; nothing restarted; no Telegram sent.

## Scorecard

| Dimension | Score | Evidence | Method |
|---|---|---|---|
| 1 Getting started (fresh machine) | **4/10** | GETTING_STARTED.md stale; .env.example missing login keys; DB restore undocumented | TESTED+INFERRED |
| 2 CLI/API ergonomics | **6/10** | start-local verbs incl. `status` with latency; thin --help blurbs; run_today has no argparse | TESTED |
| 3 Error messages | **6/10** | 4 live samples graded below | TESTED |
| 4 Documentation | **6/10** | IMPROVEMENT_LOG excellent; 2/3 findability; stale guides + root clutter | TESTED |
| 5 Upgrade path | **5/10** | 39/39 pins ✓ but shared jupyter_env hazard; node unpinned | INFERRED |
| 6 Dev environment | **4/10** | 5 test suites, 1 documented; **no CI anywhere** | TESTED |
| 7 Bus factor / handoff (replaces Community) | **3/10** | .env is the only secret store; 4.4 GB DuckDB git-ignored, no backup runbook | INFERRED |
| 8 DX measurement | **6/10** | job failures → Telegram + /status + System page; no error aggregation | TESTED |
| **TTHW** | warm ≈ 2 min · **fresh machine: blocked** (Red Flag tier) | see §1 | INFERRED |
| **Overall DX** | **5/10** | smooth daily for its one operator; fragile to machine loss; docs drifting | — |

Boomerang: `NO_PRIOR_PLAN_REVIEW` — no /plan-devex-review baseline exists; this is the first DX measurement.

## 1. Getting started — the disk-wipe test fails
Steps as documented vs reality:

| Step | Doc says | Reality | Friction |
|---|---|---|---|
| Clone + env | GETTING_STARTED: copy .env.example | `.env.example` (36 keys) is missing **ICICI_CLIENT_ID, ICICI_PASSWORD, ICICI_MOBILE** (verified by name-diff vs live .env) and has no ICICI_TOTP_SECRET/COST_PROFILE/DESK_*/UI_MODE | **HIGH — login can never work from the example** |
| Data | ".env … NSE data auto-downloaded or pre-loaded" | `data/market.duckdb` is **4.4 GB, git-ignored, no backup/restore section anywhere** (grep: zero hits in GETTING_STARTED) | **HIGH — 16 yrs of ingested panel unrecoverable from docs** |
| Local stack | "starts only UI API + frontend" | start-local.sh actually runs the full 7-service stack (its own header says so) | MED — doc contradicts script |
| Browser login | not mentioned | daily_session_refresh needs Chrome + Playwright (headless login) — undocumented prerequisite | MED |
| Warm start | — | `./start-local.sh` with health waits ≈ 2 min; `status` verb is genuinely good | LOW |

## 2. CLI ergonomics
- `start-local.sh` verbs (start/stop/restart/status/logs + per-service + `UI_MODE=prod`) — the best part of the surface. TESTED.
- argparse `--help` exists on the main scripts but descriptions are mostly empty strings (`--out OUT` tells nothing). `alpha_lab/run_today.py` has **no argparse** — invoking it with `--help` would just run it (15 s panel load).
- **PYTHONPATH paper-cut is real**: 60 files self-insert sys.path; invocation conventions (`PYTHONPATH=.` vs `PYTHONPATH=alpha_lab`) are documented only inside two IMPROVEMENT_LOG lines, nowhere canonical.
- Telegram surface: 21 commands with `/help` and menu registration — strong operator UX. TESTED (import-only).

## 3. Error messages (live samples, three-tier: problem/cause/fix)
| Sample | Verdict |
|---|---|
| `GET /api/stocks/ZZZNOTREAL` → `{"detail":"Not Found"}` | problem only — no cause, no fix, no "try GO ticker search" (1/3) |
| 500-char `names` param → FastAPI field+constraint+input echo | problem+cause (2/3), default but decent |
| `research/doc?id=../../etc/passwd` → `Unknown report` | correct hard rejection; traversal safely handled (TESTED) |
| data-service down path → `503 data-service unreachable: {exc}` (markets.py ×4) | problem+cause (2/3) |
| ICICI expired (positions.py) → names the 08:00 job and the Broker-tab fix | the model answer (3/3) — make the others look like this |

## 4. Documentation
- **IMPROVEMENT_LOG.md is the de-facto system and it works**: changelog + runbook + "needs you" list in one; this is the pattern to formalise, not replace.
- Findability trial (docs-only): "re-login ICICI" ~1 min ✓ · "why is a stock flagged" ~30 s ✓ · "run the paper shadow manually" ✗ — the command exists only in `alpha_lab/` (outside docs/), zero grep hits in docs/ or CLAUDE.md.
- Staleness: CLAUDE.md still carries the 16-week roadmap with Phase 1 "⏳" while the repo runs a live terminal, a Desk, and a forward shadow; ~8 of 19 docs are earlier-era guides (Larry-Williams/pipeline) with no "historic" banner; **~50 loose .md/.txt/.csv legacy files sit in the repo root** (BACKTEST_*, DASHBOARD_*, result CSVs), burying GETTING_STARTED.md.
- No root README.md at all.

## 5. Upgrade path
- requirements.txt: 39/39 exact pins ✓ with section comments ✓.
- But installs land in the **shared** `/Users/sudheer/Desktop/jupyter_env` (project memory records it breaking other projects once); no per-project venv, no pip freeze drift check, no `engines` pin for node (INFERRED — package.json not checked for engines).
- Changelog quality: IMPROVEMENT_LOG — excellent, dated, honest about corrections.

## 6. Dev environment
- Reality: **five** pytest suites (tests/, scripts/tests, services/ui-api/tests, services/execution-service/tests, alpha_lab/tests) with differing cwd conventions; CLAUDE.md documents **one** (`pytest tests/ -v --cov`).
- **CI: none.** No .github/ anywhere; infra/ holds compose + k8s only. Every regression gate is manual.
- mypy command documented and runnable; ruff/black claimed by global standards but no config files in repo (INFERRED).

## 7. Bus factor (handoff story)
Order in which a handoff breaks: 1) `.env` — sole copy of every secret (keychain: zero entries; verified); 2) `data/market.duckdb` 4.4 GB no backup path; 3) assistant memory lives in `~/.claude/projects/...` (machine-local, not in repo); 4) LaunchAgent autostart not installed (owner's standing choice — documented nowhere a newcomer would look); 5) jupyter_env is outside the repo entirely.

## 8. DX measurement
Exists and is used: job failures alert to Telegram, `/status` + System page expose scheduler/jobs/latency, statusline usage meters. Missing: any aggregated error-rate view (silent repeated 502s only visible by reading logs).

## Top 10 fixes (operator-pain ÷ effort)
1. **Sync `.env.example` to every key the code reads** (start from shared/config.py + grep os.environ) with one-line comments; add the three login keys. ~30 min. — unblocks the single worst restore trap.
2. **docs/OPERATIONS.md — the disk-wipe runbook**: secrets inventory, DB backup/restore, Chrome/Playwright, node, start-local, verify checklist (ui_audit + /status). ~1–2 h.
3. **Nightly DuckDB backup job** (snapshot copy → data/backups/ + optional external target) + documented restore one-liner. ~1 h.
4. **Root README.md (10 lines) + fix GETTING_STARTED's wrong local-stack description.** ~45 min.
5. **Archive the ~50 root legacy files** into docs/archive/ (keep git history). ~30 min.
6. **scripts/run_all_tests.sh** running all five suites with correct paths; reference it in CLAUDE.md. ~30 min.
7. **CI**: if the repo has a remote, a single GitHub Action = run_all_tests + `tsc --noEmit`; else a local pre-push hook. ~1 h.
8. **CLAUDE.md hygiene**: retire the Phase-1 roadmap table; add the PYTHONPATH invocation map; list all five test suites. ~30 min.
9. **argparse + real help text** on operator scripts; give run_today.py `--help`. ~45 min.
10. **Error-message pass**: bring the 5 most-hit operator endpoints up to the ICICI-expired standard (problem+cause+fix). ~1–2 h.

One pattern worth keeping on purpose: the IMPROVEMENT_LOG-as-operations-journal. Formalise it (fix #2 links into it) rather than adding a second documentation system.
