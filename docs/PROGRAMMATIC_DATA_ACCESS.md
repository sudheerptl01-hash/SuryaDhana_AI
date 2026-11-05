# Programmatic Access for SuryaDhana

**Purpose.** Catalogue of programmatic (API + Python) data sources for sourcing **new information**
into SuryaDhana — macro, energy, cross-country, and event/calendar series to engineer factors
*outside* the exhausted in-house 27-factor + `prob_up` library. (The recombination program is closed:
seven construction levers tested, all dead OOS — see `docs/legacy/SOTA_NESTED_HOLDOUT_VERDICT.md` and the
`suryadhana-5position-bottleneck` memory. The next edge, if any, comes from genuinely new inputs,
not more search over existing factors.)

> ⚠️ **Look-ahead discipline carries over.** Every series below must be ingested **point-in-time**:
> use the value *as it was known on the historical date*, never the latest revised value. For US macro
> this means **ALFRED vintages, not FRED latest** (see §3). This is the same non-negotiable rule that
> governs the backtest engine — a revised GDP/CPI print backfilled into history is look-ahead bias.

---

## 1. Summary table

| Source | What it gives | Python access | Key required | Notes |
|---|---|---|---|---|
| **FRED** | US + global macro series by ID | `fredapi`, `pandas-datareader` | Free API key | Latest (revised) values — **not** PIT |
| **ALFRED** (Archival FRED) | **Vintage / point-in-time** versions of FRED series | `fredapi` (`get_series_first_release` / vintage params), raw ALFRED REST | Same FRED key | **The one most people miss — non-negotiable for backtests** (§3) |
| **EIA** | Energy series (oil, gas, power, inventories, etc.) | `requests` on EIA v2 REST; `eia-python` wrappers | Free API key | All energy series |
| **World Bank** | Global development / macro indicators | `wbgapi` | **None** | No key; clean ID-based access |
| **DBnomics** | Aggregates dozens of official sources in one API | `dbnomics` | **None** | Single API over IMF/Eurostat/OECD/national stats — best first stop for breadth |
| **Eurostat** | EU official statistics | `eurostat`, via DBnomics | None | |
| **OECD** | OECD member macro/indicators | via DBnomics, OECD SDMX | None | |
| **data.gov.in** | Indian government open data | `requests` on the data.gov.in REST API | Free API key | India-specific open datasets |
| **Trading Economics** | Economic calendar w/ consensus + actual | `tradingeconomics` SDK | Paid/registered key | Cleanest calendar-with-consensus if budget allows |
| **investing.com / Forex Factory** | Economic calendar (consensus/actual), scrapeable | direct scrape | None | See investpy caveat (§5) |

---

## 2. Core macro / energy / cross-country

- **FRED API** — US + global series by ID via Python `fredapi` or `pandas-datareader`. The workhorse
  for headline macro (rates, CPI, unemployment, spreads, etc.). Returns **latest revised** values.
- **EIA API** — all the energy series (crude, products, natural gas, electricity, inventories,
  production). EIA v2 is a clean REST API; hit it directly with `requests` or a thin wrapper.
- **World Bank** (`wbgapi`, **no key**) — global development & macro indicators by ID.
- **DBnomics** (`dbnomics`, **no key**) — **aggregates dozens of official sources in one API**
  (IMF, Eurostat, OECD, national statistics offices…). Best single entry point when you want breadth
  without integrating each provider separately.
- **Eurostat**, **OECD** — reachable directly or (simpler) through DBnomics.
- **data.gov.in API** — Indian open data (relevant given the NSE universe focus).

## 3. ALFRED — point-in-time / vintage data (NON-NEGOTIABLE)

**This is the one most people miss, and it's non-negotiable for SuryaDhana.**

- FRED serves the **current, revised** value of a series. A backtest that joins today's revised CPI
  onto a 2022 trading date is using information that **did not exist** on that date — textbook
  look-ahead bias, the exact failure mode the engine's embargo/WFO discipline exists to prevent.
- **ALFRED (Archival FRED)** serves the **vintage** — the value *as first released / as known on a
  given real-world date*. Use it to reconstruct the macro state an agent would actually have seen.
- Access: same FRED API key. Via `fredapi` use the first-release / vintage-date parameters
  (e.g. `get_series_first_release`, `get_series_as_of_date`), or call the ALFRED REST endpoints
  (`series/observations` with `realtime_start` / `realtime_end`) directly.
- **Rule for any macro factor here:** key every observation by its **release/vintage date**, then
  align to trading dates with the standard publication lag — never by the observation's *reference*
  period alone.

## 4. (carry-over) Indian open data

- **data.gov.in API** — register for a free key; query the dataset resource endpoints with `requests`.
  Useful for India-specific macro/sector/administrative series to complement the NSE equity universe.

## 5. Economic calendar (consensus / actual)

- Options: **investing.com** and **Forex Factory** calendars (scrapeable), or the
  **Trading Economics API** for a maintained consensus/actual feed.
- ⚠️ **Caveat:** the old **`investpy`** library **broke** when investing.com changed their site.
  **Do not assume the wrapper works** — scrape the calendars directly, or use Trading Economics' API
  instead of relying on `investpy`.
- For event-study / surprise factors, capture **consensus, actual, and the release timestamp** so the
  "surprise" (actual − consensus) is aligned to the moment it became public (same PIT rule as §3).

---

## 6. Setup notes (SuryaDhana conventions)

**Install into the canonical env** (never system/conda/pyenv):

```bash
/Users/sudheer/Desktop/jupyter_env/bin/pip install fredapi pandas-datareader wbgapi dbnomics eurostat tradingeconomics requests
```

**Secrets — never hardcode keys.** Per the engineering standards, load every API key from the
environment / secret manager, not source:

```bash
# .env (gitignored) — example placeholders, set real values out of band
export FRED_API_KEY=...
export EIA_API_KEY=...
export DATA_GOV_IN_API_KEY=...
export TRADING_ECONOMICS_KEY=...
```

```python
import os
from fredapi import Fred
fred = Fred(api_key=os.environ["FRED_API_KEY"])   # never inline the key
```

**Ingestion checklist for any new external series:**
- [ ] Stored **point-in-time** (vintage/release-dated), not latest-revised — ALFRED for FRED series.
- [ ] Keyed by **release date** and aligned to trading dates with the real publication lag.
- [ ] Provenance recorded (source, series ID, pull timestamp) for reproducibility.
- [ ] No key in source — read from env/secret manager.
- [ ] Validated against the engine's WFO/embargo discipline before it becomes a factor.
