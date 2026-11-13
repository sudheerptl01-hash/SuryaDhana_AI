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
