# Four decisions only you can make — one command each

Eighteen rating rounds took the terminal from 6.5 to 8.9. Every buildable item is closed. What remains is
these four, and three of them are the only thing standing between five areas and 9.0. Each is one command.

Nothing here is urgent for **Monday's open** — the terminal is ready and nothing below is on the trading
path. They matter for what the numbers on three pages *mean*.

---

## 1. The risk-free rate (O-T5) — caps Research at 8.8

**What it affects:** every implied-volatility number on the terminal. `b76-pcp-v1` (Black-76 on the
put-call-parity forward) discounts with `rate_curve`, and that table holds exactly one row: **6.5 %, dated
2019-10-01**. Seven years stale. The DATA page renders it honestly — "dated constant in force since
2019-10-01", not an age — so nothing is hidden, but every IV, every IV-rank and every vol-cone band on DERV,
OMON and OSTR is computed with it.

**What to decide:** which rate, and today's value. The conventional choice for Indian index options is the
**91-day T-bill yield** (RBI publishes it weekly; it has been ~6.4–6.6 % through 2026, so the number may
barely move — but a dated row that says so is worth more than an undated one that happens to be close).

**The command** — the schema is already dated, so this is an INSERT and nothing is rewritten:

```bash
cd ~/MahaKubera_108/SuryaDhana_AI
P=/Users/sudheer/Desktop/jupyter_env/bin/python
# stop ui-api first: it holds a read lock on market.duckdb (RUNBOOK 'After an outage')
./start-local.sh stop ui-api
$P - <<'EOF'
import duckdb
from datetime import date, datetime, timezone
RATE = 6.50          # <-- today's 91-day T-bill yield, in percent
con = duckdb.connect("data/market.duckdb")
con.execute("INSERT INTO rate_curve (date, tenor, rate, source, first_seen_at) VALUES (?, ?, ?, ?, ?)",
            [date.today(), "91d", RATE, "RBI 91-day T-bill (owner, O-T5)", datetime.now(timezone.utc)])
print(con.execute("SELECT * FROM rate_curve ORDER BY date DESC LIMIT 3").fetchall())
con.close()
EOF
./start-local.sh start ui-api
```

Then re-derive the stored IVs so history uses it: `curl -X POST ':8001/jobs/iv-eod?job=iv_repair'`
(run it outside the freeze windows — not 07:45–09:20 or 18:30–21:15).

---

## 2. `PAPER_FO_CAPITAL` — caps Options at 8.7

**What it affects:** RSK › F&O. Verified live: `/api/risk/fo` returns
`capital.source = "default ₹1,000,000 (PAPER_FO_CAPITAL unset — the owner sets it)"`. Every SPAN-utilisation
percentage and every VaR-as-%-of-capital on that page is arithmetic on a placeholder. The Greeks and the
rupee VaR are real; only the percentages are relative to a number you have not set.

**The command** — the capital base for the PAPER F&O book, in rupees:

```bash
cd ~/MahaKubera_108/SuryaDhana_AI
echo 'PAPER_FO_CAPITAL=1500000' >> .env     # <-- your number
./start-local.sh restart ui-api
curl -s :8010/api/risk/fo | python3 -c 'import json,sys; print(json.load(sys.stdin)["capital"])'
```

---

## 3. `OFFSITE_BACKUP_DIR` — caps Platform at 8.9

**What it affects:** durability. `scripts/db_backup.py --offsite` works and is tested; the 02:15 job passes
`--offsite` automatically **whenever the variable is set** (it re-reads `.env` at run time, so no restart is
needed). Unset, `db_backup.py` reports `{"skipped": "unset"}` and every copy stays on this Mac — which is
one disk failure from losing a 4.4 GB survivorship-free panel built since 2010.

**The command** — any path that is not this machine's internal disk (an external drive, a mounted NAS, an
iCloud/Dropbox folder):

```bash
cd ~/MahaKubera_108/SuryaDhana_AI
echo 'OFFSITE_BACKUP_DIR=/Volumes/Backup/suryadhana' >> .env   # <-- your path
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/db_backup.py --offsite   # verify once by hand
```

It rotates 7 daily + 4 Sundays and verifies the DuckDB copy by sha256. A failed off-site copy exits 1 *after*
the local backup completes, so SYS shows the error and Telegram says why — it never costs you the local copy.

---

## 4. `GO IMPORT` — your watchlist and pins

**What it affects:** WTCH and GPLN focus lists are empty. The old terminal's watchlist lives in your
**browser's** localStorage, which no agent can reach — it has to be you, in the browser, once.

**The command:** open the terminal, type `GO IMPORT` in the command bar, accept the prompt. The settings
banner at the bottom-right of BRIEF offers the same thing (`IMPORT…`).

---

## What these do not block

Monday's open needs none of them. The broker chip, the pre-open alarm, the budget panel, the Crashes column,
the data-health surface and the 44 pages are all live and verified on release `20261114-155227-59c3004`.
Your Monday checklist is `~/.suryadhana_pm_scratch/final_round_20261113/f-probe/MONDAY_SMOKE.md` — 54 checks
in the order the day happens, from 08:05 to the 23:40 settlement band.
