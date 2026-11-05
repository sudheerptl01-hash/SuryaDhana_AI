# MCX Gold Pre-Open Tracking Checklist (polished)

**Goal:** before MCX opens, know what happened overnight and how much of it should show up in today's MCX Gold open. Each step answers one question and feeds one block of the daily JSON (`YYYYMMDD.json`, schema v1.0.0).

---

## Step 1: Lock the baselines (`baseline`)
**Question:** What prices did MCX close against last night?

- **MCX Gold close/settle** for the active contract (broker terminal or the mcxindia.com bhavcopy). This replaces any assumed number.
- **Gold at the MCX close time.** Use XAUUSD spot or GC front at 23:30 IST (23:55 IST in US winter), not the COMEX 1:30 pm ET settle. Your gap must start from the moment MCX stopped trading.
- **USD/INR close** from the prior day.

> Settling a price conflict (like $4,158 vs $4,105): check the exact contract (GCZ26 vs spot) and the timestamp. The two numbers are usually an intraday high and low, or spot vs futures, so compare like with like.

## Step 2: Overnight gold move (`overnight_markets.xauusd_spot`, `comex_gold_front`)
**Question:** How far has gold moved since MCX closed?

- Latest XAUUSD and GC front, compared with the Step 1 anchor and your reference level (`T1_COMEX_REF`).

## Step 3: Rupee (`usdinr_spot`, `usdinr_ndf`)
**Question:** Will the rupee add to or subtract from the gap?

- Before 9:00, use the USD/INR NDF. After 9:00, use the spot open. Read the FBIL reference later as confirmation.
- Compare with your reference (`T2_USDINR_REF`). A weaker rupee (USD/INR higher) lifts MCX.

## Step 4: Compute the gap (`gap_model`)
```
gap   = 356 × ΔCOMEX/10 + 1,521 × ΔINR
fair  = MCX prev close + gap
```
- Rs 356 per $10 of gold and Rs 1,521 per Rs 1 of USD/INR.
- **Upgrade:** recompute the coefficients daily from the previous close. The gold coefficient is MCX ÷ COMEX × 10 and the rupee coefficient is MCX ÷ USDINR. On 9 Oct they came out at 362 and 1,544, close to the static values, so the model holds.

## Step 5: Rates and dollar (`us10y`, `us10y_real_tips`, `dxy`, `eurusd`)
**Question:** Is the opportunity cost of holding gold rising or falling?

- US 10Y, the live 10Y TIPS real yield (FRED DFII10 lags one day), DXY, and EUR/USD against your trigger (`T3_EURUSD_TRIGGER`).
- In the current regime (Fed hiking, 10Y above 5%), **real yields are the main driver**. Oil moves into gold through inflation and Fed pricing, so higher oil can be *bearish* for gold.

## Step 6: Fed odds (`fed_and_rates`)
- CME FedWatch: next-meeting hold/hike % and December hike %, compared with yesterday's values (`T4`, `T5`). Add one line on any Fed speaker from the last 24 hours.

## Step 7: 360° headlines (`news[]`)
Sweep every channel that moves gold and tag each item with impact, strength (1–5) and transmission channel:
- **Geopolitics/energy:** Iran/Hormuz, oil supply
- **Europe/FX:** France (OAT-Bund spread), EUR, JPY, CNY
- **Macro data:** US, India, China
- **Physical demand:** SGE premium and volume, Indian dealer premium/discount, festive demand
- **Flows:** GLD tonnes, WGC ETF flows, central-bank buying
- **India policy:** duty, GST, RBI

## Step 8: Exchange housekeeping (`exchange_housekeeping`)
- MCX circulars on margin or special-margin changes, contract changes, and trading hours. A margin hike usually brings forced liquidation, so size down when you see one.

## Step 9: Pre-open decision (`gap_model.open_signal`)
- Compare the MCX pre-open/indicative price with the model's fair open.
  - **Within ±Rs 300:** `aligned_tradeable`. The gap is fair, so trade your plan.
  - **More than Rs 300 away:** `dislocated_wait_15_30m`. Don't chase. Wait for the rupee's 9:00 open to settle and let price come back toward the model.

## Step 10: Synthesis (`synthesis`)
- One paragraph on what happened, the regime, bullish and bearish drivers, bias score (−5 to +5), expected range, open plan, and invalidation.

---

### Can this be automated?
Yes. A daily scheduled task (Mon–Fri, before the open) runs Steps 1–10 with web research and writes `YYYYMMDD.json` to `SuryaDhana_AI/gold_premarket/`, the same way the soft-catalyst scanner writes to `new_scnner/`. Limits of the automated version:
- No access to your broker terminal, so the **MCX pre-open/indicative price and the exact bhavcopy settle may be derived from news prints**. They're flagged `is_derived: true`. Paste the broker figure in if it differs.
- **Bloomberg and Reuters terminals are paywalled.** NDF and live TIPS come from free proxies and are marked with a confidence level.
- Every missing or conflicting value is listed in `data_quality`, so the app can see what to trust.
