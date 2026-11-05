# SuryaDhana — Getting Started (operator guide)

Accurate as of 14 Oct 2026. The canonical map (architecture, trading rules, test commands) is `CLAUDE.md`;
the daily journal is `docs/IMPROVEMENT_LOG.md`.

## Quick start (warm machine — the normal case)

```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
./start-local.sh start      # the full local stack: data-service :8001, ui-api :8010,
                            # master-controller :8008 (jobs + Telegram bot), frontend :3000
./start-local.sh status     # per-service health with latency
./start-local.sh stop       # stop everything (or: stop <service>)
UI_MODE=prod ./start-local.sh restart frontend   # optimised UI build (dist dir ui/.next-prod)
```

Open **http://localhost:3000**. Press `/` for the GO command bar (tickers + function codes), `?` for help.

> `start-local.sh` runs the **whole stack**, not just the UI — an older version of this guide said otherwise.
> Logs land in `.logs/`. **Restart freeze windows (IST):** avoid restarting data-service or master-controller
> 07:45–09:20 and 18:30–21:15 (ICICI login, pre-open and EOD jobs).

## Prerequisites (fresh machine)

1. **Python**: the shared env at `/Users/sudheer/Desktop/jupyter_env/bin/python` (never system Python;
   `pip install -r requirements.txt` into that env — it is shared with other projects, install only pins).
2. **Node 20+ / npm**, then `cd ui && npm install`.
3. **Google Chrome** — the ICICI login automation drives real Chrome via Playwright.
4. **`.env`** — `cp .env.example .env`, then fill the keys (names below). Never commit it.
5. **Market database** — `data/market.duckdb` (≈4.4 GB) is git-ignored. Restore it from backup before first
   start: see `docs/RUNBOOK_RESTORE.md`. Without it the terminal starts but shows empty data.

### `.env` keys that matter

| Key | Purpose |
|---|---|
| `ICICI_API_KEY` / `ICICI_API_SECRET` | Breeze app credentials (breezeapi from ICICI Direct) |
| `ICICI_SESSION_TOKEN` | **Daily** session token — refreshed automatically (below) |
| `ICICI_CLIENT_ID` / `ICICI_PASSWORD` / `ICICI_MOBILE` | login automation (user id / PIN, OTP phone) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | the phone bot + alerts |
| `COST_PROFILE` | broker cost model (default `icici_moneysaver`) |

## ICICI login (daily)

The Breeze session dies daily. The 08:00 IST job (or `/login` on the Telegram bot) opens ICICI, fills your
ID + PIN, clicks "Verify with OTP", and the bot asks you for the SMS code — reply with the 6 digits and the
session is set. Manual run: `python scripts/daily_session_refresh.py --headless` (uses `.env`).

## Daily rhythm (what runs by itself)

Scheduled by master-controller (IST, Mon–Fri): 08:00 ICICI login · 08:50 pre-market note · market-hours
alerts/internals · 18:30 EOD ingest · 19:30 Decision Desk (paper) · 19:50 S1 paper shadow · 21:00 wrap —
all with Telegram notices. Nothing places live orders; the system is **paper-only**, and switching any
execution path live requires the owner's explicit review (see `CLAUDE.md` → Trading Rules).

## Checks

```bash
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py   # 37 terminal pages load clean?
```
The five test suites + type checks: `CLAUDE.md` → "How to run things".

## Docker (legacy)

`infra/docker-compose.yml` still describes the old 8-service stack (`./start.sh`). Local operation uses
`start-local.sh`; the dormant services are documented in `CLAUDE.md` → Architecture.

## Troubleshooting

- **Port busy**: `./start-local.sh stop` then `lsof -i :3000 -i :8010` and kill leftovers.
- **DuckDB locked**: only data-service may open the DB; stop stray scripts, restart data-service.
- **ICICI not connected**: Telegram `/login` (or System tab → Broker); the token is daily, not monthly.
- **UI stale after code changes**: `UI_MODE=prod ./start-local.sh restart frontend` (prod uses `ui/.next-prod`;
  the `ui/.next` folder is dev leftovers).
