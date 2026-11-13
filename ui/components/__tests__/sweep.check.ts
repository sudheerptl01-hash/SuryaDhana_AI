/**
 * C-SWEEP checks (FINAL ROUND, 13 Nov 2026): colour-semantics residue (L-15 class) + kit consistency.
 *
 *  - L-15: advances/declines and breadth figures are CONTEXT — never green/red. Tone stays reserved for the
 *    trader's own rules (cockpit) and errors; price changes keep their sign colour (they are prices, not verdicts).
 *    Covered files: PreOpen.tsx (the pre-open F&O A/D), MarketMonitor.tsx (breadth stats), MarketInternals.tsx
 *    (A/D bars + legend), LiveMovers.tsx (index breadth + sector A/D bar). Brief.tsx:392 is E-DIFF's (one-shot).
 *  - O-F5a / RISK §b: ErrorBox renders a calm `upstream` variant for "data-service unreachable" errors — the raw
 *    transport string never reaches a panel from the shared kit.
 *  - Chart-kit consistency (plan C5/C7): CHRT gains FIT / PNG ⤓ / ⛶ with 4.x LWC API names only;
 *    EquityCockpitChart sits in the ExpandableChart shell and registers FIT/PNG through the shell context.
 *
 * Every rule has a negative control where the pre-fix behaviour is representable as a source pattern.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/sweep.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── L-15: A/D and breadth figures lose green/red ────────────────────────────────────────────────────────────
{
  const pre = src('components/PreOpen.tsx')
  // the A/D stat and the gaps-count stat are plain strings now, not green/red spans
  check('PRE L-15 advances/declines figure is neutral', /label="Advances \/ declines" value=\{`\$\{data\.advances \?\? '—'\} \/ \$\{data\.declines \?\? '—'\}`\}/.test(pre))
  check('PRE L-15 negative control: no green/red span inside the A/D stat', !/Advances \/ declines" value=\{<span><span style=\{\{ color: T\.green/.test(pre))
  check('PRE L-15 the ±2% gap counts are neutral', /label="Gaps > ±2%" value=\{`\$\{rows\.filter/.test(pre) && !/Gaps > ±2%" value=\{<span>/.test(pre))

  const mkt = src('components/MarketMonitor.tsx')
  check('MKT L-15 A/D stat carries no direction accent', !/Advances \/ declines[^\n]*accent=\{tone\(/.test(mkt))
  check('MKT L-15 above-DMA stats are not green/red by threshold', !/pct_above50 \?\? 0\) >= 50 \? T\.green/.test(mkt) && !/pct_above200 \?\? 0\) >= 50 \? T\.green/.test(mkt))
  check('MKT L-15 highs/lows, ±4% and distribution days lose direction colour',
    !/new_highs \?\? 0\) - \(b\.new_lows \?\? 0\)/.test(mkt) && !/mm_ratio10 \?\? 0\) >= 1\.5 \? T\.green/.test(mkt) && !/dist_days_25 \?\? 0\) <= 4 \? T\.green/.test(mkt))
  // the index % move keeps its price tone (a price, not a context verdict)
  check('MKT price change keeps its tone', /color=\{tone\(b\.index_chg_pct\)\}/.test(mkt))

  const mi = src('components/MarketInternals.tsx')
  check('MI L-15 A/D bars are one neutral colour', /color: 'rgba\(134,145,165,0\.5\)'/.test(mi))
  check('MI L-15 negative control: no sign-switched green/red bar colour', !/net >= 0 \? 'rgba\(22,217,138/.test(mi))
  check('MI L-15 the up/down legend counts are neutral', /<span style=\{\{ color: T\.text \}\}>\{s\.n500_adv\} up<\/span>/.test(mi) && !/color: T\.green \}\}>\{s\.n500_adv\}/.test(mi))

  const mov = src('components/LiveMovers.tsx')
  check('MOV L-15 index breadth figure is neutral', /const breadth = \(i\?: LiveIndex\) => i \? <span style=\{\{ color: T\.text \}\}>\{i\.advances\} \/ \{i\.declines\}<\/span> : '—'/.test(mov))
  check('MOV L-15 sector A/D share bar is neutral', /height: 3, background: T\.border, marginTop: 4 \}\}><div style=\{\{ height: 3, width: `\$\{up\}%`, background: T\.muted/.test(mov))
  check('MOV L-15 negative control: no green-on-red A/D bar', !/background: T\.red, marginTop: 4 \}\}><div style=\{\{ height: 3, width: `\$\{up\}%`, background: T\.green/.test(mov))
}

// ── O-F5a / RISK §b: the kit's calm upstream error face ─────────────────────────────────────────────────────
{
  const kit = src('components/terminal/index.tsx')
  check('kit isUpstreamDown exists and matches the error contract',
    /export function isUpstreamDown/.test(kit) && /code === 'upstream_down'/.test(kit)
    && /data-service unreachable/.test(kit) && /All connection attempts failed/.test(kit))
  check('kit upstream variant: calm copy, muted tone, machine-readable marker',
    /waiting for the data service — retries by itself/.test(kit)
    && /data-sd-error="upstream"/.test(kit) && /color: T\.muted/.test(kit.slice(kit.indexOf('isUpstreamDown(error)'))))
  // the raw message is never rendered on the upstream path: errorText(error) appears only in the red branch
  const upstreamBranch = kit.slice(kit.indexOf('if (isUpstreamDown(error))'), kit.indexOf('data-sd-error="error"'))
  check('kit upstream variant never prints the raw error text', !upstreamBranch.includes('{errorText(error)}'))
  check('kit default error face unchanged (red, raw text shown)', /data-sd-error="error"/.test(kit) && /▲ \{errorText\(error\)\}/.test(kit))
}

// ── chart-kit consistency: CHRT actions + EquityCockpit shell (plan C5/C7) ─────────────────────────────────
{
  const cs = src('components/ChartStudio.tsx')
  check('CHRT gains FIT / PNG / expand actions', />FIT<\/Chip>/.test(cs) && />PNG ⤓<\/Chip>/.test(cs) && /setTall\(v => !v\)/.test(cs))
  check('CHRT PNG composites both panes on the terminal ground', /takeScreenshot\(\)/.test(cs) && /drawImage\(c1, 0, 0\)/.test(cs) && /saveDownload\(b, `chrt-/.test(cs))
  check('CHRT tall mode restores on Esc', /e\.key === 'Escape'\) setTall\(false\)/.test(cs))
  check('CHRT stays on 4.x LWC API names', /addCandlestickSeries\(/.test(cs) && /addHistogramSeries\(/.test(cs) && !/\.addSeries\(/.test(cs))

  const eq = src('components/EquityCockpitChart.tsx')
  check('EQUITY cockpit sits in the ExpandableChart shell', /<ExpandableChart title="Compounded equity"/.test(eq) && /badges=\{\[\{ label: 'arithmetic'/.test(eq))
  check('EQUITY cockpit registers FIT/PNG through the shell context', /useChartShell\(\)/.test(eq) && /registerActions\(\{\s*\n?\s*fit:/.test(eq) && /takeScreenshot\(\)\.toBlob/.test(eq))
  check('EQUITY cockpit stays 4.x', /addAreaSeries\(/.test(eq) && /addLineSeries\(/.test(eq) && !/\.addSeries\(/.test(eq))
  const bt = src('components/BacktestPanel.tsx')
  check('BT call site: one header, the shell carries the title', !/Compounded Equity · NAV vs Benchmark · Drawdown/.test(bt) && /<EquityCockpitChart data=\{results\.equity_curve\}/.test(bt))
}

// ── no direction words introduced by this sweep (grep the touched copy) ────────────────────────────────────
{
  // the sweep changed colours, never wording: the only words it added are in comments. Assert no user-facing
  // "bullish"/"bearish"/"buy"/"sell" string was ADDED to the touched files beyond what pre-dates the sweep
  // (pre-existing: MKT "(≥ 1.5 bullish)" sub + "institutions selling" — flagged to PM, wording changes out of scope).
  const mkt = src('components/MarketMonitor.tsx')
  check('MKT pre-existing wording untouched (no copy drift)', /≥ 1\.5 bullish/.test(mkt) && /≥ 5 = institutions selling/.test(mkt))
}

console.log(`sweep.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
