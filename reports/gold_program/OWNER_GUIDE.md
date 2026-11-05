# The GOLD page: an owner's guide (26 Oct 2026)

Plain English, for the person who trades MCX gold and asked for "a health check, COT, OTC, the Kitco chart, days /
weeks / months, who is long and short, a contract chooser, auto-login, and only what is useful". This guide describes the
page as `PLAN.md` specifies it and as phase 2 builds it; a panel whose feed is not yet running shows its last stored value
with a STALE chip, or the reason it is empty ("since <the day its job first ran>", "LINK-ONLY until O-2"), never a blank. The research the
page rests on is in `FINDINGS.md` (one line: **nothing in gold positioning, flows, macro or the calendar forecasts the
price; all of it describes the week that just happened, and that is what the page shows**).

## 1. Open it

Type `GOLD` in the GO bar (or `XAU`, `GC`; `COT` jumps to POSITIONING, `GPHY` to PHYSICAL, `GMAC` to MACRO, `LRN` to
LEARN). It sits next to CMDT and MCXG. MCXG stays your trading desk (quote, contract selector, paper ticket); GOLD is
where you *understand* gold. Nine sub-views across the top: **HEALTH · DAILY · WEEKLY · MONTHLY · POSITIONING · PHYSICAL ·
MACRO · CONTRACTS · LEARN**. The contract you pick (exchange × family × expiry, top of the page) is remembered and shared
with MCXG.

## 2. Read it in 10 minutes

1. **The header strip** (the only live prices on the page): COMEX matched-month settlement and live price · USD/INR ·
   10-year real yield · MCX settlement, labelled by its *session* ("Thu 22 Oct settlement", never the date of the file
   that carried it) · the basis of MCX over duty-paid landed gold · managed-money net from the last COT with its
   week-on-week change · "MCX opens in …". These are the five things you are long when you buy an MCX lot: gold, the
   rupee, a duty regime, the premium and the crowd. Hover the strip for the four instruments named (spot proxy, COMEX
   front GC1, matched month, MCX contract) so you never compare the wrong two.
2. **HEALTH › the verdict sentence**: "WEAK WEEK, DOLLAR-DRIVEN · gold −2.8 % over the week · of which the dollar −1.9 %
   · real yield +12 bp · funds net 104,206 (−2.7 % w/w, long liquidation) · India basis +0.4 % vs duty-paid landed · roll
   DEC-26→FEB-27 costs +1.03 % (+3.2 %/yr), FND in 35 d · GLD −12.0 t on the day (notable) · **describes, does not
   predict**". Every clause is a threshold on a stored number (LEARN §8.4 lists each rule exactly as the code applies it,
   and LEARN shows the live clauses with their rule ids above that table); a stale input is left out, never guessed; the
   last three words are part of the sentence on purpose.
3. **HEALTH › the eight tiles** (trend, real yield, dollar, positioning, India basis, Shanghai premium, ETF holdings,
   curve/roll): each with a 60-day sparkline and a one-line "how to read". There is no score and no count of
   "supportive" tiles, because a score would read as a forecast and no driver has earned one.
4. **HEALTH › Today's open** (the old CMDT pre-open desk, moved here): fair open, the gap split into the COMEX part and
   the rupee part, OK / WAIT. The verdict wears a `heuristic` chip with the measured miss so far (3 scored mornings,
   none within ₹300): treat it as arithmetic about where MCX *should* open, not a call on the day.
5. **HEALTH › Event risk**: the next seven days in IST — FOMC (after the MCX close in US winter: a gap at 09:00), US
   CPI / NFP / PCE (inside the MCX evening: tradable), the COT release, MCX expiries, COMEX first notice day, the Budget.
6. **POSITIONING › who did what**: "funds closed 3,777 longs and covered 894 shorts; long liquidation; OI 402,279; as of
   Tue 20 Oct, released Fri 23 Oct, next Sat 31 Oct 01:00 IST". Paired bars show who is long and who is short across the
   five trader groups. This answers your "who is long, who is short, what got closed" — weekly, with a three-day lag,
   COMEX only. The one-word label is the larger of the two fund legs: when price fell and funds still added more longs
   than shorts it reads "funds bought the dip" (the 27 Oct 2026 week), never "new shorts" for a handful of new shorts.
   The crowdedness gauge beside it is worded "not a signal" and is never coloured.
7. **POSITIONING › daily**: COMEX open interest by product (T+1, ≈ 15:30 IST) and MCX open interest per contract (07:35),
   each with "positions opened / closed" read against the price move. This answers "daily" — exchanges publish how many
   positions closed, never who closed them.
8. **PHYSICAL › the India price stack**: COMEX → × USD/INR → landed ₹/10 g → + 15 % duty (dated; see §8) → duty-paid →
   IBJA premium → MCX basis and carry, each bar with its timestamp. The old "18 % implied premium" was 0.995 × 1.15 ×
   1.031: mostly duty.
9. **MACRO › drivers**: the real yield and the dollar with a supportive / headwind tag and their recent correlation to
   gold; "Gold or the dollar?" splits today's move into pure gold, the dollar and (for MCX) the rupee.
10. **CONTRACTS › roll calendar**: when your contract tenders, when COMEX's first notice day is, what the roll costs.

## 3. The routine (also at the top of LEARN, as checklists with links)

- **Daily, 08:30–08:55 (10 min):** header strip → HEALTH verdict and tiles → Today's open (decide OK / WAIT before
  09:00; the ₹300 limit is unproven) → drivers and headlines → yesterday's OI × price read → the expected move in rupees
  per lot (`mc.move`) and the tender cut-off if it is within a week. Evening 23:00–23:30: the 24-h chart (DAILY) for the
  COMEX settlement vs the MCX close; tomorrow's events.
- **Weekly, Saturday morning (20 min):** POSITIONING hero and bars (the COT lands Saturday 01:00 IST; 02:00 from Sat 7 Nov, the first release after US clocks change on 1 Nov)
  → ETF tonnes week on week → OTC window (LBMA turnover, EFP prints) → term structure and carry → premium and basis
  history → next week's calendar. WEEKLY gives the Mon–Fri table with CSV export and the 26-week heat grid.
- **Monthly, first weekend:** central banks (IMF, PBoC streak, RBI) → vaults, SGE withdrawals, India imports, Swiss
  exports, AMFI → the regime check on MACRO (how well the real-yield rule has been working) → the accuracy log (the
  chase-limit decision at 20 rows) → any margin change on the selector.

## 4. What each badge and chip means

| Badge | Means | Examples |
|---|---|---|
| `signal` | a pre-registered study passed as a forecast in both halves after costs. **None exists today.** | — |
| `context` | describes what happened or where things stand; proven to explain the week, proven *not* to forecast the next | the COT strip, every health tile, premiums, ETF flows, central banks, the seasonality grid |
| `arithmetic` | an identity, a cost or a spec; makes no claim about the future | fair open, landed cost, carry, tick value, the "gold or the dollar" split, the expected move per lot |
| `heuristic` | a house rule with no evidence yet; the chip carries the measured error where one exists | the ₹300 chase limit, the headline risk-word count |

Chips: **LIVE** (Breeze) / **DELAYED** (Yahoo, ≈ 1 min) / **STALE** (older than the series' allowed age; the last stored
value stays visible with its date) / **OFFLINE**; **PROXY** on the MCX settlement (the midpoint of ICICI's price band, not
the exchange's number, until the owner decides O-8); **LAST TRADE** on COMEX per-month prices (Yahoo's last trade, not
the settlement, until CME's bulletin is allowed, O-2); **PROVISIONAL** on the LBMA AM/PM marks (fetched through WGC's chart
API until O-1). Daily data shows its date, never a clock. Context numbers are never coloured bullish or bearish; green and
red appear only on price changes and on the fair-vs-live comparison. Every panel header has an "about" popover (publisher,
cadence, lag, formula, pitfalls, verdict) and a **[B] / [P]** toggle between the plain line and the exact definition;
dotted-underlined words open the glossary (160 terms; a dozen "start here" terms sit above the alphabet until you type, and
the search understands the page's own abbreviations — MM, OI, FND, w/w, bp, GC1).

## 5. ICICI auto-login, step by step

The code for a zero-touch 08:00 login already exists and is tested; **the only missing piece is the authenticator setup
key** (`ICICI_TOTP_SECRET`), which is in neither `.env` nor the Keychain. Until it is stored, the 08:00 job falls back to
the SMS OTP you answer on Telegram (`/login`), as on 23 Oct.

**Today, by hand (PLAN §g, owner action O-4):**

1. **Get the key.** On icicidirect.com: Settings → *Disable Login Authenticator* (enter PIN) → *Login Authenticator* →
   Google Authenticator → when the QR code appears, also copy the text under "manually enter the provided key" (that
   text is the setup key, usually 16–32 letters and digits). Scan the QR on your phone as well, so the phone and the Mac
   share the same key. (Alternative: export from Google Authenticator and decode the `otpauth-migration://` QR offline on
   this Mac; never paste it into a website.)
2. **Store it in the macOS Keychain, not in a file.** In Terminal, in the project folder:
   ```bash
   security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w
   ```
   It prompts for the value (type or paste it; nothing lands in the command history). Then `chmod 600 .env` (the file is
   0644 today). The Keychain is encrypted, readable only by `/usr/bin/security` for your user, and is not in git or the project's
   02:15 backups (your login keychain is only as backed up as your own Time Machine / iCloud Keychain settings make it): on
   a new Mac you repeat this step (RUNBOOK §2).
3. **Test it once, attended, after 15:40 IST** (never 07:30–09:30, when the real job and the pre-open work run):
   ```bash
   /Users/sudheer/Desktop/jupyter_env/bin/python scripts/daily_session_refresh.py --force
   ```
   Expect, in order: `code panel: totp` → `submitted authenticator code (single attempt)` → `RESULT refreshed`. If ICICI
   rejects the code, note the exact wording on the page (not a screenshot — it would show account details): it is
   either a wrong key (re-do step 1) or the inferred Submit button (a code fix, G-LOGIN R1).
4. **Tomorrow 08:00:** Telegram should say "ICICI session refreshed" with no OTP prompt. The BRKR page shows
   `TOTP CONFIGURED · Keychain`.

**From the BRKR page, once phase 2 ships (the "Auto-login (TOTP)" panel):** Step 1 shows the same three lines with an
*OPEN ICICI SETTINGS* button; Step 2 is a masked box where you paste the key and the page shows the current six-digit
code with a 30-second bar — open Google Authenticator and check the ICICI entry shows the same digits (wait for one
rollover); Step 3 asks you to type that code to confirm and saves the key (the page never shows or logs the secret);
Step 4 *CHECK SESSION / LOG IN IF EXPIRED* runs the login and watches it to `● LIVE`. *DISABLE AUTO-LOGIN* removes the
`.env` copy (a Keychain copy, if any, is removed by hand). If ICICI ever rejects the authenticator code, the morning job
falls back to SMS and the panel shows `TOTP MISMATCH — re-register`.

Rules the code keeps: one attempt per run; the secret never appears in logs, Telegram, screenshots, settings sync or a
URL; `.env` with the seed is a complete login, so it stays 0600 and your password-manager copy is treated the same way.

## 6. What is deliberately NOT shown, and why

- **No score, no "N of 8 supportive", no tightness index.** 0 of 69 walk-forward positioning rules beat buy-and-hold
  (G-STUDY); a composite reads as a forecast it cannot be. The verdict is a sentence of facts.
- **No COT buy/sell signal, alert or long/flat rule; the COT index is never coloured.** The classic "crowded / washed
  out" rule points the wrong way in 20 years of data. The page shows who did what; it never says what to do.
- **No fair-value forecast of the gold price.** The real-yield / dollar regression says $788 with gold at $4,000 and its
  refit has the wrong sign (G-MACRO H5): DO-NOT-PUBLISH.
- **No options-only positioning panel.** One line in the POSITIONING drawer ("options add +4,479 to funds' net"), because
  the study found no information in it — but you asked for "futures/options", so the number is there.
- **COMEX warehouse stocks, deliveries, the daily bulletin, FedWatch, CME contract pages: links, not numbers**, until you
  resolve CME's block of this IP (O-2; `www.cmegroup.com` is never fetched by the stack). The CME **FTP** files (daily OI
  by product, EFP prints, the expiry calendar, contract specs) are fetched and shown.
- **MCX official bhavcopy, category-wise OI ("who holds MCX gold"), spot polling, option chain: dormant.** MCX's site
  blocks every scripted client; the schema and a placeholder panel exist, with the reason, until you decide whether a
  browser-session collector is acceptable (O-8). The ICICI master's band midpoint stands in as the settlement (PROXY).
- **Kitco is a link.** Its terms forbid embedding and scraping; the DAILY chart is built from our own stored 1-minute
  bars with the same ideas (previous day dotted, settlement dashed, session bands including MCX hours, IST over NY).
- **No LBMA price table.** It needs an IBA licence; the fix times are marks on the chart and the WGC chart's AM/PM
  serve as provisional reference marks only.
- **stooq, goldprice.org, investing.com: not even linked** (proof-of-work walls, 403s, or terms). Yahoo covers them.
- **No second Yahoo poller anywhere.** One cached fetcher and data-service's jobs own the whole budget (≤ 6 chart calls a
  minute across the app); a 429 on 26 Oct showed what happens otherwise. Histories therefore **start the day the jobs
  start** (the panel prints "since <that date>") — the page says so rather than backfilling from a chart.
- **No sizing advice from headlines.** The risk-word count is a tally with a `heuristic` chip; "consider half size" went.
- **Nothing gold reaches the Decision Desk, the S1 shadow, a directional alert or the paper ticket's price.** The ticket
  gains sizing arithmetic only (max lots at 1 % risk, the USD/INR hedge, ATR in rupees).
- **Same number, once.** The pre-open desk leaves CMDT, BRF keeps one line, WEI keeps its row plus one line and a hover,
  MCXG's overlay becomes one line that links here, the tape's "GOLD" quote is relabelled "GOLD GC1". Repetition is a defect.

## 7. Your decisions (ordered; nothing below is done by the builders)

1. **O-1 terms posture** for WGC, SPDR (GLD), IBJA, SGE: the default is private display with attribution, one fetch a day,
   nothing re-served; downgrade any of them to a link if you prefer. Kitco is a link regardless.
2. **O-3 the duty**: confirm Notification 16/2026-Customs (BCD 10 % + AIDC 5 % = 15 % since 13 May 2026) at cbic.gov.in
   in a browser; the terminal prints "confirm at CBIC" until you do, and `GOLD_IMPORT_DUTY_PCT=15` with its effective date
   goes into `.env`.
3. **O-4 TOTP today** (§5).
4. **O-5 / O-6** approve the page, the consolidation, the 21 tables, the schedule and the one-off backfills (the CME FTP
   pull is ≈ 2 hours and 330 MB in passing; every history starts the day you approve it, so earlier is cheaper).
5. **O-2 CME**: open the CME gold volume page in a normal browser; if it is blocked, email gcc@cmegroup.com stating
   personal, non-commercial use.
6. **O-8 MCX / Breeze**: whether a nightly browser-session collector for MCX files is acceptable, and whether one
   credentialed Breeze pull of MCX daily history is allowed so the studies can run on the instrument you actually trade.
7. **O-9** ICICI's tender cut-off for MCX GOLD / GOLDM (not in the repo): it decides when a swing position must roll.
8. **O-13** approve the pre-registered study plans (G-STUDY-2, GS-P2, GS-P3, the G-INDIA OI matrix) before any result is
   looked at; **O-14** approve the Telegram wording (08:45 with the measured miss, the Saturday COT digest).
9. Optional: a free CFTC app token, a free FRED key (ALFRED vintages), a Goldhub login (O-7); read the Atlanta Fed and
   SPDR licence text by eye (O-10).

## 8. Honesty notes you should know

- The 15 % duty rests on secondary sources that all agree (and on MCX June gold rising 6–7 % on 13 May 2026); CBIC's own
  site refuses scripted clients. If CBIC says otherwise, the price stack is wrong by exactly the difference and nothing
  else depends on it.
- The 08:45 fair-open model has three scored mornings; two missed by ₹2.9–3.5k, and the 15 Oct row looks like a stale
  baseline. Every morning's inputs are now kept so a miss can be explained; the chase limit is re-decided at 20 rows.
- "Other reportables" (+95,659 net) is an opaque CFTC bucket; the strip shows all five groups and infers nothing about
  who they are.
- Timestamps matter for every premium: a premium computed from prices seven hours apart is clock error, so the India and
  Shanghai premiums are sampled at the fix minutes and show both timestamps.
- If something looks wrong: a STALE chip names the series and its age; Telegram carries the job failures; the SYS page
  lists every gold job's last run; `docs/RUNBOOK_RESTORE.md` has the gold restore and backfill order.
