# Terminal FINAL — the 9/10 program (13 Nov 2026)

The owner trades from Monday 16 Nov with real money (orders placed MANUALLY at ICICI; this terminal informs and tracks,
it never sends an order). Mission: move every area of `reports/terminal_v2/RATING.md` (6.0 on 4 Nov, 6.5 on 5 Nov,
wave 2 deployed since) to **≥ 9/10**, judged by independent critics on evidence, for ONE user: an individual trading
NSE index options day-to-day (first), stock F&O and MCX gold (next), equity swing (kept). Ease of use and a refined,
calm, polished dark terminal are top priorities. "Better than Bloomberg for this one trader" is the bar.

## §0 Owner decisions (13 Nov, binding)
- **O-F1 Focus order**: index options (incl. expiry day) → everything else follows.
- **O-F2 Look**: refined dark terminal — keep the identity; calmer contrast, better type/spacing/consistency, subtle
  motion, zero clutter. No light theme this round.
- **O-F3 Risk cockpit**: YES, with sensible defaults the owner tunes in settings (daily loss cap, consecutive-loss
  stand-down, trade counter, visible STAND DOWN state). It reads the paper F&O book + alerts; it never blocks anything.
- **O-F4 Orders**: manual at ICICI. PAPER ONLY stands in code. A live-order path is OUT OF SCOPE this round.
- **O-F5 Named complaints (verbatim scope)**: (a) "data-service unreachable" on app open after a reboot — permanent fix
  (watchdog start order) + a calm self-healing boot screen, never a raw error; (b) options-page charts "not clear, can't
  zoom" — every chart on the options/F&O/gold pages gets zoom + pan + crosshair + readable axes + expand view.

## §1 Inherited binding rules (unchanged)
PAPER ONLY enforced in code; trading-rule files frozen; GOLD labelling rules apply terminal-wide (badges
signal-does-not-exist / context / arithmetic / heuristic; no composite scores; context never coloured bullish/bearish;
"describes, does not predict"; one number once per page; store-then-show, point-in-time). Python =
/Users/sudheer/Desktop/jupyter_env/bin/python. Public repo hygiene (no data/, logs, screenshots, secrets; secret-scan
before push; PM commits, builders NEVER run git). No Yahoo callers beside the cached fetcher. Breeze through the budget
ledger only. Restart freeze windows (IST): data-service/master-controller never 07:45–09:20 / 18:30–21:15; ui deploys
avoid 07:55–08:10; lock-safe order stop ui-api → restart data-service (/ready 200) → start ui-api. No new paid data.

## §2 Deploy calendar (this round)
- Fri 13 Nov: wave 0 (assess/spec) + reliability fix; UI deploys allowed 15:35–18:25 or 21:20–24:00.
- Sat–Sun 14–15 Nov: build waves B/C/D/E; deploy + full 43-page audits both engines; backfills Sunday daytime.
- Sun 18:00: full critic re-rating (wave F). Any area < 9 → targeted fix wave Sunday night.
- Mon 16 Nov 08:20: smoke audit (BRF/OMON/OSTR/DERV/XPRY/RSK/GOLD), no deploys 07:30–09:30, owner trades.

## §3 Workstreams
- **W1 Reliability-for-money**: watchdog cold-boot order (data-service before ui-api, lock-safe), boot/degraded UX (calm
  "warming up / catching up" screen with live retry, never a raw connection error), morning self-check strip (feed age,
  broker session, DB writable, jobs on time), catch-up gap closure (FII/DII missing days, COT budget retry, IBJA parser),
  Keychain `_prev` cleanup, restore drill note.
- **W2 Trader's day (index options first)**: OMON chain above the fold w/ Greeks + strike→leg handoff; OSTR with real
  margin + multi-expiry; XPRY cockpit polish (max-pain drift, straddle tracker, PCR intraday); FO paper book ↔ risk
  cockpit; one active-symbol store everywhere; GO coverage; keyboard-first (?, j/k, aliases).
- **W3 Charts engine (named complaint)**: one interactive chart kit for every time-series/payoff on OMON/OSTR/DERV/VOL/
  XPRY/FOBK/CHRT/GOLD/MCXG: wheel+drag zoom, pan, crosshair with values, clear axes/gridlines, expand-to-full-page,
  PNG export. lightweight-charts 4.2.3 (already a dependency) for time-series; the SVG kit gains zoom only where LWC
  does not fit (payoff grids). No new chart dependency.
- **W4 Design polish (refined dark)**: token pass (type scale, spacing grid, calm contrast, one accent discipline),
  component consistency sweep (chips, tables, panels, empty/loading states), strip = the trader's day order, motion
  (150ms ease, no flash), phone compact for BRF/WTCH/OMON-summary/ALRT/MOV, SourceChip (LIVE/age/STALE/OFFLINE) on every
  panel.
- **W5 Risk cockpit (O-F3)**: RSK › DISCIPLINE: daily loss cap vs paper-book realised+MTM, trade counter, consecutive-loss
  stand-down banner (visible on every page header when tripped), scenario strip (spot ±1/±2%, IV ±5, T−1) on the book,
  pre-trade checklist card on OSTR (event today? IV percentile known? max loss typed?). Defaults owner-tunable in settings.
- **W6 Data trust**: freshness chips terminal-wide (reuse gold catalog pattern), wrong-LIVE verification, DATA page
  chip in header, dataset SLO lines, silent-rot alarms.
- **W7 Beyond Bloomberg (well-wisher track)**: Morning Game Plan page + Telegram (08:50: overnight moves, levels, OI
  walls, IV regime vs yesterday, today's events, focus list — all context-badged); Trade journal: paper trades capture
  market context at entry/exit → weekly debrief (P&L split theta/delta/vega, setup win-rate, discipline score); Options
  flow radar (30-min OI delta + vol/OI + IV pump per strike, `context`); Expiry replay simulator (practice on stored
  2-min tapes, score vs actual); What-changed diff on BRF since last look.

## §4 Agent protocol
Waves of builders with DISJOINT file ownership + an adversarial checker per builder + PM (the session) integrating.
Builders never restart services, never run git, never touch frozen files, read this PLAN first. Every wave ends:
5 test suites + tsc + node checks + 43-page audit (both engines, readonly prefs) green before deploy. Critics rate
only the DEPLOYED terminal with evidence (screenshots under ~/.suryadhana_pm_scratch/final_round_20261113/, never the repo).

## §5 Rubric (wave F)
The 8 RATING.md areas, same scale, same owner lens. Target ≥ 9.0 each. A critic may not award 9 without naming the
evidence; a critic must name the single cheapest remaining fix if < 9. Iterate until done — time is not a constraint.

## §6 Round log (what each rating round actually found)
Kept because the pattern is the most useful thing this programme learned: **after the first two rounds, almost every
new defect was in a PM fix or in the gate written to protect it.** A round that only re-measures the product misses
them; the brief has to point the critic at the recent diff.

| Round | Overall | What it found |
|---|---|---|
| F1–F4 | 7.19 → 8.1 | product gaps: charts, cockpit, data trust, design tokens |
| F5 | 8.2 | `CommodityDesk.tsx` (387 lines) imported by nothing — the PM had called the desks live |
| F6 | 8.34 | two tools that lied about their own subject; **four Breeze SDK call sites bypassed the ledger** (`get_quotes` had recorded ZERO calls) |
| F7 | 8.39 | seven defects in code written that morning, incl. a gate that could pass while blind and a TTL fix applied to one file but not its twin |
| F8 | 8.4 | five more: a freeze guard **defeated by the function it guards**; a gate asserting strings that existed only in a comment; the ledger gate blind wherever a comment names the metering helper; the new BRKR chip making the nightly noise its own docstring forbids; and reading the market clock in the browser's timezone |
| F9 | 8.4 (held) | the gate hardened in F6/F7/F8 was scanning **one seventh of the repo** — three unmetered Breeze calls on the busiest live path in data-service, invisible to the budget panel; and F8-04's accepted fix had silently deleted the only pre-open broker alarm |

Rules that came out of it, for whoever runs round N+1:
1. **Point the critic at `git log --oneline -8` and the diff**, not only at the deployed pages.
2. **A new gate must be mutation-tested** — revert the fix and watch the gate fail — or it is prose. F8-02 and two
   of the PM's own checks passed while blind; one pair of cases even sat after the summary line, unable to fail.
3. **Strip comments before a scanner reasons about code.** Three separate gates were fooled by their own
   explanatory comments.
4. **A fix applied in one file must be grepped for its twin** (`QUOTE_TTL_S` survived F6 in a second router).
5. **Anything deciding an Indian market window converts through `Asia/Kolkata` explicitly.** A bare `Date`'s
   weekday and hour are the viewer's, and fixtures built the same wrong way hide it.
6. **Ask what a gate does NOT look at.** Three rounds hardened the ledger gate's logic while never questioning
   its scope; the defect it was built for was living one directory over the whole time. Same for an allowlist:
   enforce the *reason* for each entry, not the entry.
7. **A fix that narrows when something fires must be asked what it stopped firing for.** F8-04 was right that a
   closed Saturday should be quiet, and in being right it took the pre-open hour with it — the one hour where
   the alarm could still change the outcome.
8. **Verify navigation, not just presence.** A check that loaded `?page=` six times never left the default page
   and still "passed", because the thing it looked for lives in the header. The key is `?tab=`.
