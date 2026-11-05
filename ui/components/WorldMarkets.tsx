'use client'

/**
 * WEI — world markets: the overnight and global cues an Indian trader checks before 09:15. Indices by region,
 * FX, commodities, rates and crypto, with day change, a one-month sparkline and where the price sits in its day
 * range. Yahoo Finance quotes (delayed), refreshed every 60 s via /api/news-scanner/quotes.
 *
 * Gold (gold program PLAN §b): the GC=F row is unchanged; ONE second line under it carries the GOLD health words,
 * the India basis, the COT managed-money net and the roll date from /api/gold/health (60 s cache in ui-api, no
 * Breeze on the path), with the five-number header strip on hover and a GOLD › chip. Nothing else moves into WEI.
 */
import { goToPage } from '@/lib/navigate'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { spanNote } from '@/lib/quoteSpan'
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { getFomc, getGiftNifty, getIndicesLive, getLiveMovers, getNewsQuotes, getRbiMpc, type FomcMeeting, type GiftNifty } from '@/lib/api'
import type { Quote } from '@/components/news/types'
import { Chip, PageHeader, Panel, Spark, T, fmtNum, tone, sourceOf } from '@/components/terminal'
import { GoldHoverCard } from '@/components/gold/HealthStrip'
import { getGoldHealth } from '@/lib/gold/api'
import { weiLine } from '@/lib/gold/format'
import { setGoldSubInUrl } from '@/lib/gold/prefs'
import type { GoldHealth } from '@/lib/gold/types'

type Q = Quote & { spark?: number[] }

const NSE_NAME: Record<string, string> = { '^NSEI': 'NIFTY 50', '^NSEBANK': 'NIFTY BANK', '^CNXIT': 'NIFTY IT', '^INDIAVIX': 'INDIA VIX' }
const GROUPS: { title: string; accent: string; rows: [string, string][] }[] = [
  { title: 'India', accent: T.amber, rows: [['^NSEI', 'NIFTY 50'], ['^NSEBANK', 'BANK NIFTY'], ['^BSESN', 'SENSEX'], ['^CNXIT', 'NIFTY IT'], ['^INDIAVIX', 'INDIA VIX']] },
  { title: 'Americas', accent: T.cyan, rows: [['^GSPC', 'S&P 500'], ['^IXIC', 'NASDAQ'], ['^DJI', 'DOW JONES'], ['^RUT', 'RUSSELL 2000'], ['^VIX', 'VIX']] },
  { title: 'Asia-Pacific', accent: T.green, rows: [['^N225', 'NIKKEI 225'], ['^HSI', 'HANG SENG'], ['000001.SS', 'SHANGHAI'], ['^KS11', 'KOSPI'], ['^TWII', 'TAIWAN'], ['^STI', 'SINGAPORE'], ['^AXJO', 'ASX 200']] },
  { title: 'Europe', accent: T.violet, rows: [['^FTSE', 'FTSE 100'], ['^GDAXI', 'DAX'], ['^FCHI', 'CAC 40'], ['^STOXX50E', 'EURO STOXX 50']] },
  { title: 'Currencies', accent: T.amber, rows: [['INR=X', 'USD/INR'], ['DX-Y.NYB', 'DOLLAR INDEX'], ['EURUSD=X', 'EUR/USD'], ['JPY=X', 'USD/JPY'], ['CNY=X', 'USD/CNY']] },
  { title: 'Commodities', accent: T.red, rows: [['BZ=F', 'BRENT'], ['CL=F', 'WTI CRUDE'], ['GC=F', 'GOLD'], ['SI=F', 'SILVER'], ['HG=F', 'COPPER'], ['NG=F', 'NATURAL GAS']] },
  { title: 'Rates & crypto', accent: T.cyan, rows: [['^TNX', 'US 10Y YIELD'], ['^IRX', 'US 3M BILL'], ['BTC-USD', 'BITCOIN'], ['ETH-USD', 'ETHER']] },
]
const ALL = GROUPS.flatMap(g => g.rows.map(r => r[0]))

const fmt = (v?: number, d = 2) => fmtNum(v, d)
const ago = (t?: number) => {
  if (!t) return ''
  const m = Math.round((Date.now() / 1000 - t) / 60)
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`
}

export function WorldMarkets() {
  const [q, setQ] = useState<Record<string, Q>>({})
  const [asOf, setAsOf] = useState<Date | null>(null)
  const load = useCallback(async () => {
    try {
      const out: Record<string, Q> = {}
      for (let i = 0; i < ALL.length; i += 60) Object.assign(out, (await getNewsQuotes(ALL.slice(i, i + 60))).data.quotes)
      // Indian indices: price and change from NSE (Yahoo's can lag a whole session after the close); Yahoo keeps the spark
      try {
        const nse = (await getIndicesLive(Object.values(NSE_NAME))).data.indices
        for (const [sym, name] of Object.entries(NSE_NAME)) {
          const v = nse[name]
          if (v?.last == null) continue
          const m = /^(\d{2})-(\w{3})-(\d{4}) (\d{2}):(\d{2})/.exec(v.time ?? '')
          const mon = m ? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].indexOf(m[2]) : -1
          const t = m && mon >= 0 ? Date.UTC(+m[3], mon, +m[1], +m[4], +m[5]) / 1000 - 19800 : undefined     // IST → epoch
          out[sym] = { ...(out[sym] ?? {}), price: v.last, change: v.change ?? null, change_pct: v.change_pct, ...(t ? { market_time: t } : {}), prev_date: null, stale: false, available: true } as Q
        }
      } catch { /* Yahoo values stay */ }
      setQ(out); setAsOf(new Date())
    } catch { /* keep last */ }
  }, [])
  useEffect(() => { load(); const iv = setInterval(load, 60_000); return () => clearInterval(iv) }, [load])
  const [fomc, setFomc] = useState<FomcMeeting[]>([])
  useEffect(() => { getFomc().then(r => setFomc(r.data.upcoming)).catch(() => {}) }, [])
  const [gift, setGift] = useState<GiftNifty | null>(null)
  useEffect(() => {
    const get = () => getGiftNifty().then(r => setGift(r.data)).catch(() => {})
    get(); const iv = setInterval(get, 60_000); return () => clearInterval(iv)
  }, [])
  const [rbi, setRbi] = useState<{ end: string }[]>([])
  useEffect(() => { getRbiMpc().then(r => setRbi(r.data.upcoming)).catch(() => {}) }, [])
  // the GOLD line under the GC=F row (weekly verdict words; the page itself is GOLD)
  const [gold, setGold] = useState<GoldHealth | null>(null)
  const [goldErr, setGoldErr] = useState(false)
  const [goldHover, setGoldHover] = useState(false)
  useEffect(() => {
    let alive = true
    const get = () => getGoldHealth('W').then(r => { if (alive) { setGold(r.data); setGoldErr(false) } }).catch(() => { if (alive) setGoldErr(true) })
    get(); const iv = setInterval(get, 60_000); return () => { alive = false; clearInterval(iv) }
  }, [])
  const daysTo = (iso: string) => Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000)
  // India 10-year G-sec: NSE's benchmark clean-price index (no free live yield feed). Price down = yield up.
  const [gsec, setGsec] = useState<{ last: number | null; change_pct: number | null } | null>(null)
  useEffect(() => {
    const get = () => getLiveMovers('NIFTY').then(r => {
      const x = r.data.indices.find(i => i.index === 'NIFTY 10 YR BENCHMARK G-SEC (CLEAN PRICE)')
      if (x) setGsec({ last: x.last, change_pct: x.change_pct })
    }).catch(() => {})
    get(); const iv = setInterval(get, 120_000); return () => clearInterval(iv)
  }, [])

  // only markets that printed in the last 18 h: a closed market's last change is not news
  const movers = useMemo(() => Object.entries(q).filter(([, v]) => v?.available && v.change_pct != null
      && v.market_time != null && Date.now() / 1000 - v.market_time < 18 * 3600)
    .sort((a, b) => Math.abs(b[1].change_pct!) - Math.abs(a[1].change_pct!)).slice(0, 3), [q])

  return (
    <div>
      <PageHeader code="WEI" title="World Markets"
        subtitle={`global cues for the Indian open · Yahoo Finance, delayed · every 60 s${asOf ? ` · ${asOf.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })}` : ''}`}
        right={movers.length ? <span style={{ fontSize: 11, color: T.muted }}>live movers: {movers.map(([s, v]) => (
          <span key={s} style={{ marginLeft: 8, color: tone(v.change_pct) }}>{GROUPS.flatMap(g => g.rows).find(r => r[0] === s)?.[1]} {fmtSigned(v.change_pct!, 2)}%</span>))}</span> : undefined} />
      {fomc.length > 0 && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', border: `1px solid ${T.border}`, background: T.panel,
                      padding: '7px 12px', marginBottom: 12, fontSize: 11.5 }}>
          <span style={{ fontFamily: T.display, fontSize: 10.5, letterSpacing: 1.4, color: T.cyan }}>POLICY DATES · US FED (FOMC)</span>
          {fomc.slice(0, 4).map((m, i) => {
            const days = Math.round((new Date(`${m.end}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000)
            return (
              <span key={m.end} style={{ color: i === 0 ? T.text : T.muted }}>
                {new Date(`${m.end}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                {m.projections && <span title="with the Summary of Economic Projections (dot plot)" style={{ color: T.amber }}> ★</span>}
                {i === 0 && <span style={{ color: T.amber }}> · {days === 0 ? 'today' : days === 1 ? 'tomorrow' : `in ${days} days`}</span>}
              </span>)
          })}
          <span style={{ color: T.dim, fontSize: 10 }}>≈23:30 IST (00:30 in US winter) · ★ projections</span>
          {rbi.length > 0 && <>
            <span style={{ fontFamily: T.display, fontSize: 10.5, letterSpacing: 1.4, color: T.amber, marginLeft: 8 }}>RBI MPC</span>
            {rbi.slice(0, 2).map((m, i) => (
              <span key={m.end} style={{ color: i === 0 ? T.text : T.muted }}>
                {new Date(`${m.end}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                {i === 0 && <span style={{ color: T.amber }}> · in {daysTo(m.end)} days</span>}
              </span>))}
            <span style={{ color: T.dim, fontSize: 10 }}>≈10:00 IST · sources: federalreserve.gov, rbi.org.in</span>
          </>}
          <span role="button" onClick={() => goToPage('eco')} style={{ marginLeft: 'auto', color: T.cyan, cursor: 'pointer', fontSize: 10.5 }}
            title="India CPI, WPI, IIP, GDP releases with RBI and Fed decisions">FULL CALENDAR · ECO ›</span>
        </div>
      )}
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(520px, 1fr))', alignItems: 'start' }}>
        {GROUPS.map(g => (
          <Panel source={sourceOf(asOf ? asOf.toISOString() : null, { source: 'Yahoo', maxAgeDays: 1 })} key={g.title} title={g.title} accent={g.accent} pad={0}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11.5 }}>
              <tbody>
                {g.title === 'India' && gift?.last != null && (
                  <tr style={{ borderBottom: `1px solid ${T.border}`, background: '#0d1219' }}
                      title="GIFT NIFTY (NSE IX, near-month NIFTY future): trades 06:30–15:40 and 16:35–02:45 IST, the overnight cue for the NIFTY open">
                    <td style={{ padding: '6px 10px', color: T.amber, whiteSpace: 'nowrap', fontWeight: 600 }}>GIFT NIFTY</td>
                    <td style={{ padding: '6px 6px', textAlign: 'right', color: T.bright }}>{fmt(gift.last)}</td>
                    <td style={{ padding: '6px 6px', textAlign: 'right', color: tone(gift.change) }}>{gift.change != null ? fmtSigned(gift.change, 2) : ''}</td>
                    <td style={{ padding: '6px 6px', textAlign: 'right', color: tone(gift.change_pct), fontWeight: 600 }}>{gift.change_pct != null ? `${fmtSigned(gift.change_pct, 2)}%` : ''}</td>
                    <td colSpan={2} style={{ padding: '6px 6px', fontSize: 10.5, color: tone(gift.implied_gap_pct) }}>
                      {gift.implied_gap_pct != null ? `implies ${fmtSigned(gift.implied_gap_pct, 2)}% vs NIFTY close` : ''}</td>
                    <td style={{ padding: '6px 10px', textAlign: 'right', color: T.dim, fontSize: 10 }}>{gift.time?.slice(12) ?? ''}</td>
                  </tr>
                )}
                {g.rows.map(([sym, label]) => {
                  const v = q[sym]
                  const ok = v?.available
                  const range = ok && v.day_high != null && v.day_low != null && v.day_high > v.day_low && v.price != null
                    ? ((v.price - v.day_low) / (v.day_high - v.day_low)) * 100 : null
                  return (
                    <Fragment key={sym}>
                    <tr style={{ borderBottom: `1px solid ${T.border}` }}
                        title={sym === 'GC=F' ? 'Yahoo continuous front GC=F (GC1), not the Dec contract' : undefined}>
                      <td style={{ padding: '6px 10px', color: T.text, whiteSpace: 'nowrap' }}>{label}</td>
                      <td style={{ padding: '6px 6px', textAlign: 'right', color: T.bright }}>{ok ? fmt(v.price, sym.includes('=X') && !sym.startsWith('INR') ? 4 : 2) : '—'}</td>
                      <td style={{ padding: '6px 6px', textAlign: 'right', color: tone(v?.change) }}>{ok && v.change != null ? fmtSigned(v.change, 2) : ''}</td>
                      <td style={{ padding: '6px 6px', textAlign: 'right', color: tone(v?.change_pct), fontWeight: 600, whiteSpace: 'nowrap' }}
                        title={spanNote(v) ? `change since the ${v!.prev_date} close: a holiday, or a session the data source skipped` : undefined}>
                        {ok && v.change_pct != null ? `${fmtSigned(v.change_pct, 2)}%` : ''}
                        {ok && spanNote(v) && <div style={{ fontSize: 9, color: T.dim, fontWeight: 400 }}>{spanNote(v)}</div>}</td>
                      <td style={{ padding: '4px 6px' }}>{ok && v.spark && v.spark.length > 1
                        ? <Spark values={v.spark} width={80} height={20} color={v.spark[v.spark.length - 1] >= v.spark[0] ? T.green : T.red} /> : null}</td>
                      <td style={{ padding: '6px 6px', width: 70 }} title="where the price sits in today's range">
                        {range != null && (
                          <span style={{ display: 'inline-block', position: 'relative', width: 60, height: 5, background: T.border, verticalAlign: 'middle' }}>
                            <span style={{ position: 'absolute', left: `calc(${range}% - 2px)`, top: -2, width: 4, height: 9, background: range > 70 ? T.green : range < 30 ? T.red : T.amber }} />
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: T.dim, fontSize: 10 }}>{ok ? ago(v.market_time) : ''}</td>
                    </tr>
                    {sym === 'GC=F' && (
                      <tr data-wei-gold style={{ borderBottom: `1px solid ${T.border}`, background: '#0d1219' }}>
                        <td colSpan={7} style={{ padding: '3px 10px', fontSize: 10.5, maxWidth: 0, overflow: 'hidden' }}>
                          <span style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}
                                onMouseEnter={() => setGoldHover(true)} onMouseLeave={() => setGoldHover(false)}>
                            <span style={{ color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}
                                  title="GOLD health in one line: verdict words · India basis vs duty-paid landed · COT managed-money net (w/w) · roll date. Hover for the five numbers.">
                              {gold ? weiLine(gold) : goldErr ? 'GOLD · health unavailable' : 'GOLD · loading…'}
                            </span>
                            <Chip color={T.amber} onClick={() => { setGoldSubInUrl('health'); goToPage('gold') }} title="Open the gold terminal (GO: GOLD, XAU, GC)">GOLD ›</Chip>
                            {goldHover && (
                              <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 30, background: T.panel, border: `1px solid ${T.amber}`, padding: '8px 10px',
                                            boxShadow: '0 8px 24px rgba(0,0,0,.6)' }}>
                                <GoldHoverCard />
                              </div>
                            )}
                          </span>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  )
                })}
                {g.title === 'Rates & crypto' && gsec && (
                  <tr style={{ borderBottom: `1px solid ${T.border}` }} title="NSE's 10-year benchmark G-sec clean-price index: the price falls when the yield rises">
                    <td style={{ padding: '6px 10px', color: T.text, whiteSpace: 'nowrap' }}>INDIA 10Y G-SEC <span style={{ color: T.dim, fontSize: 9.5 }}>PRICE</span></td>
                    <td style={{ padding: '6px 6px', textAlign: 'right', color: T.bright }}>{fmt(gsec.last ?? undefined)}</td>
                    <td />
                    <td style={{ padding: '6px 6px', textAlign: 'right', color: tone(gsec.change_pct), fontWeight: 600 }}>{gsec.change_pct != null ? `${fmtSigned(gsec.change_pct, 2)}%` : ''}</td>
                    <td colSpan={2} style={{ padding: '6px 6px', fontSize: 10, color: T.dim }}>{gsec.change_pct != null ? (gsec.change_pct < 0 ? 'yields up' : gsec.change_pct > 0 ? 'yields down' : 'flat') : ''}</td>
                    <td style={{ padding: '6px 10px', textAlign: 'right', color: T.dim, fontSize: 10 }}>NSE</td>
                  </tr>
                )}
              </tbody>
            </table>
          </Panel>
        ))}
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>Right column: time since the last print (markets that are closed show their last close). Delayed data, for context only.</div>
    </div>
  )
}
