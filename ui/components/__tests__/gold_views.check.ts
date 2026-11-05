/**
 * GOLD sub-view checks (B4B-UI-VIEWS: POSITIONING · PHYSICAL · MACRO · LEARN and the BRKR auto-login panel; PLAN §e, §f, §g):
 *
 *  1. every gold field the B4B views render (`tip('key')`, `tips('key')`, `tooltips['key']`) has an entry in
 *     ui/lib/gold/tooltips.json, and every PLAN panel id they render (`id="p.hero"` …) has a panel tooltip;
 *  2. the glossary (copied from G-EDU) has no dangling `see_also`, no self reference, and every `<Term t="…">` in the
 *     views resolves to a term;
 *  3. no "bullish" / "bearish" anywhere in the B4B view sources (context metrics never wear a direction word, §f.3) and
 *     no hand-rolled ASCII minus sign site (signed numbers come from goldViewModel with U+2212);
 *  4. the TOTP panel never writes to localStorage / sessionStorage / prefs and its preview request adds no
 *     Authorization header, no credentials flag and no query-string secret;
 *  5. the pure models: who-did wording, the fund-driver label, the OI quadrants, the KGX identity, per-lot sigma, the
 *     supportive/headwind sign rules, the setup-key normaliser (base32 groups, otpauth with %20), the 09:00–15:30 rule,
 *     the .env mode warning, the status chips per source;
 *  6. the LEARN routines mirror CURRICULUM.md Part 9 (each step's key phrase appears there) and the Part 8 rename map
 *     covers every Appendix B row of PLAN.md;
 *  8. wave 1c (the critics' round, reports/gold_program/critics/findings.json): the COT release is the server's label
 *     (C-DATA-6); percentiles name their window and never an ordinal (C-DATA-14, C-BEGINNER-19); the tape never says
 *     'flat' for a missing OI and names multi-session deltas (C-BEGINNER-24, C-DATA-19, C-TRADER-18); roll distances
 *     are days (C-TRADER-28); p.asia asks for no uncatalogued id and prints no placeholder (C-BEGINNER-16, C-DATA-17);
 *     the ladder prints the stored fix-minute premium with every bar's clock (C-TRADER-4, C-BEGINNER-2/-5, C-DATA-11);
 *     Shanghai pairs same-date legs only, with the real gap (C-TRADER-5, C-DATA-10); the IMF table is Moz / t once, a
 *     wrong-unit row excluded (C-TRADER-6, C-BEGINNER-3, C-DATA-5); RBI's price-implied tonnes are gone (C-TRADER-22);
 *     OTC units (C-TRADER-21, C-DATA-20); driver tiles are labelled by the series served, changes in one unit, betas with
 *     units, the KGX note instead of a failing identity (C-DATA-4, C-TRADER-8, C-BEGINNER-14/-20, C-DATA-21); the
 *     glossary pins the start-here dozen, searches aliases, prints long only when it differs and closes on Escape
 *     (C-BEGINNER-10/-11/-17/-22); the routines read as titles (C-BEGINNER-8); the [B]-only filter hides tables, fences
 *     and unmarked pro paragraphs (C-BEGINNER-9); builder notes are [P]-only (C-BEGINNER-23); Western grouping for
 *     contracts / oz / t / $ (C-TRADER-20). Every rule has a negative control.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/gold_views.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../gold/goldViewModel')
type TotpMod = typeof import('../gold/totpModel')
type LearnMod = typeof import('../../lib/gold/learn')
const M = (await import(new URL('../gold/goldViewModel.ts', import.meta.url).href)) as ModelMod
const TM = (await import(new URL('../gold/totpModel.ts', import.meta.url).href)) as TotpMod
const L = (await import(new URL('../../lib/gold/learn.ts', import.meta.url).href)) as LearnMod

const here = path.dirname(new URL(import.meta.url).pathname)
const ui = path.resolve(here, '..', '..')
const repo = path.resolve(ui, '..')
const read = (rel: string) => fs.readFileSync(path.join(ui, rel), 'utf8')

let failures = 0
function check(name: string, ok: boolean, detail?: string): void {
  if (ok) { console.log(`ok   ${name}`); return }
  failures++
  console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`)
}

// ── assets ───────────────────────────────────────────────────────────────────────────────────────
const tooltipsJson = JSON.parse(read('lib/gold/tooltips.json')) as { count: number; panels: string[]; tooltips: Record<string, string>; ui_added: string[] }
const glossaryJson = JSON.parse(read('lib/gold/glossary.json')) as { count: number; terms: { term: string; short: string; long?: string; see_also?: string[]; aliases?: string[] }[] }
const TIPS = tooltipsJson.tooltips
const TERMS = glossaryJson.terms

check('tooltips.json count matches its entries', tooltipsJson.count === Object.keys(TIPS).length, `${tooltipsJson.count} vs ${Object.keys(TIPS).length}`)
check('glossary.json count matches its entries', glossaryJson.count === TERMS.length)
check('every tooltip is one line of ≤ 200 chars', Object.entries(TIPS).every(([, v]) => v.length <= 200 && !v.includes('\n')),
  Object.entries(TIPS).filter(([, v]) => v.length > 200 || v.includes('\n')).map(([k]) => k).join(','))
check('every glossary short is one line of ≤ 200 chars', TERMS.every(t => t.short.length <= 200 && !t.short.includes('\n')))
check('the panels list names exactly the dotted tooltip keys', JSON.stringify([...tooltipsJson.panels].sort()) === JSON.stringify(Object.keys(TIPS).filter(k => /^(h|d|w|m|p|ph|mc|c)\.[a-z0-9.]+$/.test(k)).sort()))
check('no tooltip carries a direction word or sizing advice', !Object.values(TIPS).some(v => /\b(bullish|bearish)\b/i.test(v) || /half size/i.test(v)))

// G-EDU is the source of truth and the SUPERSET (wave 1b): the ui copy equals it key for key; a UI-only key is allowed
// only when `ui_added` declares it (no silent drift in either direction)
const gedu = path.join(repo, 'reports', 'gold_program', 'G-EDU')
if (fs.existsSync(gedu)) {
  const srcT = JSON.parse(fs.readFileSync(path.join(gedu, 'tooltips.json'), 'utf8')) as { tooltips: Record<string, string>; panels: string[] }
  const srcG = JSON.parse(fs.readFileSync(path.join(gedu, 'glossary.json'), 'utf8')) as { terms: { term: string; short: string }[] }
  const diffT = Object.entries(srcT.tooltips).filter(([k, v]) => TIPS[k] !== v).map(([k]) => k)
  check('every G-EDU tooltip is carried verbatim', diffT.length === 0, diffT.slice(0, 8).join(','))
  const extraT = Object.keys(TIPS).filter(k => !(k in srcT.tooltips)).sort()
  const declared = [...(tooltipsJson.ui_added ?? [])].sort()
  check(`the ui tooltips carry no key G-EDU lacks unless ui_added declares it (${extraT.length} extra, ${declared.length} declared)`, JSON.stringify(extraT) === JSON.stringify(declared), extraT.filter(k => !declared.includes(k)).join(','))
  check('the panels list equals G-EDU\'s', JSON.stringify([...tooltipsJson.panels].sort()) === JSON.stringify([...srcT.panels].sort()))
  const have = new Map(TERMS.map(t => [t.term, t.short]))
  const diffG = srcG.terms.filter(t => have.get(t.term) !== t.short).map(t => t.term)
  check('every G-EDU glossary term is carried verbatim', diffG.length === 0, diffG.slice(0, 8).join(','))
  const extraG = TERMS.filter(t => !srcG.terms.some(s => s.term === t.term)).map(t => t.term)
  check('the ui glossary carries no term G-EDU lacks', extraG.length === 0, extraG.join(','))
} else console.log('skip G-EDU comparison (reports/gold_program/G-EDU not on disk)')

// ── 1 + 2: the view sources vs the assets ────────────────────────────────────────────────────────
const VIEW_FILES = ['gold/PositioningView.tsx', 'gold/PhysicalView.tsx', 'gold/MacroView.tsx', 'gold/LearnView.tsx', 'gold/CotWhoIsLong.tsx',
  'gold/OiQuadrantTape.tsx', 'gold/PriceLadder.tsx', 'gold/KgxBar.tsx', 'gold/SeasonalityGrid.tsx', 'gold/FlowCharts.tsx', 'gold/ViewBits.tsx',
  'gold/GlossaryPanel.tsx', 'gold/IciciTotpPanel.tsx']
const sources = Object.fromEntries(VIEW_FILES.map(f => [f, read(path.join('components', f))]))

const tipKeys = new Set<string>()
const panelIds = new Set<string>()
const termRefs = new Set<string>()
for (const [f, src] of Object.entries(sources)) {
  for (const m of src.matchAll(/\btips?\(\s*'([a-z0-9_]+)'\s*\)/g)) tipKeys.add(m[1])
  for (const m of src.matchAll(/\btooltips\[\s*'([a-z0-9_]+)'\s*\]/g)) tipKeys.add(m[1])
  for (const m of src.matchAll(/\bid="((?:p|ph|mc)\.[a-z0-9.]+)"/g)) panelIds.add(m[1])
  for (const m of src.matchAll(/<Term\s+t="([^"]+)"/g)) termRefs.add(m[1])
  check(`${f}: no bullish/bearish wording`, !/\b(bullish|bearish)\b/i.test(src))
  check(`${f}: no hand-rolled ASCII minus sign site`, !/\?\s*'-'\s*:\s*''/.test(src) && !/'-'\s*\+/.test(src))
}
// tooltip keys named in a lookup table (MacroView DRIVER_TIP, PriceLadder tipKey)
for (const m of sources['gold/MacroView.tsx'].matchAll(/:\s*'([a-z0-9_]+)'/g)) if (/^(tips10|dgs2|t10yie|dxy|usdinr|gvz|brent|etf_tonnes)$/.test(m[1])) tipKeys.add(m[1])
for (const k of ['landed', 'usdinr', 'duty_paid_landed', 'duty_rate', 'ibja_999', 'mcx_basis_pct', 'kgx_total', 'kgx_pure_gold', 'kgx_usd_effect', 'kgx_inr_effect']) tipKeys.add(k)
const missingTips = [...tipKeys].filter(k => !(k in TIPS)).sort()
check(`every rendered gold field has a tooltip entry (${tipKeys.size} keys)`, missingTips.length === 0, missingTips.join(','))
const missingPanels = [...panelIds].filter(p => !(p in TIPS) || !tooltipsJson.panels.includes(p)).sort()
check(`every PLAN panel id rendered by the B4B views has a panel tooltip (${panelIds.size} panels)`, missingPanels.length === 0, missingPanels.join(','))
const expectedPanels = ['p.hero', 'p.whois', 'p.history', 'p.crowd', 'p.decomp', 'p.daily.comex', 'p.daily.mcx', 'p.mcx.category', 'p.asia', 'p.drawer',
  'ph.ladder', 'ph.india', 'ph.shanghai', 'ph.etf', 'ph.official', 'ph.otc', 'ph.comex.stocks', 'ph.links',
  'mc.drivers', 'mc.kgx', 'mc.ccy', 'mc.fed', 'mc.calendar', 'mc.move', 'mc.health', 'mc.context']
check('the three views render every PLAN a.6–a.8 panel exactly once', expectedPanels.every(p => panelIds.has(p)) &&
  expectedPanels.every(p => Object.values(sources).join('\n').split(`id="${p}"`).length === 2), expectedPanels.filter(p => !panelIds.has(p)).join(','))

const dangling = L.danglingSeeAlso(TERMS)
check('glossary see_also cross-references resolve', dangling.length === 0, dangling.slice(0, 6).map(d => d.join('→')).join(','))
check('no glossary term references itself', !TERMS.some(t => (t.see_also ?? []).includes(t.term)))
const index = L.indexGlossary(TERMS)
const badTerms = [...termRefs].filter(t => !L.lookupTerm(index, t))
check(`every <Term> in the views resolves to a glossary entry (${termRefs.size} refs)`, badTerms.length === 0, badTerms.join(','))
for (const t of ['GOLDTEN', 'AIDC', 'due date rate', 'EFP price vs volume', 'FND / LTD', 'registered / eligible / pledged', 'Au(T+D) direction', 'KGX rupee leg', 'point-in-time', 'signal', 'settlement by session'])
  check(`glossary carries the term the synthesis asked for: ${t}`, !!L.lookupTerm(index, t))

// ── 3: labelling rules in the model ──────────────────────────────────────────────────────────────
check('crowd gauge wording is "crowdedness, not a signal"', M.CROWD_LABEL.startsWith('crowdedness, not a signal'))
check('the model never emits bull/bear words', !/\b(bullish|bearish)\b/i.test(read('components/gold/goldViewModel.ts')))
check('signed() uses U+2212 and Western grouping for contracts (C-TRADER-20)', M.signed(-2883) === '−2,883' && M.signed(104206) === '+104,206' && M.signed(0) === '0' && M.signed(1356) === '+1,356')
check('num()/usd() use Western grouping; inr() keeps the Indian lakh grouping for rupees only', M.num(-1234.5, 1) === '−1,234.5' && M.num(396810) === '396,810' && M.inr(146079) === '₹1,46,079' && M.usd(-4007.9) === '−$4,007.9')
check('negative control: a rupee amount never prints Western-grouped and a contract count never lakh-grouped', M.inr(146079) !== '₹146,079' && M.num(105562) !== '1,05,562')
check('FlowCharts ticks and hover values use Western grouping (contracts / oz / t / $ — C-TRADER-20); dates stay IST', /toLocaleString\('en-US'/.test(read('components/gold/FlowCharts.tsx')) && !/toLocaleString\('en-IN'/.test(read('components/gold/FlowCharts.tsx')) && /timeZone: 'Asia\/Kolkata'/.test(read('components/gold/FlowCharts.tsx')))
check('signedPct()', M.signedPct(-2.8, 1) === '−2.8%' && M.signedPct(0.4, 1) === '+0.4%' && M.signedPct(null) === '—')

// ── 5: pure models ───────────────────────────────────────────────────────────────────────────────
check('who-did wording: closed / covered', JSON.stringify(M.whoDidWords(-3777, -894)) === JSON.stringify(['closed 3,777 longs', 'covered 894 shorts']))
check('who-did wording: new longs / new shorts', JSON.stringify(M.whoDidWords(3761, 466)) === JSON.stringify(['added 3,761 new longs', 'added 466 new shorts']))
check('who-did wording: zero → no clause', M.whoDidWords(0, null).length === 0)
check('fund-driver label: long liquidation', M.fundDriverLabel(-3777, -894, -2.8) === 'long liquidation')
check('fund-driver label: funds sold into it', M.fundDriverLabel(-3000, 500, 1.2) === 'funds sold into it')
check('fund-driver label: funds bought the dip', M.fundDriverLabel(4000, -500, -1.0) === 'funds bought the dip')
check('fund-driver label: short covering', M.fundDriverLabel(100, -5000, 1.5) === 'short covering')
check('fund-driver label: new shorts', M.fundDriverLabel(-100, 5000, -1.5) === 'new shorts')
check('fund-driver label: null without a price', M.fundDriverLabel(1, 1, null) === null)
// the mirror of services/data-service/gold/driver_rule.py (C-TRADER-3 / C-BEGINNER-1 / C-DATA-15): the critics' week and the tie rules
check('fund-driver label: the critics week (+1,538 / +182 / −1.64 %) is "funds bought the dip", never "new shorts"', M.fundDriverLabel(1538, 182, -1.64) === 'funds bought the dip' && M.fundDriverLabel(-1538, -182, 1.0) === 'funds sold into it')
check('fund-driver label: the bigger bearish leg; a tie goes to the closing leg; new shorts only when they are the bigger leg', M.fundDriverLabel(-100, 100, -1) === 'long liquidation' && M.fundDriverLabel(-30, 100, -1) === 'new shorts' && M.fundDriverLabel(100, 5000, -1) === 'new shorts' && M.fundDriverLabel(100, -100, 1) === 'short covering' && M.fundDriverLabel(-5, 5, 1) === 'funds sold into it' && M.fundDriverLabel(100, 30, 1) === 'new longs')
check('fund-driver label negative control: no word on a flat week or when neither leg moved', M.fundDriverLabel(100, 50, 0) === null && M.fundDriverLabel(0, 0, -1) === null)
check('the view prints the server label first and adds the [B] rule line', /c\?\.driver_label \?\? fundDriverLabel\(/.test(read('components/gold/PositioningView.tsx')) && /the bigger of the two moves; when price fell and the net still rose, funds bought the dip/.test(read('components/gold/PositioningView.tsx')))
check('quadrants', M.quadrantLabel(1, 1) === 'long build-up' && M.quadrantLabel(1, -1) === 'short covering' && M.quadrantLabel(-1, 1) === 'short build-up' && M.quadrantLabel(-1, -1) === 'long unwinding' && M.quadrantLabel(0, 1) === null)
check('contracts → Moz / t / $bn', Math.abs((M.contractsToMoz(104206) ?? 0) - 10.4206) < 1e-6 && Math.abs((M.contractsToTonnes(104206) ?? 0) - 324.12) < 0.05 && Math.abs((M.contractsToUsdBn(104206, 4000) ?? 0) - 41.68) < 0.01)
check('landed ₹/10 g', Math.abs((M.landedInr10g(4000, 95) ?? 0) - (4000 * 95 * 10) / 31.1034768) < 1e-6 && M.landedInr10g(null, 95) === null)
check('KGX identity within 0.02 pp', M.kgxConsistent(-2.18, -2.29, 0.10) && !M.kgxConsistent(-2.18, -2.0, 0.10) && !M.kgxConsistent(null, 1, 1))
check('sigma per lot (GOLD 100 ×, PETAL 0.1 ×)', M.sigmaPerLot(1.5, 146000, 'GOLD') === 219000 && Math.abs((M.sigmaPerLot(1.5, 146000, 'GOLDPETAL') ?? 0) - 219) < 1e-9 && M.sigmaPerLot(1.5, 146000, 'X') === null)
check('driver tags come from the server only (no client re-tagging): supportive / headwind pass, anything else is neutral',
  M.driverTag('supportive') === 'supportive' && M.driverTag('headwind') === 'headwind' && M.driverTag(null) === 'neutral' && M.driverTag(undefined) === 'neutral' && M.driverTag('bullish') === 'neutral')
check('ladder order COMEX → USD/INR → landed → duty → duty-paid → IBJA → MCX', M.orderLadder([{ step: 'mcx', label: '', value: 1 }, { step: 'comex', label: '', value: 1 }, { step: 'ibja_999_pm', label: '', value: 1 }, { step: 'duty_paid', label: '', value: 1 }, { step: 'duty', label: '', value: 1 }, { step: 'landed', label: '', value: 1 }, { step: 'usdinr', label: '', value: 1 }]).map(s => s.step).join(',') === 'comex,usdinr,landed,duty,duty_paid,ibja_999_pm,mcx')
check('settlement label by session, never the file date', M.settlementLabel('2026-10-22') === 'Thu 22 Oct settlement' && M.settlementLabel(null, 'Fri 23 Oct settlement') === 'Fri 23 Oct settlement')
check('istLabel', M.istLabel('2026-10-20') === 'Tue 20 Oct' && M.istLabel('2026-10-23T19:30:00Z', true) === 'Sat 24 Oct 01:00 IST' && M.istLabel('nope') === '—')
check('dateLabel keeps the year for dated constants (the duty)', M.dateLabel('2026-05-13') === 'Wed 13 May 2026' && M.dateLabel(null) === '—')
check('freshLabel', M.freshLabel({ state: 'stale', source: 'Yahoo', age_days: 12, reason: '429' }) === 'STALE · Yahoo · 12 d · 429' && M.freshLabel(null) === 'UNAVAILABLE')

// TOTP model (PLAN §g)
check('setup key: base32 in groups of four with spaces', TM.normaliseSetupKey('jbsw y3dp ehpk 3pxp') === 'JBSWY3DPEHPK3PXP')
check('setup key: otpauth URI with %20', TM.normaliseSetupKey('otpauth://totp/ICICI:user?secret=JBSW%20Y3DP%20EHPK%203PXP&issuer=ICICI&digits=6') === 'JBSWY3DPEHPK3PXP')
check('setup key: padding stripped, dashes allowed', TM.normaliseSetupKey('JBSW-Y3DP-EHPK-3PXP====') === 'JBSWY3DPEHPK3PXP')
check('setup key: garbage → null, never throws', TM.normaliseSetupKey('hello world 1') === null && TM.normaliseSetupKey('') === null && TM.normaliseSetupKey('otpauth://totp/x') === null && TM.normaliseSetupKey('otpauth://totp/x?secret=%E0%A4%A') === null)
check('groupCode', TM.groupCode('482913') === '482 913' && TM.groupCode(null) === '— — —')
check('confirm needs six digits', TM.confirmLooksComplete('482 913') && !TM.confirmLooksComplete('4829'))
check('.env mode warning', TM.envModeWarning('0644') === '.env is 0644 — run chmod 600 .env' && TM.envModeWarning('0600') === null && TM.envModeWarning(420) === '.env is 0644 — run chmod 600 .env' && TM.envModeWarning('-rw-------') === null && TM.envModeWarning(null) === null)
const at = (h: number, m: number) => new Date(Date.UTC(2026, 9, 26, h - 5, m - 30))     // IST = UTC + 5:30
check('force login disabled 09:00–15:30 IST, allowed outside', !!TM.forceLoginDisabledReason(at(10, 0)) && !!TM.forceLoginDisabledReason(at(9, 0)) && !TM.forceLoginDisabledReason(at(15, 30)) && !TM.forceLoginDisabledReason(at(16, 0)) && !TM.forceLoginDisabledReason(at(8, 59)))
const chipText = (s: Parameters<typeof TM.statusChips>[0]) => TM.statusChips(s).map(c => c.text)
check('status chips: keychain', chipText({ configured: true, source: 'keychain' })[0] === 'TOTP CONFIGURED · Keychain')
check('status chips: .env', chipText({ configured: true, source: 'env' })[0] === 'TOTP CONFIGURED · .env')
check('status chips: not set (amber)', TM.statusChips({ configured: false })[0].text === 'TOTP NOT SET' && TM.statusChips({ configured: false })[0].tone === 'amber')
check('status chips: running (cyan, pulse) + mismatch first', (() => { const c = TM.statusChips({ configured: true, source: 'env', login_running: true, block: { totp: true } }); return c[0].text.startsWith('TOTP MISMATCH') && c.some(x => x.text.startsWith('AUTO-LOGIN RUNNING') && x.tone === 'cyan' && x.pulse) })())
check('status chips: unavailable', chipText(null)[0] === 'TOTP STATUS UNAVAILABLE')
check('job line', TM.jobLine({ configured: true, auto_login_enabled: false }) === '08:00 job: disabled' && TM.jobLine(null) === '08:00 job: status unavailable')
check('session watch wording: unsupported names the Telegram fallback', TM.sessionWatchLine('unsupported').includes('/login') && TM.sessionWatchLine('watching', 65).includes('1m05s') && TM.sessionWatchLine('live').startsWith('● LIVE'))
check('keychain one-liner prompts (no secret in argv)', TM.KEYCHAIN_ONE_LINER.endsWith(' -w') && !/ -w\s+\S/.test(TM.KEYCHAIN_ONE_LINER))
check('watch cadence 5 s up to 8 min; preview debounce 400 ms', TM.WATCH_EVERY_MS === 5000 && TM.WATCH_MAX_MS === 480000 && TM.PREVIEW_DEBOUNCE_MS === 400)
check('totpModel and goldViewModel have no imports (plain-node safe)', !/^import /m.test(read('components/gold/totpModel.ts')) && !/^import /m.test(read('components/gold/goldViewModel.ts')))

// ── 4: the TOTP panel's storage and request hygiene ──────────────────────────────────────────────
// code only: the header comments describe the rules and would match their own words
const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
const panelSrc = stripComments(sources['gold/IciciTotpPanel.tsx'] + read('components/gold/totpModel.ts'))
check('TOTP panel never touches localStorage / sessionStorage / IndexedDB / cookies / prefs', !/localStorage|sessionStorage|indexedDB|document\.cookie|usePref|lib\/prefs|savePref|setPref/.test(panelSrc))
check('TOTP preview request adds no Authorization header and no credentials flag', !/Authorization|withCredentials|Bearer|headers\s*:/.test(panelSrc))
check('TOTP calls are relative same-origin paths (no host)', /TOTP_URL = '\/api\/positions\/totp'/.test(panelSrc) && !/https?:\/\/[^'"]*\/api\//.test(panelSrc))
check('the secret never goes in a query string', !/params:\s*\{[^}]*secret/.test(panelSrc) && /http\.post<TotpPreview>\(`\$\{TOTP_URL\}\/preview`, \{ secret \}\)/.test(panelSrc))
check('the secret is cleared from React state after SAVE', /setKey\(''\); setConfirm\(''\); setPreview\(null\)/.test(panelSrc))
check('the key input is type=password with a SHOW toggle and autoComplete off', /type=\{show \? 'text' : 'password'\}/.test(panelSrc) && /autoComplete="off"/.test(panelSrc))
check('the panel never logs', !/console\.(log|info|debug|warn|error)/.test(panelSrc))
check('OPEN ICICI SETTINGS uses openExternal', /openExternal\(ICICI_SETTINGS_URL\)/.test(panelSrc))
check('CHECK SESSION calls the documented scheduler proxy and degrades on 404/405', /REFRESH_PROXY_URL = '\/api\/telemetry\/icici-refresh'/.test(panelSrc) && /httpStatus === 404 \|\| httpStatus === 405/.test(panelSrc))
check('DISABLE AUTO-LOGIN is confirm-gated', /CONFIRM DISABLE/.test(panelSrc) && /http\.delete<TotpClearResult>\(TOTP_URL\)/.test(panelSrc))
check('FORCE LOGIN only when advertised, confirm-gated, 09:00–15:30 rule', /status\?\.force_supported/.test(panelSrc) && /CONFIRM FORCE LOGIN/.test(panelSrc) && /forceLoginDisabledReason\(\)/.test(panelSrc))
const brkr = read('components/PortfolioSummary.tsx')
check('BRKR renders the panel in both layouts', brkr.split('<IciciTotpPanel').length === 3 && /connected=\{false\}/.test(brkr) && /<IciciTotpPanel connected onSessionLive/.test(brkr))
check('BRKR hides the "send /login" sentence while a login runs', /!totp\?\.login_running && <div/.test(brkr))

// ── 6: LEARN assets vs the curriculum and the plan ───────────────────────────────────────────────
const curriculum = path.join(gedu, 'CURRICULUM.md')
if (fs.existsSync(curriculum)) {
  const md = fs.readFileSync(curriculum, 'utf8')
  // the routines are parsed live from Part 9; the document names the panel each step points at
  const live = L.parseRoutines(md)
  check('parseRoutines: three routines (daily / weekly / monthly) with ≥ 4 steps each', live.length === 3 && live.map(r => r.id).join(',') === 'daily,weekly,monthly' && live.every(r => r.steps.length >= 4), live.map(r => `${r.id}:${r.steps.length}`).join(','))
  const livePanels = live.flatMap(r => r.steps.flatMap(s => s.panels ?? []))
  const badLive = livePanels.filter(p => !tooltipsJson.panels.includes(p))
  check(`parseRoutines: every panel id Part 9 names is a PLAN panel with a tooltip (${livePanels.length})`, livePanels.length >= 20 && badLive.length === 0, badLive.join(','))
  check('parseRoutines: every step deep-links to a sub-view and keeps no backticks', live.every(r => r.steps.every(s => !!s.panel && !!s.sub && !s.text.includes('`'))))
  check('parseRoutines: the daily routine carries the evening line', !!live.find(r => r.id === 'daily')?.evening?.startsWith('Evening'))
  const parts = L.parseCurriculum(md)
  check('parseCurriculum: front matter + 9 parts + appendices', parts.filter(p => p.kind === 'front').length === 1 && parts.filter(p => p.kind === 'part').length === 9 && parts.filter(p => p.kind === 'appendix').length >= 3)
  check('parseCurriculum: Part 6 has the COT section', !!parts.find(p => /PART 6/.test(p.title))?.sections.some(s => /Commitments of Traders/.test(s.title)))
  check('parseCurriculum: a # inside a code fence is not a heading', L.parseCurriculum('# T\n\n# PART 1 — a\n\n```\n# not a heading\n```\n\n## 1.1 x\nbody\n').length === 1)
} else console.log('skip CURRICULUM comparison (not on disk)')
check('curriculum corrections are gated on the loaded text (stale 6 % duty wording → the duty notes; fixed text → not)',
  L.activeCorrections('x duty-paid at 6% y').some(c => c.where === '§2.6 duty') && !L.activeCorrections('# PART 1\nthe duty is 15 % since 13 May 2026\n').some(c => c.where === '§2.6 duty') && L.activeCorrections(null).length === L.CURRICULUM_CORRECTIONS.length)
check('Appendix E / F are rendered as LEARN panels, not twice', L.PARTS_RENDERED_AS_PANELS.test('Appendix E — What is not free, and where to click instead') && L.PARTS_RENDERED_AS_PANELS.test('Appendix F — What a Bloomberg gold trader looks at') && !L.PARTS_RENDERED_AS_PANELS.test('Appendix A — Formulas') && /PARTS_RENDERED_AS_PANELS\.test/.test(sources['gold/LearnView.tsx']))
// C-BEGINNER-9: "only [B] copy" keeps [B] + [APP] + headings and drops [P], tables, code fences and the unmarked pro paragraphs
const sampleBody = '### 2.4 x\n\nunmarked formula para\n\n**[B]** b\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n\n**[P]** p\n\n**[APP]** app'
check('filterLayerParagraphs B: keeps [B], [APP] and the heading; drops [P], the table, the fence and the unmarked paragraph',
  L.filterLayerParagraphs(sampleBody, 'B') === '### 2.4 x\n\n**[B]** b\n\n**[APP]** app')
check('filterLayerParagraphs P: drops [B] only (tables, fences, unmarked stay)', L.filterLayerParagraphs(sampleBody, 'P') === '### 2.4 x\n\nunmarked formula para\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n\n**[P]** p\n\n**[APP]** app')
check('filterLayerParagraphs B: a section with no [B] line says so instead of going blank', L.filterLayerParagraphs('unmarked only\n\n**[P]** p', 'B') === L.NO_BEGINNER_COPY && L.filterLayerParagraphs('**[B]** b', 'B') === '**[B]** b')
check('isTableOrFence: tables and fences yes, prose and headings no', L.isTableOrFence('| a | b |\n|---|') && L.isTableOrFence('```py\nx\n```') && !L.isTableOrFence('a | b in prose') && !L.isTableOrFence('## heading'))
check('searchGlossary ranks an exact term first', L.searchGlossary(TERMS, 'swap dealer')[0]?.term === 'swap dealer' && L.searchGlossary(TERMS, '').length === 40 && L.searchGlossary(TERMS, 'zzzz-nothing').length === 0)
// C-BEGINNER-10/-11/-17: the start-here dozen, aliases, long-only-when-different
check('START_HERE is the dozen the critics asked for and every name is a glossary term', L.START_HERE.length === 12 && L.START_HERE.join(',') === 'troy ounce,spot,futures,COMEX,MCX,open interest,COT,managed money,net position,basis,roll,real yield' && L.startHereEntries(index).length === 12)
const withAlias = TERMS.find(t => (t.aliases ?? []).length > 0)
check(`aliases resolve through the index and rank right behind the exact term (${withAlias ? `${withAlias.aliases![0]} → ${withAlias.term}` : 'no alias in the glossary yet'})`,
  !withAlias || (L.lookupTerm(index, withAlias.aliases![0])?.term === withAlias.term && L.searchGlossary(TERMS, withAlias.aliases![0])[0]?.term === withAlias.term))
check('alias search negative control: an alias of nothing finds nothing; an alias never shadows a real term', L.lookupTerm(index, 'zzz-alias') === undefined && L.lookupTerm(L.indexGlossary([{ term: 'a', short: 's', aliases: ['b'] }, { term: 'b', short: 's2' }]), 'b')?.term === 'b')
check('longIfDifferent: null when long repeats short, the long line otherwise', L.longIfDifferent({ term: 'x', short: 'same', long: 'same' }) === null && L.longIfDifferent({ term: 'x', short: 'a', long: 'b' }) === 'b' && L.longIfDifferent({ term: 'x', short: 'a' }) === null)
const gp = sources['gold/GlossaryPanel.tsx']
check('GlossaryPanel pins the start-here dozen while the box is empty, prints aliases, long only when different, Escape closes the dock', /data-glossary-start-here/.test(gp) && /startHereEntries\(INDEX\)/.test(gp) && /longIfDifferent\(e\)/.test(gp) && /data-glossary-aliases/.test(gp) && /ev\.key === 'Escape'/.test(gp) && /setOpen\(false\)/.test(gp))
check('tipFor prefers the server map', L.tipFor({ a: 'server' }, { a: 'bundled', b: 'bundled' }, 'a') === 'server' && L.tipFor(null, { b: 'bundled' }, 'b') === 'bundled' && L.tipFor({}, {}, 'c') === undefined)
const plan = path.join(repo, 'reports', 'gold_program', 'PLAN.md')
if (fs.existsSync(plan)) {
  const appB = fs.readFileSync(plan, 'utf8').split('## Appendix B')[1]?.split('## Appendix C')[0] ?? ''
  const rows = [...appB.matchAll(/(8\.[12]\.\d+) /g)].map(m => m[1])
  const have = new Set(L.PART8_RENAME.map(([from]) => from.split(' ')[0]))
  check(`Part 8 rename map covers every Appendix B row (${rows.length})`, rows.length > 0 && rows.every(r => have.has(r)), rows.filter(r => !have.has(r)).join(','))
}
// C-BEGINNER-8: the routines read as titles; the id travels in title=
check('PANEL_TITLES covers tooltips.json\'s panel list exactly', JSON.stringify(Object.keys(L.PANEL_TITLES).sort()) === JSON.stringify([...tooltipsJson.panels].sort()), Object.keys(L.PANEL_TITLES).filter(k => !tooltipsJson.panels.includes(k)).concat(tooltipsJson.panels.filter(p => !(p in L.PANEL_TITLES))).join(','))
check('every panel title names its sub-view in brackets and is not the id', Object.entries(L.PANEL_TITLES).every(([id, t]) => /\((HEALTH|DAILY|WEEKLY|MONTHLY|POSITIONING|PHYSICAL|MACRO|CONTRACTS)\)$/.test(t) && t !== id && t.length > 8))
const parts = L.describeStep('h.open: fair vs settlement, COMEX part vs rupee part (h.moved); no id here')
check('describeStep replaces panel ids with titles and keeps the id for the chip', parts.length === 4 && parts[0].kind === 'panel' && parts[0].id === 'h.open' && parts[0].title === L.PANEL_TITLES['h.open'] && parts[2].kind === 'panel' && parts[2].id === 'h.moved' && parts[3].kind === 'text' && parts[3].text === '); no id here' && !parts.some(x => x.kind === 'text' && /\bh\.(open|moved)\b/.test(x.text)))
check('describeStep negative control: plain text and a non-panel dotted word stay text', L.describeStep('plain text with p.nope and x.y').every(x => x.kind === 'text') && L.describeStep('').length === 0)
check('shortPanelTitle drops the "(VIEW)" suffix Part 9 already writes beside the id; unknown ids pass through', L.shortPanelTitle('h.verdict') === 'the health verdict' && L.shortPanelTitle('mc.kgx') === 'gold or the dollar?' && L.shortPanelTitle('x.nope') === 'x.nope' && /shortPanelTitle\(part\.id\)/.test(sources['gold/LearnView.tsx']))
check('LearnView renders routine steps through describeStep (no raw ids) and corrections by layer', /describeStep\(s\.text\)/.test(sources['gold/LearnView.tsx']) && /data-panel-ref=\{part\.id\}/.test(sources['gold/LearnView.tsx']) && /activeCorrections\(doc\.data\?\.markdown, layer\)/.test(sources['gold/LearnView.tsx']))
check('the Part 8 panel-id note is [P]-only (C-BEGINNER-23); the duty note shows on both layers', !L.activeCorrections(null, 'B').some(c => c.where === 'Part 8 panel names') && L.activeCorrections(null, 'P').some(c => c.where === 'Part 8 panel names') && L.activeCorrections('duty-paid at 6%', 'B').some(c => c.where === '§2.6 duty'))
check('every bundled routine step targets a real sub-view', L.ROUTINES.every(r => r.steps.every(s => ['health', 'daily', 'weekly', 'monthly', 'positioning', 'physical', 'macro', 'contracts', 'learn'].includes(s.sub))))
const bundledPanels = L.ROUTINES.flatMap(r => r.steps.flatMap(s => s.panels ?? [s.panel ?? '']))
check('every bundled routine step names PLAN panels that have tooltips', L.ROUTINES.length === 3 && bundledPanels.every(p => tooltipsJson.panels.includes(p)), bundledPanels.filter(p => !tooltipsJson.panels.includes(p)).join(','))
check('bundled routine steps link to the sub-view of their first panel', L.ROUTINES.every(r => r.steps.every(s => L.subForPanel(s.panel ?? '') === s.sub)))
check('parseRoutines on a document without Part 9 → []', L.parseRoutines('# T\n\n# PART 1 — a\n').length === 0)
check('parseRoutines reads a minimal Part 9', JSON.stringify(L.parseRoutines('# PART 9 — r\n\n**Daily (x)**\n1. `h.open`: a\n   b `mc.move`\n2. plain\nEvening (e): `d.24h` z\n\n**Weekly (y)**\n1. `p.hero` q\n\n# Appendix A\n').map(r => [r.id, r.when, r.steps.map(s => [s.sub, s.panel, s.text, s.panels]), r.evening]))
  === JSON.stringify([['daily', 'x', [['health', 'h.open', 'h.open: a b mc.move', ['h.open', 'mc.move']], ['health', undefined, 'plain', []]], 'Evening (e): d.24h z'], ['weekly', 'y', [['positioning', 'p.hero', 'p.hero q', ['p.hero']]], undefined]]))
check('NOT_FREE never lists a host the stack may fetch as a feed', L.NOT_FREE.every(l => /lbma|cmegroup|mcxindia|kitco|bloomberg|reuters/.test(l.url)))

// ── 7 (wave 1b): contract conformance — the views read what routers/gold.py emits, declare ids the seed has,
//    never invent a freshness state or an as-of, and ask the routes for what they allow ──────────────────────────────
const VIEWS3 = ['gold/PositioningView.tsx', 'gold/PhysicalView.tsx', 'gold/MacroView.tsx'] as const
const view3 = Object.fromEntries(VIEWS3.map(f => [f, stripComments(sources[f])])) as Record<(typeof VIEWS3)[number], string>
const goldPy = path.join(repo, 'services', 'ui-api', 'routers', 'gold.py')
const seedPy = path.join(repo, 'services', 'data-service', 'gold', 'catalog_seed.py')

// 7a the history range never exceeds the route's bound (`weeks: int = Query(52, ge=1, le=2000)`)
const routeMax = fs.existsSync(goldPy) ? Number(/weeks:\s*int\s*=\s*Query\(\s*\d+\s*,\s*ge=\d+\s*,\s*le=(\d+)\)/.exec(fs.readFileSync(goldPy, 'utf8'))?.[1] ?? NaN) : NaN
check('COT_RANGES: every range ≤ the /cot route bound and "all" asks for exactly the maximum', Object.values(M.COT_RANGES).every(w => w <= M.COT_WEEKS_MAX) && M.COT_RANGES.all === M.COT_WEEKS_MAX && (Number.isNaN(routeMax) || routeMax === M.COT_WEEKS_MAX), `route le=${routeMax}, model max=${M.COT_WEEKS_MAX}`)
check('PositioningView reads COT_RANGES from the model (no local 2600)', /COT_RANGES\[range\]/.test(view3['gold/PositioningView.tsx']) && !/2600/.test(view3['gold/PositioningView.tsx']))
check('cotRangeLabel prints the real range from the rows that came back', M.cotRangeLabel(52, '2025-10-28') === '52 reports · since Tue 28 Oct 2025' && M.cotRangeLabel(1, null) === '1 report' && M.cotRangeLabel(0, '2025-01-01') === 'no reports')

// 7b no fabricated freshness: every lag chip is the server's block (serverFreshness) or null; no `{ state: 'delayed' … }` literal
for (const f of VIEWS3) {
  const src = view3[f]
  const freshSites = [...src.matchAll(/fresh=\{([^}]*(?:\{[^}]*\}[^}]*)*)\}/g)].map(m => m[1])
  // a site is honest when it is `null`, calls serverFreshness(...) itself, or names a const / helper whose definition does
  const honestNames = new Set([...src.matchAll(/const (\w+) = [^\n]*serverFreshness\(/g)].map(m => m[1]))
  const honest = (s: string) => s.trim() === 'null' || /serverFreshness\(/.test(s) || honestNames.has(/^\s*(\w+)/.exec(s)?.[1] ?? '')
  check(`${f}: every fresh= site is serverFreshness(...) or null (${freshSites.length} sites)`, freshSites.length > 0 && freshSites.every(honest), freshSites.filter(s => !honest(s)).join(' | '))
  check(`${f}: negative control — a literal block would be caught`, !honest('{ state: \'delayed\', source: \'stored\' }') && !honest('fabricated') && honest('null'))
  check(`${f}: no client-invented freshness state`, !/state:\s*'(delayed|live|stale|unavailable)'/.test(src))
  check(`${f}: the request clock is never an as-of (no istLabel(<payload>.as_of))`, !/istLabel\(\s*[a-z]+\??\.as_of\s*\)/.test(src) && !/dateOnly=\{asOfDay\}/.test(src))
}
check('serverFreshness passes the server block through and returns null for nothing / a shapeless object', M.serverFreshness({ state: 'stale', source: 'CFTC', as_of: '2026-10-20' })?.state === 'stale' && M.serverFreshness(null) === null && M.serverFreshness(undefined) === null && M.serverFreshness({} as never) === null && M.serverFreshness({ state: '' } as never) === null)
check('latestDate picks the newest ISO date and skips junk', M.latestDate(['2026-10-20', null, '2026-10-23T19:30:00Z', 'nope', '2026-09-01']) === '2026-10-23' && M.latestDate([]) === null && M.latestDate([undefined, 'x']) === null)
check('thresholdText prints HEALTH_RULES objects as text (React #31 on LEARN, wave 1b) and keeps numbers / strings', M.thresholdText({ weak_pct: -2.0, strong_pct: 2.0, flat_pct: 0.5 }) === 'weak_pct −2 · strong_pct 2 · flat_pct 0.5' && M.thresholdText(5) === '5' && M.thresholdText(0.4) === '0.4' && M.thresholdText(-1234.567) === '−1,234.57' && M.thresholdText('≥ 9 d') === '≥ 9 d' && M.thresholdText(null) === '—' && M.thresholdText([1, 'a']) === '1 / a')
check('LEARN renders every rule value / threshold through thresholdText (no raw object child)', /thresholdText\(c\.threshold\)/.test(sources['gold/LearnView.tsx']) && /thresholdText\(c\.value\)/.test(sources['gold/LearnView.tsx']) && !/\{c\.threshold \?\? '—'\}/.test(sources['gold/LearnView.tsx']))
check('monthLabel', M.monthLabel('2026-09') === 'Sep 2026' && M.monthLabel('2026-09-30') === 'Sep 2026' && M.monthLabel('2026-13') === '—' && M.monthLabel(null) === '—')
// MacroView: every dateOnly is one of the block dates (never the payload clock)
const macroDateSites = [...view3['gold/MacroView.tsx'].matchAll(/dateOnly=\{([a-zA-Z]+)\}/g)].map(m => m[1])
check('MacroView: every panel as-of is a block date (drivers / gold / fed / move / calendar / context)', macroDateSites.length === 8 && macroDateSites.every(d => ['driversDate', 'goldDate', 'fedDate', 'moveDate', 'calDate', 'ctxDate'].includes(d)), macroDateSites.join(','))
check('MacroView: the calendar (a schedule) wears no lag chip', !/id="mc\.calendar"[^>]*fresh=/.test(view3['gold/MacroView.tsx']))

// 7c the field paths the views read exist in gold.py's builders (the four shape mismatches of wave 1 can not come back)
if (fs.existsSync(goldPy)) {
  const py = fs.readFileSync(goldPy, 'utf8')
  const pyFreshKeys = (fnName: string) => {
    const body = py.split(`def ${fnName}(`)[1]?.split(/\n@router|\ndef /)[0] ?? ''
    const block = body.split('"freshness": {')[1]?.split('\n        },')[0] ?? ''
    return new Set([...block.matchAll(/"([a-z_]+)": freshness\(/g)].map(m => m[1]))
  }
  const flowsKeys = pyFreshKeys('build_flows'), macroKeys = pyFreshKeys('build_macro')
  const physUsed = [...view3['gold/PhysicalView.tsx'].matchAll(/\bfr\('([a-z_]+)'\)/g)].map(m => m[1])
  const macroUsed = [...view3['gold/MacroView.tsx'].matchAll(/\bfb\('([a-z_]+)'\)/g)].map(m => m[1])
  check(`PhysicalView reads only freshness keys build_flows emits (${[...flowsKeys].join('/')})`, flowsKeys.size >= 5 && physUsed.length > 0 && physUsed.every(k => flowsKeys.has(k)), physUsed.filter(k => !flowsKeys.has(k)).join(','))
  check(`MacroView reads only freshness keys build_macro emits (${[...macroKeys].join('/')})`, macroKeys.size === 3 && macroUsed.length > 0 && macroUsed.every(k => macroKeys.has(k)), macroUsed.filter(k => !macroKeys.has(k)).join(','))
  check('negative control: the freshness-key parser sees nothing for a builder without a block', pyFreshKeys('build_contracts').size === 0 && pyFreshKeys('no_such_builder').size === 0)
  const premiumsBody = py.split('def build_premiums(')[1]?.split('\n@router')[0] ?? ''
  check('premiums freshness is nested (india / shanghai) in gold.py and read nested by PhysicalView', (premiumsBody.match(/"freshness": freshness\(/g) ?? []).length === 2 && !/"freshness": \{/.test(premiumsBody) && /serverFreshness\(india\?\.freshness\)/.test(view3['gold/PhysicalView.tsx']) && /serverFreshness\(sh\?\.freshness\)/.test(view3['gold/PhysicalView.tsx']) && !/p\.freshness/.test(view3['gold/PhysicalView.tsx']))
  check('drawer.concentration keys match gold.py (gross4_long … net8_short, no conc_ prefix)', M.CONCENTRATION_KEYS.every(k => py.includes(`"${k}",`)) && !/conc_net4_long/.test(view3['gold/PositioningView.tsx']) && /concentrationLines\(/.test(view3['gold/PositioningView.tsx']))
  check('WGC India tonnes read from the top-level wgc_india_holdings_t gold.py emits (no India region row)', py.includes('"wgc_india_holdings_t":') && /f\.wgc_india_holdings_t/.test(view3['gold/PhysicalView.tsx']) && !/\/india\/i\.test\(w\.region\)/.test(view3['gold/PhysicalView.tsx']))
  check('the /macro calendar rows are {date, title}: gold.py emits them and MacroView reads them', /"date": d\.isoformat\(\)/.test(py) && /"title": e\.get\("name"\)/.test(py) && /r\.title \?\? r\.name/.test(view3['gold/MacroView.tsx']) && /r\.date \?\? r\.event_date/.test(view3['gold/MacroView.tsx']))
  check('the MCX daily route takes ?family= and labels rows with it', /family: str = Query\("GOLD"\)/.test(py) && /"symbol_or_product": family\.upper\(\)/.test(py))
}
check('concentrationLines reads the server keys and prints "—" for a missing block', M.concentrationLines({ net4_long: 12.3, net8_long: 20.1, net4_short: 30.5, net8_short: 41, gross4_long: 15, gross8_long: 25, gross4_short: 35, gross8_short: 45 }).net === 'L 12.3% / 20.1% · S 30.5% / 41.0%' && M.concentrationLines({ gross4_long: 15 }).gross.startsWith('L 15.0% / —') && M.concentrationLines(null).net === 'L — / — · S — / —' && M.concentrationLines({ conc_net4_long: 1 }).net === 'L — / — · S — / —')

// 7d the MCX ladder: the selected family travels with the request; no silent fall-back to another family's rows
const posSrc = view3['gold/PositioningView.tsx']
check('p.daily.mcx: the selected family is passed to the request and the load re-runs when it changes', /getGoldPositioningDaily\('MCX', 60, fam\), \[fam\]/.test(posSrc))
check('api.ts forwards the family on MCX requests (API_CONTRACT §2.6)', /family\?: Family \| string \| null\) =>/.test(read('lib/gold/api.ts')) && /family: exchange === 'MCX' \? family : undefined/.test(read('lib/gold/api.ts')))
check('p.daily.mcx: rows are the family\'s own; a server answer for another family is said, never shown', !/exact\.length \? exact : all/.test(posSrc) && /data-mcx-family-mismatch/.test(posSrc) && /served !== fam/.test(posSrc))
check('p.daily.mcx: no rows → "no rows for <family>" (not another family\'s)', /data-mcx-no-rows/.test(posSrc))

// 7e catalog ids: every id a panel declares exists in B1's seed; the literal badge equals the seed's for the primary id
if (fs.existsSync(seedPy)) {
  const seed = fs.readFileSync(seedPy, 'utf8')
  const listOf = (name: string) => [...(new RegExp(`${name} = \\(([^)]*)\\)`).exec(seed)?.[1] ?? '').matchAll(/"([A-Z0-9]+)"/g)].map(m => m[1])
  const imfCountries = listOf('IMF_COUNTRIES'), ibjaPurities = listOf('IBJA_PURITIES')
  const seedHas = (id: string): boolean => {
    if (seed.includes(`"${id}"`)) return true
    let m = /^IMF_GOLD_(OZ|USD)_([A-Z]{3})$/.exec(id)
    if (m) return imfCountries.includes(m[2]) && seed.includes(`f"IMF_GOLD_${m[1]}_{iso}"`)
    m = /^IBJA_(\d{3})_(AM|PM)$/.exec(id)
    if (m) return ibjaPurities.includes(m[1]) && seed.includes('f"IBJA_{p}_{fix}"')
    return false
  }
  const seedBadge = (id: string): string | null => {
    const row = new RegExp(`_row\\("${id}"[\\s\\S]*?"(?:PUBLISH-CORE|PUBLISH-CONTEXT|LINK-ONLY|DO-NOT-PUBLISH)",\\s*"(context|arithmetic|signal|heuristic)"`).exec(seed)
    if (row) return row[1]
    const entry = new RegExp(`"${id}": \\(([\\s\\S]*?)\\),?\\n`).exec(seed)       // a dict entry; names may hold "(…)"
    if (entry) return [...entry[1].matchAll(/"(context|arithmetic|signal|heuristic)"/g)].map(x => x[1]).pop() ?? null
    if (/^IMF_GOLD_OZ_/.test(id)) return /f"IMF_GOLD_OZ_\{iso\}"[\s\S]*?"PUBLISH-CORE", "(context|arithmetic)"/.exec(seed)?.[1] ?? null
    if (/^IBJA_\d{3}_(AM|PM)$/.test(id)) return /f"IBJA_\{p\}_\{fix\}"[\s\S]*?"PUBLISH-CORE", "(context|arithmetic)"/.exec(seed)?.[1] ?? null
    return null
  }
  check('seed parser: positive and negative controls', seedHas('COT_DISAGG_F') && seedHas('IMF_GOLD_OZ_IND') && seedHas('IBJA_999_PM') && !seedHas('COT_MM_NET') && !seedHas('IMF_GOLD_OZ_XXX') && !seedHas('IBJA_123_PM') && !seedHas('FED_PATH')
    && seedBadge('MCX_CURVE_ICICI') === 'arithmetic' && seedBadge('COT_DISAGG_F') === 'context' && seedBadge('KGX_PURE_GOLD_PCT') === 'arithmetic' && seedBadge('FRED_DFII10') === 'context' && seedBadge('IMF_GOLD_OZ_IND') === 'context' && seedBadge('NOPE') === null)
  const declared: { file: string; id: string; series: string[]; about: string | null; badge: string | null }[] = []
  for (const f of VIEWS3) {
    for (const m of view3[f].matchAll(/<GPanel\s+id="([a-z.]+)"([\s\S]*?)>/g)) {
      const attrs = m[2]
      const series = [...(/series=\{\[([^\]]*)\]\}/.exec(attrs)?.[1] ?? '').matchAll(/'([A-Z0-9_]+)'|\b(COT_ID)\b/g)].map(x => (x[1] ?? 'COT_DISAGG_F'))
      declared.push({ file: f, id: m[1], series, about: /about="([A-Z0-9_]+)"/.exec(attrs)?.[1] ?? null, badge: /badge="([a-z]+)"/.exec(attrs)?.[1] ?? null })
    }
  }
  check(`every B4B panel was parsed (${declared.length})`, declared.length === 26, declared.map(d => d.id).join(','))
  const unknown = declared.flatMap(d => [...d.series, ...(d.about ? [d.about] : [])].filter(id => !seedHas(id)).map(id => `${d.id}:${id}`))
  check('every catalog id the B4B panels declare exists in catalog_seed.py', unknown.length === 0, unknown.join(','))
  const badgeMismatch = declared.filter(d => d.series[0] && d.badge && seedBadge(d.series[0]) && seedBadge(d.series[0]) !== d.badge).map(d => `${d.id}:${d.badge}≠${seedBadge(d.series[0])}`)
  check('the literal badge of every panel equals the seed badge of its primary series (the catalog chip wins once loaded)', badgeMismatch.length === 0, badgeMismatch.join(','))
  const noBadgeInfo = declared.filter(d => d.series[0] && d.badge && !seedBadge(d.series[0])).map(d => `${d.id}:${d.series[0]}`)
  check('every primary series resolves to a seed badge (the parser knows every row form the seed uses)', noBadgeInfo.length === 0, noBadgeInfo.join(','))
  check('the COT panels hang off the COT catalog row first (not the Yahoo price series)', declared.filter(d => /^p\.(hero|whois|history|crowd|decomp|drawer)$/.test(d.id)).every(d => d.series[0] === 'COT_DISAGG_F'))
  check('LINK-ONLY panels gate on nothing and name their catalog row through `about` (p.mcx.category, ph.comex.stocks)', declared.filter(d => d.id === 'p.mcx.category' || d.id === 'ph.comex.stocks').every(d => d.series.length === 0 && !!d.about && seedHas(d.about)))
  check('GPanel: the catalog badge wins over the literal; an absent row is "no verdict", not a pass', /const shownBadge = primary\?\.badge \?\? badge/.test(sources['gold/ViewBits.tsx']) && /publishGate\(catalog, s\) !== 'ok'/.test(sources['gold/ViewBits.tsx']))
} else console.log('skip catalog seed comparison (services/data-service/gold/catalog_seed.py not on disk)')

// 7f drivers: the server's tag and rule; the client re-tags nothing
check('MacroView renders the server tag only (driverTag(d.tag)) and the server rule first', /driverTag\(d\.tag\)/.test(view3['gold/MacroView.tsx']) && !/driverTag\([^)]*d1/.test(view3['gold/MacroView.tsx']) && /d\.rule \?\? DRIVER_RULES\[d\.key\]/.test(view3['gold/MacroView.tsx']))
check('DRIVER_RULES is text only: no gld_t / brent / breakeven rule drives a tag (driverTag takes one argument)', M.driverTag.length === 1 && typeof M.DRIVER_RULES.gld_t === 'string')
// 7g repetition and links (PLAN §f.6, a.8)
check('ph.india no longer repeats the ladder\'s premium / basis of the day', !/IBJA premium now|MCX basis now/.test(view3['gold/PhysicalView.tsx']))
check('mc.ccy: the INR row links to MCXG (the desk page) and to CONTRACTS', /goToPage\('mcxgold'\)/.test(view3['gold/MacroView.tsx']) && /onNavigate\('contracts'\)/.test(view3['gold/MacroView.tsx']))
check('the /macro calendar type is local to MacroView until types.ts carries {date, title}', /type MacroCalRow/.test(sources['gold/MacroView.tsx']))

// ── 8 (wave 1c): the critics' findings, each with a negative control ─────────────────────────────
// C-DATA-6: the release is the server's label, never a converted release_at
check('p.hero prints latest.release_ist and never istLabel(release_at)', /c\.latest\?\.release_ist/.test(posSrc) && !/istLabel\([^)]*release_at/.test(posSrc))
// C-DATA-14 / C-BEGINNER-19: percentiles name their window, never an ordinal
check('percentileLabel: the window the server computed it over', M.percentileLabel(26.2, 160) === 'percentile 26 of the last 160 reports (≈ 3 y)' && M.percentileLabel(50, 1040) === 'all-history percentile 50 (1,040 reports)' && M.percentileLabel(13.8, null) === 'percentile 14' && M.percentileLabel(null, 160) === '—' && M.percentileLabel(26, 160, '3-y window') === 'percentile 26 · 3-y window')
check('percentileLabel negative control: 160 reports is never "all-history"', !M.percentileLabel(26, 160).includes('all-history') && M.ALL_HISTORY_MIN_REPORTS > 160)
check('no ordinal percentile ("93th pct") survives in the B4B views', !VIEWS3.some(f => /\dth pct|th pct\b/.test(view3[f])))
// C-BEGINNER-24 / C-DATA-19 / C-TRADER-18: the tape
check('sessionsBetween counts weekdays', M.sessionsBetween('2026-10-29', '2026-11-03') === 3 && M.sessionsBetween('2026-11-02', '2026-11-03') === 1 && M.sessionsBetween('2026-10-30', '2026-11-02') === 1 && M.sessionsBetween('2026-11-03', '2026-11-03') === null && M.sessionsBetween('x', '2026-11-03') === null)
const tr = (row: Parameters<typeof M.tapeReadout>[0], prev: string | null) => M.tapeReadout(row, prev, 'no OI yet (CME T+1)')
check('tapeReadout: a missing OI is never "flat"', tr({ trade_date: '2026-11-03', dprice_pct: -0.74, doi: null, label: null }, '2026-11-02').word === 'no OI for this session' && tr({ trade_date: '2026-11-03', dprice_pct: -0.74, doi: null, label: null }, '2026-11-02').note === 'no OI yet (CME T+1)')
check('tapeReadout: flat only with two known deltas; the server label wins', tr({ trade_date: '2026-11-03', dprice_pct: 0, doi: 100, label: null }, '2026-11-02').word === 'flat' && tr({ trade_date: '2026-11-03', dprice_pct: -2.45, doi: 863, label: 'short build-up' }, '2026-11-02').word === 'short build-up')
check('tapeReadout: a delta spanning missing sessions is named', tr({ trade_date: '2026-11-03', dprice_pct: -2.45, doi: 863, label: 'short build-up' }, '2026-10-29').note === 'Δ over 3 sessions (rows missing between)' && tr({ trade_date: '2026-11-03', dprice_pct: -2.45, doi: 863, label: 'short build-up' }, '2026-11-02').note === null)
check('OiQuadrantTape renders through tapeReadout and takes the missing-OI reason from the caller', /tapeReadout\(/.test(sources['gold/OiQuadrantTape.tsx']) && !/\?\? 'flat'/.test(sources['gold/OiQuadrantTape.tsx']) && /missingOiNote=\{CME_OI_LAG\}/.test(posSrc) && /missingOiNote=\{MCX_OI_LAG\}/.test(posSrc))
// C-TRADER-28 / C-TRADER-13: calendar days, as the server counts them
check('roll distances print as days, never sessions', /days to FND/.test(posSrc) && /days to tender/.test(posSrc) && !/sessions to (FND|tender)/.test(posSrc))
// C-BEGINNER-16 / C-DATA-17: p.asia — no uncatalogued id, no placeholder row; the release build hides the panel until ui-api serves gold_asia_daily
check('p.asia requests no uncatalogued series id and prints no "no verdict" placeholder', !/SGE_AUTD|SHFE_AU_FRONT_OI|getGoldSeries/.test(posSrc) && !/not published/.test(posSrc) && /data-asia-pending/.test(posSrc))
check('p.asia is gated out of the release build (PLAN §f.2) and the gate reads NODE_ENV', /const RELEASE_BUILD = process\.env\.NODE_ENV === 'production'/.test(posSrc) && /\{!RELEASE_BUILD && <GPanel id="p\.asia"/.test(posSrc))
// C-DATA-14 both server shapes: the old /cot (percentile_all over the fetched window, no label) and the new one (percentile_all = data-service all-history or null; percentile_window + window_label)
check('p.crowd reads percentile_all with the server label, else percentile_window with window_label; OI reads pct_rank_label', /crowdPercentile\(c\?\.crowd, nReports\)/.test(posSrc) && /serverStr\(crowd, 'window_label'\)/.test(posSrc) && /serverNum\(crowd, 'percentile_window'\)/.test(posSrc) && /serverStr\(c\?\.open_interest, 'pct_rank_label'\)/.test(posSrc))
// C-DATA-19: the 20-d volume average needs sessions
check('p.daily.comex: the volume ratio waits for VOL_AVG_MIN_SESSIONS sessions (never 1.00× from one row)', /const VOL_AVG_MIN_SESSIONS = 5/.test(posSrc) && /vol20\.length >= VOL_AVG_MIN_SESSIONS/.test(posSrc) && /data-vol-ratio/.test(posSrc) && !/vol20\.length \? vol20\.reduce/.test(posSrc))
// C-TRADER-4 / C-BEGINNER-2 / C-BEGINNER-5 / C-DATA-11: the ladder
const ladderSrc = sources['gold/PriceLadder.tsx'], physSrc = view3['gold/PhysicalView.tsx']
check('ladderClock: live legs are "now", IBJA a fix, MCX a settlement, duty a constant', M.ladderClock({ step: 'comex', label: '', value: 1, ts: '2026-11-05T00:06:48+05:30' }) === 'now' && M.ladderClock({ step: 'ibja', label: '', value: 1, ts: '2026-11-03' }) === 'fix' && M.ladderClock({ step: 'mcx', label: '', value: 1, ts: 'Tue 03 Nov settlement' }) === 'settlement' && M.ladderClock({ step: 'duty', label: '', value: 15, ts: '2026-05-13' }) === 'constant' && M.ladderClock({ step: 'landed', label: '', value: 1, ts: '2026-11-03' }) === 'unknown')
check('ladderTsLabel prints the clock', M.ladderTsLabel({ step: 'comex', label: '', value: 1, ts: '2026-11-04T18:36:48Z' }) === 'now · Thu 05 Nov 00:06 IST' && M.ladderTsLabel({ step: 'ibja', label: '', value: 1, ts: '2026-11-03' }) === 'PM fix · Tue 03 Nov' && M.ladderTsLabel({ step: 'mcx', label: '', value: 1, ts: 'Tue 03 Nov settlement' }) === 'Tue 03 Nov settlement' && M.ladderTsLabel({ step: 'mcx', label: '', value: 1, ts: '2026-11-03' }) === 'Tue 03 Nov settlement')
const hist = [{ report_date: '2026-11-02', premium_pct: -1.664 }, { report_date: '2026-11-03', premium_pct: -0.71 }]
check('storedPremiumOn: the fix-minute row for the IBJA date, null when absent', M.storedPremiumOn(hist, '2026-11-03')?.value === -0.71 && M.storedPremiumOn(hist, '2026-11-04') === null && M.storedPremiumOn(hist, null) === null && M.storedPremiumOn(null, '2026-11-03') === null)
check('the ladder prints the STORED premium (never india.premium_pct, a cross-clock division) and labels the basis clock', /premium=\{premiumStored\}/.test(physSrc) && !/premiumPct=\{india\.premium_pct\}/.test(physSrc) && /storedPremiumOn\(india\?\.history/.test(physSrc) && /basisClock=\{basisClock\}/.test(physSrc) && /ladderTsLabel\(s\)/.test(ladderSrc) && /data-ladder-clock-line/.test(ladderSrc) && /do not divide across clocks/.test(ladderSrc))
// C-TRADER-5 / C-DATA-10: Shanghai
check('ukIsBst: GMT from the last Sunday of October, BST from the last Sunday of March', M.ukIsBst('2026-10-24') && !M.ukIsBst('2026-10-26') && M.ukIsBst('2026-03-29') && !M.ukIsBst('2026-03-28') && !M.ukIsBst('x'))
const pr = M.shanghaiPairing('2026-11-04', '2026-11-03', false)
check('shanghaiPairing: cross-date pair is not a premium; the real gap is 8 h 45 min on GMT, 7 h 45 min in BST, none for COMEX', !pr.sameDate && /8 h 45 min/.test(pr.gap) && M.shanghaiPairing('2026-07-01', '2026-07-01', false).sameDate && /7 h 45 min/.test(M.shanghaiPairing('2026-07-01', '2026-07-01', false).gap) && /no clock gap/.test(M.shanghaiPairing('2026-11-04', '2026-11-04T06:15:00Z', true).gap) && !M.shanghaiPairing(null, '2026-11-03', false).sameDate)
check('ph.shanghai prints the premium only for a same-date pair and says what it waits for otherwise; the "7-hour" wording is gone and the server\'s old clock_note is filtered', /pairing\.sameDate/.test(physSrc) && /data-shanghai-premium="stored"/.test(physSrc) && /awaiting the/.test(physSrc) && !/7-hour gap/.test(physSrc) && !/7 hours apart/.test(physSrc) && /!\/7-hour\/\.test\(sh\.clock_note\)/.test(physSrc))
// C-TRADER-6 / C-BEGINNER-3 / C-DATA-5 / C-TRADER-22: the official sector
const usa = M.normaliseOfficial({ country: 'USA', month: '2026-07', oz_mn: 261499000, chg_oz_mn: 0 })
const chn = M.normaliseOfficial({ country: 'CHN', month: '2026-09', oz_mn: 77470000, chg_oz_mn: 740000 })
const bra = M.normaliseOfficial({ country: 'BRA', month: '2026-09', oz_mn: 5544278722.99791, chg_oz_mn: -0.0018 })
const ok1 = M.normaliseOfficial({ country: 'IND', month: '2026-08', oz_mn: 28.309311, chg_oz_mn: 0 })
check('normaliseOfficial: raw ounces → Moz and tonnes (USA 261.5 Moz = 8,133 t; CHN +0.74 Moz m/m)', usa.scaled && Math.abs((usa.oz_mn ?? 0) - 261.499) < 1e-6 && Math.abs((usa.tonnes ?? 0) - 8133.5) < 0.1 && Math.abs((chn.chg_oz_mn ?? 0) - 0.74) < 1e-9 && !usa.excluded)
check('normaliseOfficial negative control: a row already in Moz is not rescaled and not excluded', !ok1.scaled && Math.abs((ok1.oz_mn ?? 0) - 28.309311) < 1e-9 && Math.abs((ok1.tonnes ?? 0) - 880.5) < 0.1 && !ok1.excluded)
check('normaliseOfficial: the off-scale BRA row is excluded with the reason', !!bra.excluded && /unit error at the source/.test(bra.excluded ?? '') && (bra.oz_mn ?? 0) > M.OFFICIAL_MOZ_MAX)
const tbl = M.officialTable([bra, chn, usa, ok1].map(r => ({ country: r.country, month: r.month, oz_mn: r.country === 'BRA' ? 5544278722.99791 : r.country === 'USA' ? 261499000 : r.country === 'CHN' ? 77470000 : 28.309311 })))
check('officialTable: USA above CHN above IND, BRA excluded (never sorted above the USA)', tbl.rows.map(r => r.country).join(',') === 'USA,CHN,IND' && tbl.excluded.length === 1 && tbl.excluded[0].country === 'BRA')
check('ph.official renders the normalised table once (PHYSICAL) with the excluded line and no price-implied RBI tonnes', /officialTable\(f\?\.official/.test(physSrc) && /data-official-excluded/.test(physSrc) && !/tonnes_est/.test(physSrc) && physSrc.split('<DataTable columns={offCols}').length === 2)
// C-TRADER-21 / C-DATA-20: OTC units
check('avgLabel: equal to today → one session stored; else the average', /one session stored/.test(M.avgLabel(3141, 3141)) && M.avgLabel(3141, 2900) === '20-d avg 2,900' && M.avgLabel(null, null) === '20-d avg —')
check('ph.otc: the LBMA line carries one unit under the catalog series name (no "bn/day", no "per day" claim)', !/bn\/day/.test(physSrc) && !/per day/.test(physSrc) && /catalog\?\.LBMA_OTC_TURNOVER_USD_BN\?\.name/.test(physSrc) && /avgLabel\(f\.otc\.efp\.today_rt, f\.otc\.efp\.avg_20d\)/.test(physSrc))
// C-DATA-4 / C-TRADER-8 / C-BEGINNER-20 / C-DATA-21 / C-BEGINNER-14: MACRO
check('driverTileLabel follows the series served: the Fed broad index never prints as DXY', M.driverTileLabel({ key: 'dxy', label: 'Dollar index (DXY)', series_id: 'FRED_DTWEXBGS' }) === 'Fed broad USD index (DTWEXBGS)' && M.driverTileLabel({ key: 'dxy', label: 'Dollar index (DXY)', series_id: 'DXY_CLOSE' }) === 'Dollar index (DXY)' && M.driverTileLabel({ key: 'x', label: 'Server label', series_id: 'UNKNOWN_SERIES' }) === 'Server label' && M.driverTileLabel({ key: 'k' }) === 'k')
check('driverDelta: one unit per tile from change_unit (bp for yields: 0.02 pp → +2 bp)', M.driverDelta({ unit: '%', change_unit: 'bp' }, 0.02) === '+2 bp' && M.driverDelta({ unit: 'index', change_unit: '%' }, 0.286) === '+0.29%' && M.driverDelta({ unit: 't', change_unit: 't' }, -2.85) === '−2.9 t' && M.driverDelta({ unit: '%' }, -0.04) === '−4 bp' && M.driverDelta({ unit: '%', change_unit: 'bp' }, null) === '—')
check('driverDelta negative control: a yield change never prints "pp"', !/pp/.test(M.driverDelta({ unit: '%', change_unit: 'bp' }, 0.02)) && !/ pp\b/.test(view3['gold/MacroView.tsx'].split('fmtDelta')[0]))
check('betaText carries the unit', M.betaText('beta_real_yield_per_100bp', -1440) === 'real yield −1,440 $/oz per 100 bp' && M.betaText('beta_dxy', -1.49) === 'DXY −1.49 % per 1 %' && M.betaText('beta_dxy', null) === 'DXY —' && M.betaText('other', 2) === 'other +2.00')
check('kgxUnavailableNote: names the stand-in dollar series and its date; null when the split exists', /DTWEXBGS/.test(M.kgxUnavailableNote(null, { series_id: 'FRED_DTWEXBGS', report_date: '2026-10-30', state: 'delayed' }) ?? '') && /Fri 30 Oct/.test(M.kgxUnavailableNote(null, { series_id: 'FRED_DTWEXBGS', report_date: '2026-10-30' }) ?? '') && M.kgxUnavailableNote(0.5, null) === null && !!M.kgxUnavailableNote(null, null))
check('MacroView labels tiles by series, passes the KGX note, prints betas with units; the stand-in note names no series it did not check', /driverTileLabel\(d\)/.test(view3['gold/MacroView.tsx']) && /note=\{kgxNote\}/.test(view3['gold/MacroView.tsx']) && /betaText\(k, v\)/.test(view3['gold/MacroView.tsx']) && /data-driver-fallback/.test(view3['gold/MacroView.tsx']) && !/the DXY series has no stored points/.test(view3['gold/MacroView.tsx']))
check('KgxBar hides the identity check when a leg is missing and prints the note instead', /data-kgx-unavailable/.test(sources['gold/KgxBar.tsx']) && /split\s*\?\s*<span data-kgx-identity/.test(sources['gold/KgxBar.tsx']) && !/check the inputs/.test(sources['gold/KgxBar.tsx']))

// ── GoldPage wiring: the runtime loader finds the modules by name ────────────────────────────────
check('PositioningView / PhysicalView / MacroView / LearnView export the named components GoldPage imports', /export function PositioningView/.test(sources['gold/PositioningView.tsx']) && /export function PhysicalView/.test(sources['gold/PhysicalView.tsx']) && /export function MacroView/.test(sources['gold/MacroView.tsx']) && /export function LearnView/.test(sources['gold/LearnView.tsx']))
const goldPage = fs.existsSync(path.join(ui, 'components/gold/GoldPage.tsx')) ? read('components/gold/GoldPage.tsx') : ''
check('the docked glossary is mounted once by GoldPage (every Term opens it); LEARN renders it inline once', (!goldPage || goldPage.split('<GlossaryPanel />').length === 2) && sources['gold/LearnView.tsx'].split('<GlossaryPanel inline />').length === 2 && !['gold/PositioningView.tsx', 'gold/PhysicalView.tsx', 'gold/MacroView.tsx'].some(f => /GlossaryPanel|GlossaryDock/.test(sources[f])))
check('WGC / SPDR / IBJA / SGE panels carry an attribution line', /Attribution sources=\{\['IBJA'\]\}/.test(sources['gold/PhysicalView.tsx']) && /Attribution sources=\{\['SPDR', 'WGC'\]\}/.test(sources['gold/PhysicalView.tsx']) && /Attribution sources=\{\['SGE', 'WGC'\]\}/.test(sources['gold/PhysicalView.tsx']) && /Attribution sources=\{\['SGE'\]\}/.test(sources['gold/PositioningView.tsx']))
check('context metrics render in the neutral token (no green/red on a context Stat)', !/color=\{T\.(green|red)\}/.test(sources['gold/PositioningView.tsx'] + sources['gold/PhysicalView.tsx'] + sources['gold/MacroView.tsx']))
check('no composite score anywhere in the B4B views', !/\bscore\b/i.test(sources['gold/PositioningView.tsx'] + sources['gold/PhysicalView.tsx'] + sources['gold/MacroView.tsx']))

console.log(failures ? `\n${failures} check(s) failed` : '\nall gold view checks passed')
process.exit(failures ? 1 : 0)
