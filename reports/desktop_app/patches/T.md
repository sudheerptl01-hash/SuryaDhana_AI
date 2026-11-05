# Patch blocks from T (QA harness), 24 Oct 2026

T owns no shared files. These two doc edits are optional. They make the PM-owned docs match the extended
`scripts/ui_audit.py`: its default is still the original 15 tabs, and `--tabs all --browser both` is the
42-page gate. Apply each with a uniqueness-asserted replace (each old text occurs exactly once).

## 1. `CLAUDE.md` ("How to run things")

Old (exact, unique):
```
# Terminal page audit (42 pages, console + API errors)
$P scripts/ui_audit.py
```
New:
```
# Terminal page audit: default = the original 15 tabs; the 42-page Chromium + WebKit gate (exit 0 = all PASS)
$P scripts/ui_audit.py --tabs all --browser both --out reports/ui_audit/after
# Desktop QA (parity, streams, contract, app E2E): reports/desktop_app/qa_harness.md
```

## 2. `docs/RUNBOOK_RESTORE.md` (post-restore sanity block)

Old (exact, unique):
```
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py          # expect 15/15 ok
```
New:
```
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py          # expect "[chromium] 15/15 PASS", exit 0
```
