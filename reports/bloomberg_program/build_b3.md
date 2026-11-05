# Build report — B3 Live data (14 Oct 2026, ~22:4x IST)

Scope: REQUIREMENTS F3.1–F3.4 per DESIGN_SYSTEMS §6 **as amended** (A1 ensure-on-GET union+TTL, A5 prev-close
preference+clamp, A8 single-writer patches, minor 15 watchdog flip-back). Kill switch `LIVE_TICKS` **defaults
OFF** per the gate; nothing connects until the Phase-4 spike passes and the PM arms it.

## Shipped
| File | What |
|---|---|
| `services/data-service/live_ticks.py` (new, ~370 lines) | the tick engine: `LiveTicks` state machine, one `live-ticks-ws` worker thread (connect + resubscribe + watchdog in one loop), union/TTL/cap-50 subscriptions with holdings pinned (`_target_set`), per-symbol ISEC resolution via the provider (failures non-fatal in `_sub_errors`), defensive tick mapping with one-time first-tick debug log, prev-close preference order (tick `close` → bhavcopy join → None), 25% clamp + hint, strikes/cool-off, module singleton `init()/instance()/shutdown_instance()` |
| `services/data-service/main.py` | import (:65 area), lifespan `live_ticks_mod.init(get_live_provider, _prev_close_for, _holdings_symbols)` right after the provider build; shutdown hook first in the teardown block; helpers `_prev_close_for` (bhavcopy max-date closes, worker-thread only) + `_holdings_symbols`; **`GET /live/ticks?symbols=`** (sync def, ensure-on-GET per A1) next to `/provider/status`, which now carries an additive `live_ticks` status key; `datetime` added to the stdlib import |
| `shared/breeze_cache.py` | `patch_socketio_wait(seconds=20)` — the socketio `wait_timeout` fix as a shared helper (idempotent, same marker as the catalog script's local copy, which stays untouched); existing breeze_cache tests still pass |
| `services/ui-api/routers/quotes.py` (new) | `GET /api/quotes/live` **and** alias `GET /api/quotes/ticks` (one handler — kills the F3.2/UIX naming split): per-symbol merge of fresh ticks (≤5 s → `source:"icici-ws"`) with the existing Yahoo path (`news_scanner.get_quotes`, `source:"yahoo"`); request symbols ∪ saved holdings pushed in every ensure call; feed OFF/stale/UNREACHABLE ⇒ full Yahoo fallback with the state told honestly |
| `tests/unit/test_live_ticks.py` (new, 7 tests) | kill-switch inertness (provider never touched) · union+TTL+cap-50+pinned-holdings · ISEC-coded subscribe/diff/unsubscribe + per-symbol failure · tick ingestion with A5 preference, fallback and clamp+hint · watchdog DEGRADED→(next tick)→LIVE and silent-outside-market-hours · 3-strikes cool-off blocks `_kick` · idempotent shutdown with ws_disconnect |
| `services/ui-api/tests/test_quotes.py` (new, 4 tests) | fresh-tick win + holdings unioned into the ask · stale/missing → per-symbol Yahoo · OFF and UNREACHABLE degrade honestly · clamp hint passthrough |

## State machine
```
            ensure() & LIVE_TICKS=1 & provider connected
   OFF ────────────────────────────────▶ CONNECTING ──ws_connect ok──▶ LIVE ◀─┐
    ▲                                       │  ✗ (strike, backoff 2..60s)     │ next tick
    │ shutdown()                            │  3 strikes/5min                 │ (minor 15)
    │                                       ▼                                 │
    └──────────────── DISCONNECTED ◀── [cool-off 10 min] ──▶ DEGRADED ────────┘
        (provider session died;                 ▲   no ticks >120s in market hours
         next ensure() restarts)                └── watchdog, global
```

## Test / verification output
- `tests/unit` **271 passed** (includes the 7 new) · `services/ui-api/tests` **342 passed** (includes the 4 new)
- `compileall` clean on both services + shared/breeze_cache.py; inert-path smoke run (kill switch OFF → state
  OFF, provider untouched, bad symbols filtered)
- Two falsy-zero bugs found by the tests and fixed in the module (`last_tick_at`/`ref` at 0.0 silently disabled
  the watchdog)
- **F3.4 census (quota safety):** every `breeze.get_quotes(`/`get_live_quote(` call-site in the repo is
  pre-existing (api-gateway dormant, execution legacy, data-service `/live/quote`, data_proxy, gold MCX, catalog
  script). B3 added **zero** ICICI REST quote calls; `routers/quotes.py` imports only the Yahoo
  `news_scanner.get_quotes`, joining alerts.py and markets.py as existing importers.

## PATCH BLOCK for services/ui-api/main.py (A8 — applied by the file's owner B2, or the PM)
```python
# with the other router imports (line ~55):
from routers import quotes
# with the other include_router lines (next to news_scanner, line ~113):
app.include_router(quotes.router, prefix="/api/quotes", tags=["quotes"])
```
Until this lands + ui-api restarts, `/api/quotes/live` 404s; data-service `/live/ticks` is complete on its own.

## Phase-4 live spike (market closed tonight — run once while the ICICI session is valid)
```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
LIVE_TICKS=1 /Users/sudheer/Desktop/jupyter_env/bin/python - <<'EOF'
import sys, time
sys.path.insert(0, "."); sys.path.insert(0, "services/data-service")
from shared.breeze_cache import install; install()
from shared.icici import load_icici_credentials
from providers import build_live_provider
import live_ticks
c = load_icici_credentials()
prov = build_live_provider(c.api_key, c.api_secret, c.session_token); prov.connect()
assert prov.is_connected(), "session invalid — abort spike"
lt = live_ticks.init(lambda: prov)
print(lt.ensure(["TCS", "RELIANCE"]))
for _ in range(12):
    time.sleep(5); print(lt.status())
lt.shutdown(); prov.disconnect(); print("teardown clean")
EOF
```
Expected: state reaches **LIVE** within ~30 s; `subscribed: 2+holdings`; zero ticks is OK while the market is
closed (watchdog only fires in market hours); teardown exits cleanly ≤60 s. In-hours expectation: first tick
within seconds, snapshot carries `price/chg_pct/prev_close`, debug log shows the first raw tick's field names
(verify the A5 `close` alias). **Abort criteria:** session invalidated by ws_connect (re-login needed after —
check `/provider/status`), python exceptions outside the strike path, or state thrashing LIVE↔DEGRADED off-hours
→ keep `LIVE_TICKS` unset (feature stays dark, Yahoo chips honest) and file the log with the PM.

## NOT done / handoffs (honest)
1. **Frontend hook + chips (F3.3) are B4's** — `useLiveTicks`/SourceChip against `/api/quotes/ticks` (alias live).
2. **ui-api mount** waits on the patch block above (A8) + the PM's restart; **data-service restart** also needed
   before `/live/ticks` exists on :8001.
3. **B2's cache-cap patch for data-service `main.py`** (`_typical_cache`/`_fo_eod_cache`, per minor 17): build_b2.md
   did not exist while I held the file — the PM applies B2's block after both builders finish.
4. **Live ws spike deferred to Phase 4** by design (kill switch OFF; market closed). The designed POST
   `/live/ticks/symbols` was **dropped, deliberately**: ensure-on-GET (A1) makes it redundant and the program is
   deleting dead routes, not adding them — flagged here for the critic.
5. Real Breeze tick field names remain the one unknown (defensive aliases + first-tick log in place).
