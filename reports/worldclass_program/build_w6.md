# W6 — TICKS: tick persistence + intraday bars/VWAP (build report, 15 Oct 2026)

Expert: market-data engineer. Closes "ticks are memory-only" (QuantLab adoption A4; GAPS §1
VWAP MISS-B, §5). Feeds W1's chart studio (`/intraday` proxy already written against this
contract — verified against build_w1.md: key names match exactly).

## Shipped (own files only — live_ticks.py and main.py untouched; patch blocks below)

| File | What |
|---|---|
| `services/data-service/tick_store.py` (NEW) | `TickStore`: O(µs) `append(symbol, tick)` from the socketio thread into a **bounded** deque (cap 50 000, drop-oldest + `dropped` counter — never OOM; bad rows → `append_strikes`, never an exception). One daemon flusher thread per store, **started lazily on the first append**, stoppable; drains every **FLUSH_S=30 s** and on shutdown. Each drain writes an **atomic numbered part** `data/ticks/YYYY-MM-DD/part-NNNN.parquet` (ONE day-dir holds all symbols; parquet append = read-modify-write is wrong, so parts + glob-read; dot-prefixed temp + `os.replace`, so a crash mid-write can never corrupt earlier parts and readers never see half a file; restart rescans and **continues numbering**). Columns (explicit pyarrow schema → every part concats cleanly): `symbol, ts (IST ISO), price, qty, ttq, bid, ask, prev_close`. Plus the three routes below as an exported `APIRouter` (sync `def` — pandas runs in the threadpool, never on the event loop; pandas/pyarrow imported inside functions so the module import stays cheap for live_ticks). Failed part writes are dropped + counted (`rows_lost_on_flush_error`), never re-queued forever. DuckDB is **never** touched. |
| `tests/unit/test_tick_store.py` (NEW) | 26 tests, all synthetic ticks (no Breeze, no network, no market.duckdb) — list below. The live_ticks hook is tested by applying the patch blocks to a **copy** of the real source (the test fails if any anchor drifts), importing the copy, and driving `_on_tick`. |

### Endpoints (data-service :8001; W1 proxies via ui-api `routers/charts.py`)
- `GET /ticks/bars?symbol=&date=YYYY-MM-DD&interval=1m|5m|15m` → frozen W1 contract (sample below). Missing day/symbol → **200, empty bars + note**. `date` defaults to today IST, `interval` to `1m` (additive conveniences; contract unchanged when both are passed).
- `GET /ticks/vwap?symbol=&date=` → running VWAP + total observed volume + `volume_mode` provenance.
- `GET /ticks/store-status` → buffer size/cap, rows flushed today, last flush, drops, strikes, flush errors, dir.

### Volume semantics (the get-it-RIGHT requirement)
Breeze `ttq` is the *cumulative* day quantity. Per symbol+day, oldest-first:
- **cumulative-ttq**: ttq has ≥2 observations and ≥99 % of steps are ≥0 (tolerates one feed reset — the negative delta clips to 0) → per-tick `v = diff(ttq)`; the **first observation contributes v=0** (volume traded before we subscribed is unattributable — VWAP is "since first tick seen", stated honestly). Total volume = lastₜₜq − firstₜₜq.
- **per-tick-qty**: otherwise, when a `qty`/`ltq` column exists → `v = qty` summed per bar.
- **none**: neither usable → bars still form with `v=0`, `vwap: null` + note (no fake volume).
VWAP = Σ(price·v)/Σv over the day; bar `v` = Σ per-tick v inside the bin; OHLC = first/max/min/last by arrival order (stable sort; ts is seconds-precision, arrival order breaks ties).

## PATCH BLOCKS (PM applies; both verified by tests that apply them to a copy)

### (a) `services/data-service/live_ticks.py` — 3 edits (the hook)

**1. Import** (module stays import-light; tick_store defers pandas/pyarrow into functions):
```
OLD:
from shared.breeze_cache import patch_socketio_wait
from shared.logging import get_logger

NEW:
from shared.breeze_cache import patch_socketio_wait
from shared.logging import get_logger

import tick_store  # W6: tick persistence — lazy, kill-switched; see the _on_tick hook
```

**2. `LiveTicks.__init__` state** (end of the ctor):
```
OLD:
        self._last_sync = 0.0
        self._first_tick_logged = False

NEW:
        self._last_sync = 0.0
        self._first_tick_logged = False
        self._store: Any = None            # W6: lazy TickStore; False = persistence decided OFF
```

**3. `_on_tick` hook** (very end of the ingest path, after the DEGRADED flip-back — inside the
existing try so even the impossible can't break feed bookkeeping):
```
OLD:
            self.last_tick_at = now
            if self.state == DEGRADED:
                self._set_state(LIVE, None)                              # minor 15: flip back on next tick

NEW:
            self.last_tick_at = now
            if self.state == DEGRADED:
                self._set_state(LIVE, None)                              # minor 15: flip back on next tick
            # W6 TICKS: persist to parquet via tick_store — constructed lazily ONLY when a tick
            # actually flows (zero cost while LIVE_TICKS=0). TICK_PERSIST kill switch, default ON
            # whenever ticks flow; read once per worker life. append() never raises (strike
            # counter in store stats) and this guard covers construction too: persistence can
            # NEVER break the feed.
            try:
                if self._store is None:
                    self._store = tick_store.get_store() if tick_store.persist_enabled() else False
                if self._store:
                    self._store.append(sym, tick)
            except Exception:  # noqa: BLE001 — persistence must never break the stream
                pass
```

Kill-switch doc: `TICK_PERSIST` default **ON when LIVE_TICKS=1** — the hook only runs when ticks
flow, i.e. when LIVE_TICKS=1 armed the websocket, so the default is "persist whenever ticks flow"
and costs literally nothing while LIVE_TICKS=0 (no store object, no thread, no dirs, not even an
env read). `TICK_PERSIST=0` streams without writing; env is read once per worker life (restart to
flip). `_on_tick` runs on the single socketio thread → `self._store` needs no lock.

### (b) `services/data-service/main.py` — 3 edits (mount + clean shutdown)

**1. Import** — after the live_ticks import:
```
OLD:
import live_ticks as live_ticks_mod

NEW:
import live_ticks as live_ticks_mod
import tick_store as tick_store_mod
```

**2. Mount** — right after the app is constructed:
```
OLD:
app = FastAPI(
    title="SuryaDhana — Data Service",
    version="1.0.0",
    lifespan=lifespan,
)

NEW:
app = FastAPI(
    title="SuryaDhana — Data Service",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(tick_store_mod.router)   # W6: /ticks/bars, /ticks/vwap, /ticks/store-status
```

**3. Lifespan shutdown** — after live_ticks teardown (stop the tick source, then final-flush):
```
OLD:
    try:
        live_ticks_mod.shutdown_instance()
    except Exception:
        pass

NEW:
    try:
        live_ticks_mod.shutdown_instance()
    except Exception:
        pass
    try:
        tick_store_mod.shutdown_store()     # W6: final tick flush (no-op when never started)
    except Exception:
        pass
```

### (c) optional, `.env.example` — document the switch (one line, after `LIVE_TICKS=0`):
```
TICK_PERSIST=1   # W6: persist live ticks to data/ticks/<date>/part-*.parquet (only acts when LIVE_TICKS=1)
```
Dir override: `TICKS_DIR` env (default `<repo>/data/ticks`). **Add `data/ticks/` to .gitignore**
if `data/` isn't already ignored wholesale (market.duckdb's dir is git-ignored — same treatment).

## Bars-contract sample (actual endpoint output, hand-checked fixture)

`GET /ticks/bars?symbol=TCS&date=2026-10-14&interval=5m`
```json
{"symbol": "TCS", "date": "2026-10-14", "interval": "5m",
 "bars": [{"t": "09:15", "o": 100.0, "h": 101.0, "l": 100.0, "c": 100.5, "v": 300},
          {"t": "09:20", "o": 102.0, "h": 102.0, "l": 101.5, "c": 101.5, "v": 500},
          {"t": "09:30", "o": 103.0, "h": 103.0, "l": 103.0, "c": 103.0, "v": 100}],
 "vwap": 101.5833, "source": "icici-ws"}
```
Hand check: 6 ticks, ttq 100→1000; vwap = (101·150+100.5·150+102·300+101.5·200+103·100)/900 =
91425/900 = 101.5833 ✓. Missing day → `{"symbol","date","interval","bars":[],"vwap":null,
"source":"icici-ws","note":"no tick data for TCS on 2026-01-02"}` (200).
`GET /ticks/vwap?symbol=TCS&date=2026-10-14` → `{"vwap":101.5833,"volume":900,"ticks":6,
"last_price":103.0,"volume_mode":"cumulative-ttq","as_of":"2026-10-14T09:34:10+05:30","source":"icici-ws"}`.

## Test results (all with /Users/sudheer/Desktop/jupyter_env/bin/python)

- `pytest tests/unit/test_tick_store.py` → **26 passed** (0.7 s): cap/drop-oldest counters + default
  cap is 50k; append strikes never raise; junk `as_of` can't poison the day-dir name; one part per
  day for all symbols; restart continues part numbering; corrupt part + stale `.tmp` skipped with
  note (good parts still served); hand-checked 5m/1m/15m OHLCV + VWAP; **10 000-tick cumulative-ttq
  day vs an independent pure-python recompute (exact match, 9 bars + VWAP + no cross-symbol
  bleed)**; per-tick-qty mode; non-monotone ttq → qty → none fallbacks; single feed reset tolerated;
  200-with-note empty contract; frozen key names; 422 validation; unflushed buffer rows visible in
  bars; store-status; lazy flusher start → periodic flush → final drain on stop (idempotent);
  flush-error rows dropped+counted; shutdown_store; **4 hook tests on the patched copy** (persists +
  lazy, TICK_PERSIST=0, store failure never breaks the feed, A5/minor-15 behavior unregressed) +
  main.py anchor check.
- `pytest tests/unit/test_live_ticks.py` → **8 passed** (file untouched — stays green by construction).
- `pytest tests/unit -q` → **298 passed** (whole unit suite, collection-safe).
- `compileall tick_store.py test_tick_store.py` → clean.

## Flush & size math (measured, not guessed — 50-symbol worst case)

- Rate: Breeze exchange-quote stream ≈ 1 conflated msg/s per active symbol; session 09:15–15:30 =
  22 500 s → worst ≈ **1.125 M ticks/day** at the 50-symbol cap (typical mid-cap mix: 0.3–0.5×).
- Measured on disk (snappy, explicit schema): **12.8 B/row** at 1 500-row parts → **14.4 MB/day**
  worst case, ~750 parts/day (one per 30 s flush; parts only when the buffer is non-empty).
  ⇒ a full trading year ≈ 3.6 GB upper bound, ~1–2 GB realistic — rotation is a follow-up, not urgent.
- Buffer: worst inflow 50 rows/s → ~1 500 rows per 30 s flush; cap 50 000 ≈ **16 min of flusher
  outage** before any drop (a 5-tick/s burst still leaves >3 min). Memory at cap ≈ 18 MB. Flush
  cost ≈ 12 ms per part (9.2 s for 750 parts) on the daemon thread — appends never wait on IO.
- Read latency, measured on the full worst-case day (750 parts / 1.125 M rows): `GET /ticks/bars`
  1m = **417 ms**, `/ticks/vwap` = 408 ms — dominated by 750 file opens; fine for a threadpool
  route + W1's 60 s refresh, and EOD compaction (follow-up) takes it to ~50 ms.

## Cuts (stated, deliberate)
- **No retention/rotation job tonight** — day-dirs accumulate (~14 MB/day worst); follow-up: a
  controller EOD job that compacts a day's parts into one file and zips/deletes dirs older than N days.
- **L1 only**: best bid/ask stored (depth panel later; Breeze best-5 depth not subscribed by live_ticks).
- `qty` column is ready but null today — live_ticks doesn't capture Breeze `ltq`; volume correctly
  comes from the ttq diff. If a feed variant sends per-tick qty, the store + reader already handle it.
- No replay/stream endpoint (bars+vwap suffice for W1); no ui-api proxy here (W1 owns charts.py — his
  degraded-200 handling was written for exactly this mount).

## Risks / honesty
- If Breeze omits `ttq` on some payload variant, bars appear with `v=0` and `vwap: null` + an explicit
  note — honest degrade, no fabricated volume. First live session should eyeball `/ticks/store-status`
  and one `/ticks/vwap` against the exchange's day volume.
- VWAP is **since first tick seen** (pre-subscribe volume unattributable). After a mid-session
  data-service restart the parts persist (that's the point) but the restart gap's volume lands in the
  first post-restart delta of each symbol — clipped only if negative, else attributed to the first new
  tick's price. One-tick smear, bounded by the gap volume; worth a line in W1's tooltip someday.
- Part numbering assumes one data-service process (true by architecture: it owns DuckDB too).
- Rows lost only in three bounded, counted ways: buffer cap (16 min outage), part-write failure
  (disk full), process kill between flushes (≤30 s of ticks) — all visible in `/ticks/store-status`.

No restarts, no commits, no Telegram, no secrets, no DuckDB opens, no Breeze calls (ICICI session
invalid until ~08:00 — everything synthetic). ~2 h.
