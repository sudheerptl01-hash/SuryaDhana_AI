'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * Stock profile (DES) — one NSE stock from the exchange's own files: price and range, delivery, who owns it and
 * how that changed, insider and bulk/block deals, F&O positioning, margin funding, corporate events.
 * Data: /api/stocks/{ticker}/profile ← data-service /db/security/{symbol} (services/data-service/security.py).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { getMarketMonitor, getStockProfile, getStockResults, getStockFinancials, type FinQuarter, type Valuation, type FinLatest, getStockFilings, type Filing, getStockActions, type StockActions, getStockPeHistory, type PeHistory, type ResultReaction, type ResultsSummary, type StockProfile as Profile, getBasketRisk, type BasketRisk, getStockNews, getSymbols, type StockHeadline } from '@/lib/api'
import { DataTable, EventBadge, Loading, T, AvoidFlag, TickerLink, fiscalQuarter, fmtPct, ordinal, tone, fmtInr } from '@/components/terminal'
import { daysUntil, useResultsAvoid } from '@/lib/useCorpEvents'
import { TradeTicket } from './TradeTicket'
import { goToPage } from '@/lib/navigate'
import { useFinancialsLatest } from '@/lib/useFinancials'

const pct = (v: number | null | undefined, d = 1) => fmtPct(v, d)
const inr = (v: number | null | undefined, d = 2) => fmtInr(v, d)
const cr = (v: number | null | undefined) => (v == null ? '—' : `₹${Math.abs(v) >= 100 ? Math.round(v).toLocaleString('en-IN') : v.toFixed(1)} cr`)
const num = (v: number | null | undefined) => (v == null ? '—' : v >= 1e7 ? `${(v / 1e7).toFixed(2)} cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : Math.round(v).toLocaleString('en-IN'))
const day = (s: string) => new Date(`${s}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' })

function Box({ title, sub, children, accent = T.amber, id }: { title: string; sub?: ReactNode; children: ReactNode; accent?: string; id?: string }) {
  return (
    <section id={id} style={{ border: `1px solid ${T.border}`, background: T.panel, minWidth: 0, scrollMarginTop: 8 }}>
      <header style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 10px', borderBottom: `1px solid ${T.border}`, background: '#080b10' }}>
        <span style={{ width: 3, height: 11, background: accent }} />
        <span style={{ fontFamily: T.display, fontSize: 11, fontWeight: 600, letterSpacing: 1.5, color: accent, textTransform: 'uppercase' }}>{title}</span>
        {sub && <span style={{ fontSize: 10, color: T.muted }}>{sub}</span>}
      </header>
      <div style={{ padding: 10 }}>{children}</div>
    </section>
  )
}

function Row({ k, v, c, hint }: { k: ReactNode; v: ReactNode; c?: string; hint?: string }) {
  return (
    <div title={hint} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '4px 0', borderBottom: `1px solid ${T.border}`, fontSize: 11.5 }}>
      <span style={{ color: T.muted }}>{k}</span><span style={{ color: c ?? T.text, fontFamily: T.mono, textAlign: 'right' }}>{v}</span>
    </div>
  )
}

function RangeBar({ lo, hi, v }: { lo: number; hi: number; v: number }) {
  const p = Math.max(0, Math.min(100, ((v - lo) / (hi - lo || 1)) * 100))
  return (
    <div style={{ margin: '6px 0 2px' }}>
      <div style={{ position: 'relative', height: 6, background: T.border }}>
        <div style={{ position: 'absolute', left: 0, width: `${p}%`, top: 0, bottom: 0, background: `linear-gradient(90deg, ${T.red}88, ${T.amber}88, ${T.green}88)` }} />
        <div style={{ position: 'absolute', left: `calc(${p}% - 1px)`, top: -3, width: 2, height: 12, background: T.bright }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: T.dim, marginTop: 3, fontFamily: T.mono }}>
        <span>52W LOW {inr(lo)}</span><span>52W HIGH {inr(hi)}</span>
      </div>
    </div>
  )
}

/** Tiny stacked bars of an ownership share across quarters. */
function Trend({ values, color }: { values: (number | null)[]; color: string }) {
  const v = values.filter((x): x is number => x != null)
  if (v.length < 2) return null
  const lo = Math.min(...v), hi = Math.max(...v)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 1, height: 14, marginRight: 8 }}>
      {values.map((x, i) => (
        <span key={i} style={{ width: 4, height: x == null ? 1 : 3 + ((x - lo) / (hi - lo || 1)) * 11, background: color, opacity: 0.4 + (i / values.length) * 0.6 }} />
      ))}
    </span>
  )
}

export function StockProfile({ ticker, focus }: { ticker: string; focus?: 'fa' | 'ern' }) {
  const [p, setP] = useState<Profile | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const avoid = useResultsAvoid()
  const [peers, setPeers] = useState<NonNullable<Awaited<ReturnType<typeof getMarketMonitor>>['data']['map']>>([])
  useEffect(() => { getMarketMonitor().then(r => setPeers(r.data.map ?? [])).catch(() => {}) }, [])
  const [news, setNews] = useState<StockHeadline[] | null>(null)
  useEffect(() => {
    let live = true
    setNews(null)
    const sym = ticker.toUpperCase().replace(/\.NS$/, '')
    getSymbols().then(r => r.data.data.find(x => x.t === sym)?.n).catch(() => undefined)
      .then(name => getStockNews(sym, name)).then(r => live && setNews(r.data.headlines)).catch(() => live && setNews([]))
    return () => { live = false }
  }, [ticker])
  const [risk, setRisk] = useState<BasketRisk | null>(null)
  useEffect(() => {
    let live = true
    setRisk(null)
    getBasketRisk([ticker.toUpperCase().replace(/\.NS$/, '')]).then(r => live && setRisk(r.data)).catch(() => {})
    return () => { live = false }
  }, [ticker])
  const [ern, setErn] = useState<{ reactions: ResultReaction[]; summary: ResultsSummary } | null>(null)
  useEffect(() => {
    let live = true
    setErn(null)
    getStockResults(ticker).then(r => live && setErn(r.data)).catch(() => live && setErn({ reactions: [], summary: { quarters: 0 } }))
    return () => { live = false }
  }, [ticker])
  const [fa, setFa] = useState<{ quarters: FinQuarter[]; basis: string; valuation?: Valuation } | null>(null)
  const [faErr, setFaErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setFa(null); setFaErr(null)
    getStockFinancials(ticker).then(r => live && setFa(r.data))
      .catch(e => live && setFaErr(apiError(e, 'unavailable')))
    return () => { live = false }
  }, [ticker])
  // GO `TCS FA` / `TCS ERN`: bring that section into view once the page above it has laid out
  const [scrolled, setScrolled] = useState<string | null>(null)
  useEffect(() => {
    if (!focus || !p || !ern || (focus === 'fa' && !fa && !faErr) || scrolled === `${ticker}:${focus}`) return
    const t = setTimeout(() => { document.getElementById(`sd-${focus}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); setScrolled(`${ticker}:${focus}`) }, 400)
    return () => clearTimeout(t)
  })
  useEffect(() => {
    let live = true
    setP(null); setErr(null)
    getStockProfile(ticker).then(r => live && setP(r.data))
      .catch(e => live && setErr(apiError(e, 'Profile unavailable')))
    return () => { live = false }
  }, [ticker])

  if (err) return <div style={{ padding: 20, color: T.red, fontSize: 12 }}>{err}</div>
  if (!p) return <Loading label="Reading NSE files" />
  const px = p.price
  const own = p.ownership
  const quarters = own ? [...own.quarters].reverse() : []           // oldest → newest for the trend bars
  const upcoming = p.events.filter(e => daysUntil(e.event_date) >= 0)
  const past = p.events.filter(e => daysUntil(e.event_date) < 0).reverse()

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {avoid.get(p.symbol) && (() => { const a = avoid.get(p.symbol)!; return (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '8px 10px', border: `1px solid ${T.red}66`, background: '#14070a', fontSize: 11.5 }}>
          <AvoidFlag r={a} />
          <span style={{ color: T.text }}>
            Results reaction <b style={{ color: T.red }}>{a.vs_nifty_pct?.toFixed(1)}% vs NIFTY</b> on {a.reaction_date} ({a.sessions_since} sessions ago).
            In the post-results drift study, stocks after a ≤ −5% reaction lagged the market by another 1.8–3.7% over 60 sessions.
          </span>
        </div>) })()}
      {upcoming.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', padding: '8px 10px', border: `1px solid ${T.amber}55`, background: '#120e04' }}>
          <span style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.amber }}>COMING UP</span>
          {upcoming.map(e => (
            <span key={`${e.kind}-${e.event_date}`} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 11, color: T.text }}>
              <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} detail={(e as { detail?: string | null }).detail} />
              {e.kind === 'RESULTS' && ern?.summary.avg_abs_move_pct != null && (
                <span style={{ color: T.amber, fontFamily: T.mono, fontSize: 10.5 }}
                      title={`Average absolute move on the last ${ern.summary.quarters} results`}>
                  typically ±{ern.summary.avg_abs_move_pct.toFixed(1)}% on results
                </span>
              )}
              <span style={{ color: T.muted, maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.detail ?? ''}>{e.purpose}</span>
              {e.url && <a href={e.url} target="_blank" rel="noreferrer" style={{ color: T.cyan, fontSize: 10, textDecoration: 'none' }}>FILING ↗</a>}
            </span>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', alignItems: 'start' }}>
        {px && (
          <Box title="Price" sub={`NSE close ${day(px.date)} · ${px.series}${p.industry ? ` · ${p.industry}` : ''}`}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span style={{ fontFamily: T.mono, fontSize: 24, fontWeight: 700, color: T.bright }}>{inr(px.close)}</span>
              <span style={{ fontFamily: T.mono, fontSize: 13, color: tone(px.chg_pct) }}>{pct(px.chg_pct, 2)}</span>
            </div>
            {px.high_52w != null && px.low_52w != null && px.close != null && <RangeBar lo={px.low_52w} hi={px.high_52w} v={px.close} />}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 4, margin: '8px 0' }}>
              {Object.entries(px.returns).map(([k, v]) => (
                <div key={k} style={{ textAlign: 'center', border: `1px solid ${T.border}`, padding: '4px 0' }}>
                  <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1 }}>{k}</div>
                  <div style={{ fontFamily: T.mono, fontSize: 11.5, color: tone(v) }}>{pct(v, 1)}</div>
                </div>
              ))}
            </div>
            <Row k="From 52-week high / low" v={<><span style={{ color: tone(px.from_high_pct) }}>{pct(px.from_high_pct)}</span> / <span style={{ color: tone(px.from_low_pct) }}>{pct(px.from_low_pct)}</span></>} />
            <Row k="Trend" v={['sma20', 'sma50', 'sma200'].map(k => (
              <span key={k} title={`${k.toUpperCase()} ${inr(px.sma[k])}`} style={{ marginLeft: 8, color: px.above[k] == null ? T.dim : px.above[k] ? T.green : T.red }}>
                {px.above[k] == null ? '·' : px.above[k] ? '▲' : '▼'} {k.replace('sma', '')}D
              </span>))} hint="Above (▲) or below (▼) the 20, 50 and 200-day averages" />
            {fa?.valuation?.mcap != null && (() => { const v = fa.valuation!
              const c = (x: number | null | undefined) => x == null ? '—' : Math.round(x / 1e7).toLocaleString('en-IN')
              return <Row k="Market cap · P/E · P/B" hint="From the company's NSE results filings: shares × last close; P/E on the last four quarters' profit (FA below)"
                v={<span><span style={{ color: T.text }}>₹{c(v.mcap)} cr</span><span style={{ color: T.dim }}> · </span>
                  <span style={{ color: T.amber }}>{v.pe != null ? `${v.pe.toFixed(1)}×` : '—'}</span><span style={{ color: T.dim }}> · </span>
                  <span style={{ color: T.cyan }}>{v.pb != null ? `${v.pb.toFixed(1)}×` : '—'}</span></span>} /> })()}
            <Row k="Daily range (ATR 14)" v={pct(px.atr_pct, 2).replace('+', '')} hint="Average true range as a % of price: a normal day's move" />
            {/* C1-13: these are the NSE close's session (bhavcopy), not 'today': on a weekend or before the EOD files land
                they are the last session's, so the row names the session date */}
            <Row k={`Turnover ${day(px.date)} / 20d median`} v={`${cr(px.turnover_cr)} / ${cr(px.turnover_cr_20d)}`} />
            <Row k="Volume vs 50-day average" v={px.volume_x50 != null ? `${px.volume_x50.toFixed(2)}×` : '—'} c={(px.volume_x50 ?? 0) >= 2 ? T.amber : undefined} />
            <Row k={`Delivery % ${day(px.date)} / 20d avg`} v={`${px.deliv_pct ?? '—'}% / ${px.deliv_pct_20d ?? '—'}%`}
                 c={px.deliv_pct != null && px.deliv_pct_20d != null && px.deliv_pct > px.deliv_pct_20d + 10 ? T.green : undefined}
                 hint="Share of traded shares taken into demat: high = buyers holding, low = intraday churn" />
            {p.corporate_actions.length > 0 && (
              <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>
                Adjusted for {p.corporate_actions.map(a => `${a.k < 1 ? `1:${Math.round(1 / a.k)} split/bonus` : `×${a.k}`} on ${day(String(a.date).slice(0, 10))}`).join(', ')}
              </div>
            )}
          </Box>
        )}

        {risk?.stocks[0]?.vol != null && risk.nifty && (() => {
          const r = risk.stocks[0], n = risk.nifty!
          return (
            <Box title="Risk" sub={`1 year vs NIFTY 50 · split-adjusted · to ${day(risk.window.end ?? '')}`} accent={T.red}>
              <Row k="Volatility (annualised)" v={<>{r.vol!.toFixed(0)}% <span style={{ color: T.dim, fontSize: 10.5 }}>NIFTY {n.vol.toFixed(0)}% · {(r.vol! / n.vol).toFixed(1)}×</span></>}
                   c={r.vol! > 2 * n.vol ? T.amber : undefined} hint="Standard deviation of daily returns × √252" />
              <Row k="Beta to NIFTY" v={r.beta != null ? r.beta.toFixed(2) : '—'} hint="1.0 = moves one-for-one with NIFTY; 1.5 = 50% more" />
              <Row k="Max drawdown" v={<><span style={{ color: T.red }}>{pct(r.max_dd, 1)}</span> <span style={{ color: T.dim, fontSize: 10.5 }}>NIFTY {pct(n.max_dd, 1)}</span></>}
                   hint="Worst peak-to-trough fall over the year" />
              <Row k="Position at 1% portfolio risk" v={r.vol ? `${Math.min(100, (1 / (r.vol / Math.sqrt(252) * 2)) * 100).toFixed(0)}% of capital` : '—'}
                   hint="Size so that a 2-standard-deviation day costs about 1% of the portfolio: 1% ÷ (2 × daily vol). A sizing guide, not a rule." />
            </Box>
          )
        })()}

        <Box title="Ownership" sub={own ? own.window : 'shareholding pattern'} accent={T.cyan}>
          {!own ? <div style={{ fontSize: 11, color: T.dim }}>No shareholding filings stored for this stock (coverage: the ~320 most liquid names).</div> : <>
            {([['promoter_pct', 'Promoters', T.amber], ['fpi_pct', 'Foreign investors (FPI)', T.cyan], ['mf_pct', 'Mutual funds', T.violet], ['retail_pct', 'Retail (< ₹2 lakh)', T.muted]] as const).map(([k, label, c]) => (
              <Row key={k} k={label} v={<>
                <Trend values={quarters.map(q => q[k])} color={c} />
                {own.quarters[0][k] != null ? `${own.quarters[0][k]!.toFixed(2)}%` : '—'}
                <span style={{ color: tone(own.change_over_window[k]), marginLeft: 8, fontSize: 10.5 }}>{own.change_over_window[k] != null ? `${fmtSigned(own.change_over_window[k]!, 2)} pp` : ''}</span>
              </>} />
            ))}
            <Row k="Shareholders" v={<>{num(own.quarters[0].total_holders)} <span style={{ color: T.muted, fontSize: 10.5, marginLeft: 6 }}>{pct(own.holders_change_pct)}</span></>}
                 hint="Rising shareholder counts with falling institutional share often means stock moving to retail" />
            <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>Latest filing: quarter ended {day(own.quarters[0].period_end)} · pp = percentage points over the window</div>
          </>}
        </Box>

        {px?.close != null && (
          <Box title="Trade ticket" sub="real ICICI costs · before you buy" accent={T.green}>
            <TradeTicket price={px.close} atrPct={px.atr_pct} />
          </Box>
        )}

        <Box title="Positioning" accent={T.violet}
          sub={p.derivatives ? <span>F&O · margin funding · <span role="button" style={{ color: T.cyan, cursor: 'pointer' }}
            onClick={() => { try { localStorage.setItem('suryadhana.omon.v1', p.symbol) } catch { /* blocked */ }
                             window.dispatchEvent(new Event('suryadhana:omon')); goToPage('options') }}>OPTION CHAIN ›</span></span> : 'F&O · margin funding'}>
          {p.derivatives ? <>
            <Row k="Futures OI (near month)" v={<>{num(p.derivatives.fut_oi)} <span style={{ color: tone(p.derivatives.fut_oi_chg_20d_pct), fontSize: 10.5 }}>{pct(p.derivatives.fut_oi_chg_20d_pct)} 20d</span></>} />
            <Row k="Futures basis" v={pct(p.derivatives.basis_pct, 2)} hint="Futures premium over spot: unusually high = leveraged longs" />
            <Row k="Put / call open interest" v={p.derivatives.pcr_oi?.toFixed(2) ?? '—'} />
            <Row k="Expiry" v={p.derivatives.near_expiry ? day(p.derivatives.near_expiry) : '—'} />
          </> : <div style={{ fontSize: 11, color: T.dim, marginBottom: 6 }}>Not in the F&O segment.</div>}
          {p.margin_funding && <>
            <Row k="Bought on margin (MTF)" v={cr(p.margin_funding.amount_cr)} />
            <Row k="MTF shares, 20-day change" v={pct(p.margin_funding.qty_chg_20d_pct)} c={(p.margin_funding.qty_chg_20d_pct ?? 0) > 25 ? T.amber : undefined}
                 hint="Fast growth in margin-funded holdings = leveraged retail demand; it unwinds hard in sell-offs" />
          </>}
        </Box>
      </div>

      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', alignItems: 'start' }}>
        <Box title="Insider trades" sub={`last 12 months · net market buying ${cr(p.insiders.net_market_buy_cr)}`} accent={T.green}>
          {p.insiders.rows.length === 0 ? <div style={{ fontSize: 11, color: T.dim }}>None filed in the last 12 months (coverage: the ~320 most liquid names before May 2026, every NSE company since).</div> : (
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {p.insiders.rows.map((r, i) => (
                <Row key={i} k={<span>{day(r.intimation_date)} · <span style={{ color: T.text }}>{r.person}</span> <span style={{ color: T.dim, fontSize: 10 }}>{r.category}</span></span>}
                     v={<span style={{ color: /buy|acqui/i.test(r.txn_type ?? '') ? T.green : /sell|dispos/i.test(r.txn_type ?? '') ? T.red : T.muted }}>
                       {r.txn_type} {r.value ? cr(r.value / 1e7) : ''} <span style={{ color: T.dim, fontSize: 10 }}>{r.mode}</span></span>} />
              ))}
            </div>
          )}
        </Box>
        <Box title="Bulk & block deals" sub={`last 6 months · net ${cr(p.deals.net_value_cr)}`} accent={T.amber}>
          {p.deals.short.days > 0 && (
            <div style={{ fontSize: 10.5, color: T.muted, marginBottom: 6 }}>
              Short sales disclosed on {p.deals.short.days} day{p.deals.short.days > 1 ? 's' : ''} · {num(p.deals.short.qty)} shares in total
            </div>
          )}
          {p.deals.rows.length === 0 ? <div style={{ fontSize: 11, color: T.dim }}>No bulk or block deals in the last 6 months.</div> : (
            <div style={{ maxHeight: 220, overflowY: 'auto' }}>
              {p.deals.rows.map((r, i) => (
                <Row key={i} k={<span>{day(r.date)} · <span style={{ color: T.dim, fontSize: 10, textTransform: 'uppercase' }}>{r.kind}</span> <span style={{ color: T.text }}>{r.client_name ?? '—'}</span></span>}
                     v={<span style={{ color: r.side === 'BUY' ? T.green : r.side === 'SELL' ? T.red : T.muted }}>{r.side} {num(r.qty)} @ {inr(r.price)} <span style={{ color: T.dim }}>{cr(r.value_cr)}</span></span>} />
              ))}
            </div>
          )}
        </Box>
      </div>

      <Box id="sd-ern" title="Results history" accent={T.amber}
        sub={ern ? (ern.summary.quarters ? `last ${ern.summary.quarters} quarters · reaction session after each release` : 'no results found on NSE') : 'asking NSE…'}>
        {!ern ? <div style={{ fontSize: 11, color: T.dim }}>Loading release dates…</div> : ern.reactions.length === 0 ? null : <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 6, marginBottom: 8 }}>
            {[['Typical move', `±${ern.summary.avg_abs_move_pct?.toFixed(1)}%`, T.amber],
              ['vs NIFTY', ern.summary.avg_abs_vs_nifty_pct != null ? `±${ern.summary.avg_abs_vs_nifty_pct.toFixed(1)}%` : '—', T.text],
              ['Up on results', `${ern.summary.up_pct?.toFixed(0)}%`, (ern.summary.up_pct ?? 0) >= 50 ? T.green : T.red],
              ['Best', pct(ern.summary.biggest_up_pct), T.green], ['Worst', pct(ern.summary.biggest_down_pct), T.red]].map(([k, v, c]) => (
              <div key={k} style={{ border: `1px solid ${T.border}`, padding: '5px 8px' }}>
                <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
                <div style={{ fontFamily: T.mono, fontSize: 13, color: c as string }}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 70, padding: '0 2px', borderBottom: `1px solid ${T.border}` }}>
            {[...ern.reactions].reverse().map(r => {
              const m = Math.max(...ern.reactions.map(x => Math.abs(x.move_pct)), 1)
              const h = Math.max(2, (Math.abs(r.move_pct) / m) * 32)
              return (
                <div key={r.period_end} title={`Quarter ${r.period_end} · released ${r.released_at} (${r.timing}) · ${r.reaction_date}: ${pct(r.move_pct, 2)} (gap ${pct(r.gap_pct, 2)}, vs NIFTY ${pct(r.vs_nifty_pct, 2)})`}
                  style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', height: 70 }}>
                  <div style={{ height: 35, display: 'flex', alignItems: 'flex-end' }}>
                    {r.move_pct > 0 && <div style={{ width: '100%', height: h, background: T.green }} />}
                  </div>
                  <div style={{ height: 35 }}>{r.move_pct <= 0 && <div style={{ width: '100%', height: h, background: T.red }} />}</div>
                </div>
              )
            })}
          </div>
          <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 6 }}>
            {ern.reactions.map(r => (
              <Row key={r.period_end} k={<span>Q-end {day(r.period_end)} · <span style={{ color: T.dim, fontSize: 10 }}>released {r.released_at.slice(5)} {r.timing}</span></span>}
                   v={<><span style={{ color: tone(r.move_pct), fontWeight: 600 }}>{pct(r.move_pct, 1)}</span>
                        <span style={{ color: T.dim, fontSize: 10, marginLeft: 8 }}>gap {pct(r.gap_pct, 1)} · vs NIFTY {pct(r.vs_nifty_pct, 1)}</span></>} />
            ))}
          </div>
        </>}
      </Box>

      <Box id="sd-fa" title="Financials (FA)" accent={T.green}
        sub={fa ? (fa.quarters.length ? `last ${fa.quarters.length} quarters · ${fa.quarters[0].consolidated ? 'consolidated' : 'standalone'} · from NSE results filings (XBRL)` : 'no XBRL results on NSE')
                : faErr ? `unavailable: ${faErr}` : 'reading NSE results filings… (first time ~6 s)'}>
        {fa && fa.quarters.length > 0 && (() => {
          const qs = [...fa.quarters].reverse()                     // oldest → newest for the bars
          const bank = fa.quarters[0].bank
          const crs = (v: number | null | undefined) => v == null ? '—' : (Math.abs(v) / 1e7 >= 1000 ? Math.round(v / 1e7).toLocaleString('en-IN') : (v / 1e7).toFixed(1))
          const g = (v: number | null, turn?: string | null) => turn ? <span style={{ color: turn === 'to profit' ? T.green : T.red }}>{turn}</span>
            : v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: tone(v) }}>{pct(v, 1)}</span>
          const maxRev = Math.max(...qs.map(q => Math.abs(q.revenue ?? 0)), 1), maxPat = Math.max(...qs.map(q => Math.abs(q.pat ?? 0)), 1)
          const qn = fiscalQuarter
          const v = fa.valuation ?? {}
          return <>
            {v.mcap != null && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6, marginBottom: 10 }}>
                {([['Market cap', `₹${crs(v.mcap)} cr`, T.text, `${((v.shares ?? 0) / 1e7).toFixed(2)} cr shares × ₹${v.price} (last NSE close)`],
                   ['P/E (TTM)', v.pe != null ? `${v.pe.toFixed(1)}×` : v.ttm_profit != null && v.ttm_profit <= 0 ? 'loss' : '—', T.amber,
                    v.ttm_profit != null ? `market cap ÷ last 4 quarters' profit to owners (₹${crs(v.ttm_profit)} cr)` : 'needs four consecutive quarters'],
                   ['P/B', v.pb != null ? `${v.pb.toFixed(2)}×` : '—', T.cyan, v.book_as_of ? `owners' equity at ${v.book_as_of}: ₹${crs(v.book_equity)} cr` : 'no balance sheet in the filings'],
                   ['Earnings yield', v.pe ? `${(100 / v.pe).toFixed(1)}%` : '—', T.green, 'TTM profit ÷ market cap']] as const).map(([k, val, c, tip]) => (
                  <div key={k} title={tip} style={{ border: `1px solid ${T.border}`, padding: '5px 8px' }}>
                    <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
                    <div style={{ fontFamily: T.mono, fontSize: 13, color: c }}>{val}</div>
                  </div>))}
              </div>
            )}
            <PeHistoryChart symbol={p.symbol} />
            {(() => {   // trailing twelve months: the last four quarters vs the four before (only when consecutive)
              const qq = fa.quarters
              const months = (pe: string) => { const d = new Date(pe); return d.getFullYear() * 12 + d.getMonth() }
              const run = (a: number, b: number) => qq.length >= b && qq.slice(a, b).every((q, i, arr) => i === 0 || months(arr[i - 1].period_end) - months(q.period_end) === 3)
              if (!run(0, 4)) return null
              const sum = (from: number, k: 'revenue' | 'pat') => qq.slice(from, from + 4).reduce((a, q) => a + (q[k] ?? NaN), 0)
              const prev = run(4, 8) && months(qq[3].period_end) - months(qq[4].period_end) === 3
              const rev = sum(0, 'revenue'), pat = sum(0, 'pat')
              const gr = (now: number, then: number) => prev && Number.isFinite(now) && Number.isFinite(then) && then > 0 ? (now / then - 1) * 100 : null
              const rg = gr(rev, sum(4, 'revenue')), pg = gr(pat, sum(4, 'pat'))
              return <div style={{ fontSize: 11, fontFamily: T.mono, color: T.muted, marginBottom: 8 }}>
                TTM {bank ? 'interest earned' : 'revenue'} <span style={{ color: T.text }}>₹{crs(rev)} cr</span>{rg != null && <> ({g(rg)})</>}
                <span style={{ color: T.dim }}> · </span>TTM net profit <span style={{ color: T.text }}>₹{crs(pat)} cr</span>{pg != null && <> ({g(pg)})</>}
                <span style={{ color: T.dim }}> · last four quarters vs the four before</span>
              </div>
            })()}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 8 }}>
              {([[bank ? 'Interest earned (₹ cr)' : 'Revenue (₹ cr)', 'revenue', maxRev, T.amber], ['Net profit (₹ cr)', 'pat', maxPat, T.green]] as const).map(([label, k, mx, c]) => (
                <div key={k}>
                  <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase', marginBottom: 3 }}>{label}</div>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 54, borderBottom: `1px solid ${T.border}` }}>
                    {qs.map(q => { const v = q[k] ?? 0
                      return <div key={q.period_end} title={`${qn(q.period_end)} (to ${q.period_end}): ₹${crs(v)} cr`}
                        style={{ flex: 1, height: Math.max(2, Math.abs(v) / mx * 52), background: v < 0 ? T.red : c, opacity: q === qs[qs.length - 1] ? 1 : 0.65 }} /> })}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: T.dim, marginTop: 2 }}>
                    <span>{qn(qs[0].period_end)}</span><span>{qn(qs[qs.length - 1].period_end)}</span></div>
                </div>
              ))}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: T.mono }}>
                <thead><tr style={{ color: T.muted, fontSize: 9, letterSpacing: 1, textTransform: 'uppercase' }}>
                  {['Quarter', bank ? 'Int. earned' : 'Revenue', 'YoY', 'QoQ', ...(bank ? ['NII'] : []), 'Net profit', 'YoY', 'QoQ', 'Margin', 'EPS'].map((h, i) =>
                    <th key={i} style={{ textAlign: i ? 'right' : 'left', padding: '4px 6px', borderBottom: `1px solid ${T.border}`, fontWeight: 500 }}>{h}</th>)}
                </tr></thead>
                <tbody>{fa.quarters.slice(0, 8).map(q => (
                  <tr key={q.period_end} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: '4px 6px', color: T.text }} title={`to ${q.period_end} · filed ${q.filed_at.replace('T', ' ').slice(0, 16)}${q.scale_fixed ? ` · the filing reported this quarter 100× too ${q.scale_fixed > 0 ? 'small' : 'large'} (a unit error); shown corrected` : ''}`}>
                      {qn(q.period_end)}{q.scale_fixed ? <span style={{ color: T.amber }}> †</span> : null}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{crs(q.revenue)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{g(q.revenue_yoy)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{g(q.revenue_qoq)}</td>
                    {bank && <td style={{ padding: '4px 6px', textAlign: 'right' }}>{crs(q.nii)}</td>}
                    <td style={{ padding: '4px 6px', textAlign: 'right', color: (q.pat ?? 0) < 0 ? T.red : T.text }}>{crs(q.pat)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{g(q.pat_yoy, q.pat_yoy_turn)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right' }}>{g(q.pat_qoq, q.pat_qoq_turn)}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', color: T.muted }}>{q.pat_margin == null ? '—' : `${q.pat_margin.toFixed(1)}%`}</td>
                    <td style={{ padding: '4px 6px', textAlign: 'right', color: T.muted }}>{q.eps == null ? '—' : q.eps.toFixed(2)}</td>
                  </tr>))}</tbody>
              </table>
            </div>
            <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{fa.basis}. Net profit includes minority interest. Growth needs the same quarter a year earlier.
              {fa.quarters.some(q => q.scale_fixed) && <span style={{ color: T.amber }}> † the company filed this quarter in the wrong unit (100× off); shown corrected.</span>}</div>
          </>
        })()}
      </Box>

      {p.industry && (() => {
        const group = peers.filter(m => m.industry === p.industry).sort((a, b) => (b.size ?? 0) - (a.size ?? 0)).slice(0, 12)
        if (group.length < 2) return null
        const cell = (v: number | null) => <span style={{ color: tone(v) }}>{pct(v, 1)}</span>
        return (
          <Box title="Peers · relative value (RV)" sub={`${p.industry} · most traded names · valuation at the last NSE close · growth = latest quarter vs a year ago`} accent={T.cyan}>
            <PeerTable group={group} me={p.symbol} />
          </Box>
        )
      })()}

      <ActionsBox symbol={p.symbol} />

      <CompanyFilingsBox symbol={p.symbol} />

      <Box title="News" sub="last 7 days · Google News, filtered to this company · headlines, not advice" accent={T.violet}>
        {news == null ? <div style={{ fontSize: 11, color: T.dim }}>Reading headlines…</div>
          : news.length === 0 ? <div style={{ fontSize: 11, color: T.dim }}>No headlines about this company in the last week.</div>
          : news.map(h => (
            <div key={h.link} style={{ display: 'grid', gridTemplateColumns: '96px 1fr', gap: 10, padding: '4px 0', borderBottom: `1px solid ${T.border}`, alignItems: 'baseline' }}>
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>
                {new Date(h.published_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}
              </span>
              <a href={h.link} target="_blank" rel="noreferrer" style={{ color: T.text, textDecoration: 'none', fontSize: 11.5 }}>
                {h.title} <span style={{ color: T.dim, fontSize: 10 }}>· {h.publisher} ↗</span>
              </a>
            </div>))}
      </Box>

      {past.length > 0 && (
        <div style={{ fontSize: 10.5, color: T.dim }}>
          Recent events: {past.map(e => `${e.kind.toLowerCase()} ${day(e.event_date)}`).join(' · ')}
        </div>
      )}
      <div style={{ fontSize: 10, color: T.dim }}>Source: NSE bhavcopy, shareholding (XBRL), insider (PIT), bulk/block/short deals, F&O bhavcopy, MTF, corporate filings. End of day.</div>
    </div>
  )
}

type PeerRow = { symbol: string; r1: number | null; r5: number | null; r21: number | null }

/** Peers with valuation and growth from their own results filings; companies not read yet are queued for a
 *  background read and fill in over the next minute or two. */
function PeerTable({ group, me }: { group: PeerRow[]; me: string }) {
  const { fin } = useFinancialsLatest(group.map(g => g.symbol))
  const crs = (v: number | null | undefined) => v == null ? '—' : Math.round(v / 1e7).toLocaleString('en-IN')
  const g = (v: number | null | undefined, turn?: string | null) => turn ? <span style={{ color: turn === 'to profit' ? T.green : T.red }}>{turn}</span>
    : v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: v >= 0 ? T.green : T.red }}>{fmtPct(v, 1)}</span>
  const ret = (v: number | null) => <span style={{ color: v == null ? T.dim : v >= 0 ? T.green : T.red }}>{fmtPct(v, 1)}</span>
  const pending = group.filter(x => !fin[x.symbol]).length
  const pes = group.map(x => fin[x.symbol]?.pe).filter((v): v is number => v != null).sort((a, b) => a - b)
  const median = pes.length ? pes[Math.floor(pes.length / 2)] : null
  return <>
    <DataTable<PeerRow> dense rows={group} rowKey={r => r.symbol} initialSort={{ key: 'mcap', dir: 'desc' }}
      rowStyle={r => r.symbol === me ? { background: '#141106' } : undefined}
      columns={[
        { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => r.symbol === me ? <span style={{ color: T.amber, fontWeight: 700 }}>▸ {r.symbol}</span> : <TickerLink symbol={r.symbol} /> },
        { key: 'mcap', label: 'Mcap ₹ cr', align: 'right', sort: r => fin[r.symbol]?.mcap ?? -1, render: r => <span style={{ color: T.muted }}>{fin[r.symbol] ? crs(fin[r.symbol].mcap) : '…'}</span> },
        { key: 'pe', label: 'P/E', align: 'right', sort: r => fin[r.symbol]?.pe ?? 1e9, title: 'market cap ÷ last 4 quarters of profit',
          render: r => { const v = fin[r.symbol]?.pe; return v == null ? <span style={{ color: T.dim }}>{fin[r.symbol] ? '—' : '…'}</span>
            : <span style={{ color: median != null && v < median ? T.green : T.text }}>{v.toFixed(1)}×</span> } },
        { key: 'pctl', label: 'vs own past', align: 'right', sort: r => fin[r.symbol]?.pe_pctl ?? 1e9, title: "percentile of today's P/E within its own history",
          render: r => { const v = fin[r.symbol]?.pe_pctl; return v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: v <= 20 ? T.green : v >= 80 ? T.red : T.muted }}>{ordinal(v)}</span> } },
        { key: 'pb', label: 'P/B', align: 'right', sort: r => fin[r.symbol]?.pb ?? 1e9, render: r => { const v = fin[r.symbol]?.pb; return v == null ? <span style={{ color: T.dim }}>—</span> : `${v.toFixed(1)}×` } },
        { key: 'rev', label: 'Rev YoY', align: 'right', sort: r => fin[r.symbol]?.revenue_yoy ?? -999, render: r => g(fin[r.symbol]?.revenue_yoy) },
        { key: 'pat', label: 'Profit YoY', align: 'right', sort: r => fin[r.symbol]?.pat_yoy ?? -999, render: r => g(fin[r.symbol]?.pat_yoy, fin[r.symbol]?.pat_yoy_turn) },
        { key: 'mg', label: 'Margin', align: 'right', sort: r => fin[r.symbol]?.pat_margin ?? -999, render: r => { const v = fin[r.symbol]?.pat_margin; return v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: T.muted }}>{v.toFixed(1)}%</span> } },
        { key: 'r1', label: '1D', align: 'right', sort: r => r.r1 ?? -999, render: r => ret(r.r1) },
        { key: 'r5', label: '1W', align: 'right', sort: r => r.r5 ?? -999, render: r => ret(r.r5) },
        { key: 'r21', label: '1M', align: 'right', sort: r => r.r21 ?? -999, render: r => ret(r.r21) },
      ]} />
    <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>
      {median != null && <>median P/E {median.toFixed(1)}× (green = cheaper than the median) · </>}
      {pending ? `reading the results filings of ${pending} more compan${pending === 1 ? 'y' : 'ies'} from NSE…` : 'from each company’s latest NSE results filing'}
    </div>
  </>
}

const CAT_COLOR: Record<string, string> = { results: T.green, orders: '#38bdf8', rating: T.amber, 'm&a': '#c084fc', insider: '#fb923c',
  capital: '#22d3ee', people: '#a3a3a3', board: T.amber, analyst: '#94a3b8', press: '#94a3b8', routine: '#525c6e', other: '#64748b' }

/** CN: the company's own NSE announcements, newest first; routine paperwork hidden unless asked for. */
function CompanyFilingsBox({ symbol }: { symbol: string }) {
  const [data, setData] = useState<{ items: Filing[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [days, setDays] = useState(30)
  const [routine, setRoutine] = useState(false)
  const [cat, setCat] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setData(null); setErr(null)
    getStockFilings(symbol, days).then(r => live && setData(r.data)).catch(e => live && setErr(apiError(e, 'unavailable')))
    return () => { live = false }
  }, [symbol, days])
  const items = (data?.items ?? []).filter(f => (routine || f.category !== 'routine') && (!cat || f.category === cat))
  const counts = new Map<string, number>()
  for (const f of data?.items ?? []) counts.set(f.category, (counts.get(f.category) ?? 0) + 1)
  return (
    <Box title="Company filings (CN)" accent={T.cyan}
      sub={data ? `NSE announcements · last ${days} days · ${data.items.length} filings${routine ? '' : ` (${counts.get('routine') ?? 0} routine hidden)`}` : err ? `unavailable: ${err}` : 'asking NSE…'}>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
        {[30, 90, 365].map(d => <span key={d} role="button" onClick={() => setDays(d)} style={{ fontSize: 10, padding: '1px 6px', cursor: 'pointer',
          border: `1px solid ${days === d ? T.amber : T.border}`, color: days === d ? T.amber : T.muted }}>{d === 365 ? '1Y' : `${d}D`}</span>)}
        <span style={{ width: 8 }} />
        {[...counts.entries()].filter(([c]) => c !== 'routine').sort((a, b) => b[1] - a[1]).map(([c, n]) => (
          <span key={c} role="button" onClick={() => setCat(cat === c ? null : c)} style={{ fontSize: 10, padding: '1px 6px', cursor: 'pointer', textTransform: 'uppercase',
            border: `1px solid ${cat === c ? CAT_COLOR[c] ?? T.muted : T.border}`, color: CAT_COLOR[c] ?? T.muted }}>{c} {n}</span>))}
        <span role="button" onClick={() => setRoutine(!routine)} style={{ fontSize: 10, padding: '1px 6px', cursor: 'pointer', color: T.dim,
          border: `1px solid ${routine ? T.muted : T.border}` }}>{routine ? 'hide routine' : 'show routine'}</span>
      </div>
      {!data && !err ? <div style={{ fontSize: 11, color: T.dim }}>Loading…</div> : items.length === 0 ? <div style={{ fontSize: 11, color: T.dim }}>No filings in this window.</div> :
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          {items.map((f, i) => (
            <div key={`${f.seq}-${i}`} style={{ display: 'grid', gridTemplateColumns: '92px 70px 1fr auto', gap: 8, padding: '4px 0', borderBottom: `1px solid ${T.border}`, fontSize: 11, alignItems: 'baseline' }}>
              <span style={{ color: T.dim, fontFamily: T.mono, fontSize: 10 }}>{(f.time ?? '').slice(5, 16)}</span>
              <span style={{ color: CAT_COLOR[f.category] ?? T.muted, fontSize: 9.5, textTransform: 'uppercase', letterSpacing: 0.8 }}>{f.category}</span>
              <span style={{ color: T.text, lineHeight: 1.4 }} title={f.text}>{f.subject}<span style={{ color: T.dim }}> · {f.text.replace(/^.*?has (informed|submitted) (to )?the Exchange,? ?(about|regarding|that)? ?/i, '').slice(0, 140)}</span></span>
              {f.pdf ? <a href={f.pdf} target="_blank" rel="noopener noreferrer" style={{ color: T.cyan, fontSize: 10 }}>PDF ↗</a> : <span />}
            </div>))}
        </div>}
    </Box>
  )
}

/** DVD: dividends per share by financial year, TTM yield, and every bonus / split / buyback (NSE corporate actions). */
function ActionsBox({ symbol }: { symbol: string }) {
  const [d, setD] = useState<StockActions | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setD(null); setErr(null)
    getStockActions(symbol, 5).then(r => live && setD(r.data)).catch(e => live && setErr(apiError(e, 'unavailable')))
    return () => { live = false }
  }, [symbol])
  const fys = d ? Object.entries(d.by_fy).sort((a, b) => a[0].localeCompare(b[0])) : []
  const maxFy = Math.max(1, ...fys.map(([, v]) => v))
  const KC: Record<string, string> = { dividend: T.green, bonus: T.amber, split: T.amber, buyback: T.cyan, rights: T.violet, other: T.muted }
  return (
    <Box title="Dividends & corporate actions (DVD)" accent={T.green}
      sub={d ? `NSE corporate actions · last ${d.years} years · ₹ per share as declared (not adjusted for later splits / bonuses)` : err ? `unavailable: ${err}` : 'asking NSE…'}>
      {!d ? <div style={{ fontSize: 11, color: T.dim }}>{err ? '' : 'Loading…'}</div> : d.items.length === 0 ? <div style={{ fontSize: 11, color: T.dim }}>No corporate actions in this window.</div> : <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginBottom: 8 }}>
          {([['Dividend, last 12 months', d.ttm_dividend != null ? `₹${d.ttm_dividend.toLocaleString('en-IN')}` : d.ttm_reshaped ? 'split/bonus' : '—', T.text,
              d.ttm_reshaped ? 'a split or bonus inside the window makes per-share amounts incomparable' : 'sum of ex-dates in the last 365 days'],
             ['Dividend yield (TTM)', d.ttm_yield_pct != null ? `${d.ttm_yield_pct.toFixed(2)}%` : '—', T.green, d.price ? `at the last NSE close ₹${d.price}` : ''],
             ['Specials in 5 years', String(d.items.filter(i => i.special).length), T.amber, 'special dividends (included in the totals)']] as const).map(([k, v, c, tip]) => (
            <div key={k} title={tip} style={{ border: `1px solid ${T.border}`, padding: '5px 8px' }}>
              <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
              <div style={{ fontFamily: T.mono, fontSize: 13, color: c }}>{v}</div>
            </div>))}
        </div>
        {fys.length > 0 && <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 54, borderBottom: `1px solid ${T.border}`, marginBottom: 4 }}>
          {fys.map(([fy, v]) => <div key={fy} title={`${fy}: ₹${v} per share`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
            <span style={{ fontSize: 9, color: T.muted, fontFamily: T.mono }}>₹{v}</span>
            <div style={{ width: '70%', height: Math.max(2, v / maxFy * 36), background: T.green, opacity: 0.8 }} />
          </div>)}
        </div>}
        {fys.length > 0 && <div style={{ display: 'flex', gap: 6, fontSize: 9, color: T.dim, marginBottom: 8 }}>{fys.map(([fy]) => <span key={fy} style={{ flex: 1, textAlign: 'center' }}>{fy}</span>)}</div>}
        <div style={{ maxHeight: 180, overflowY: 'auto' }}>
          {d.items.map((i, n) => (
            <div key={`${i.ex_date}-${n}`} style={{ display: 'grid', gridTemplateColumns: '84px 70px 1fr auto', gap: 8, padding: '3px 0', borderBottom: `1px solid ${T.border}`, fontSize: 11 }}>
              <span style={{ color: T.dim, fontFamily: T.mono, fontSize: 10 }}>{i.ex_date}</span>
              <span style={{ color: KC[i.kind], fontSize: 9.5, textTransform: 'uppercase', letterSpacing: 0.8 }}>{i.kind}{i.special ? ' +sp' : ''}</span>
              <span style={{ color: T.text }}>{i.subject}</span>
              <span style={{ color: T.muted, fontFamily: T.mono }}>{i.rs_per_share != null ? `₹${i.rs_per_share}` : ''}</span>
            </div>))}
        </div>
      </>}
    </Box>
  )
}

/** GE: daily trailing P/E (point-in-time) with its interquartile band and median, and where today sits in it. */
function PeHistoryChart({ symbol }: { symbol: string }) {
  const [d, setD] = useState<PeHistory | null>(null)
  useEffect(() => {
    let live = true
    setD(null)
    getStockPeHistory(symbol).then(r => live && setD(r.data)).catch(() => live && setD({ symbol, points: [] }))
    return () => { live = false }
  }, [symbol])
  if (!d || d.points.length < 20 || d.median == null) return null
  const W = 900, H = 90, pad = 4
  const vals = d.points.map(p => p.pe)
  const lo = Math.min(...vals, d.p25 ?? Infinity), hi = Math.max(...vals, d.p75 ?? -Infinity)
  const x = (i: number) => pad + (i / (vals.length - 1)) * (W - 2 * pad)
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad)
  const path = vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const pctl = d.percentile ?? 50
  const tone = pctl <= 25 ? T.green : pctl >= 75 ? T.red : T.amber
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 11, fontFamily: T.mono, color: T.muted, marginBottom: 4 }}>
        P/E history (GE) · now <span style={{ color: T.text }}>{d.now?.toFixed(1)}×</span>, <span style={{ color: tone }}>{ordinal(pctl)} percentile</span> of its own range since {d.since?.slice(0, 7)}
        <span style={{ color: T.dim }}> · median {d.median.toFixed(1)}× · middle half {d.p25?.toFixed(1)}–{d.p75?.toFixed(1)}× · low {d.low?.toFixed(1)}× high {d.high?.toFixed(1)}×</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: H, display: 'block', border: `1px solid ${T.border}` }} preserveAspectRatio="none">
        {d.p25 != null && d.p75 != null && <rect x={0} width={W} y={y(d.p75)} height={Math.max(1, y(d.p25) - y(d.p75))} fill="rgba(56,189,248,0.08)" />}
        <line x1={0} x2={W} y1={y(d.median)} y2={y(d.median)} stroke={T.dim} strokeDasharray="4 4" />
        <path d={path} fill="none" stroke={T.amber} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        <circle cx={x(vals.length - 1)} cy={y(vals[vals.length - 1])} r={3} fill={tone} />
      </svg>
      <div style={{ fontSize: 9.5, color: T.dim, marginTop: 2 }}>
        Point-in-time: each day uses only results filed by then · split/bonus-adjusted price × today&apos;s shares · shaded = middle half, dashed = median · describes the past, not a forecast
      </div>
    </div>
  )
}
