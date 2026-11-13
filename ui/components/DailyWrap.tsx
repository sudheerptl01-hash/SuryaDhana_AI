'use client'

import { apiError } from '@/lib/errors'
/**
 * WRAP — the daily market wrap archive. One page per session, written at 21:00 IST by the master controller
 * (scripts/daily_wrap.py) from the terminal's own data: the session, breadth and regime, sectors, money flows,
 * movers, results reactions, tomorrow's events and the option market, and the Desk. Facts only.
 */
import { useEffect, useState } from 'react'
import { getWrap, getWraps } from '@/lib/api'
import { ErrorBox, Loading, PageHeader, Panel, T, sourceOf } from '@/components/terminal'
import { unicodeMinus } from '@/lib/format'   // server-built wrap: negative numbers with U+2212 (C1-18)
import { Markdown } from '@/components/terminal/Markdown'
import { istDateISO } from '@/lib/format'
import { nseSession } from '@/components/desktop/session'
import { wrapForeignDates, wrapPending } from '@/components/marketPagesModel'

const label = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })

export function DailyWrap() {
  const [list, setList] = useState<{ date: string; teaser: string }[] | null>(null)
  const [day, setDay] = useState<string | null>(null)
  const [md, setMd] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    getWraps().then(r => { setList(r.data.wraps); setDay(d => d ?? r.data.wraps[0]?.date ?? null) })
      .catch(e => setError(apiError(e, 'unavailable')))
  }, [])
  useEffect(() => {
    if (!day) return
    setMd(null)
    getWrap(day).then(r => setMd(r.data.markdown)).catch(e => setError(apiError(e, 'unavailable')))
  }, [day])
  const i = list?.findIndex(w => w.date === day) ?? -1
  // m022: between the close and tonight's write, say when today's wrap lands (it used to show yesterday's silently)
  const sess = nseSession(Date.now())
  const hhmm = Number(sess.istTime.replace(':', '').slice(0, 4))
  const pending = list ? wrapPending(istDateISO(), hhmm, list[0]?.date ?? null, sess.holiday == null && sess.istWeekday >= 1 && sess.istWeekday <= 5) : null
  // M10 (UI): a wrap whose sections carry another session's data ("NSE end of day 2026-10-30" under 04 Nov) says so
  const foreign = md && day ? wrapForeignDates(md, day) : []

  return (
    <div>
      <PageHeader code="WRAP" title="Daily Market Wrap"
        subtitle="one page per session, written after the evening data pass (≈ 21:00–21:30 IST) from the terminal's data · facts only, not signals" />
      {pending && <div data-wrap-pending style={{ fontSize: 11, color: T.muted, border: `1px solid ${T.border}`, padding: '6px 10px', marginBottom: 10 }}>{pending}</div>}
      {error && <ErrorBox error={error} />}
      {!list && !error && <Loading label="Reading wraps" />}
      {list && list.length === 0 && (
        <Panel title="No wraps yet" accent={T.amber} source={sourceOf(null, { source: 'daily_wrap 21:00 IST', hint: 'no wrap stored yet' })}>
          <span style={{ fontSize: 12, color: T.muted }}>The first one is written tonight at 21:00 IST. To write one now:
            <code style={{ color: T.text, marginLeft: 6 }}>PYTHONPATH=. python scripts/daily_wrap.py</code></span>
        </Panel>
      )}
      {list && list.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '260px minmax(0, 1fr)', gap: 12, alignItems: 'start' }}>
          {/* PLAN 1.4: a missed 21:00 wrap reads STALE on the chip (it used to show only as an older date in the list) */}
          <Panel title={`Archive · ${list.length}`} accent={T.amber} pad={0} source={sourceOf(list[0]?.date ?? null, { source: 'daily_wrap 21:00 IST', maxAgeDays: 4 })}>
            <div style={{ maxHeight: 760, overflowY: 'auto' }}>
              {list.map(w => (
                <button key={w.date} onClick={() => setDay(w.date)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 12px', border: 'none', cursor: 'pointer',
                           borderBottom: `1px solid ${T.border}`, borderLeft: `2px solid ${w.date === day ? T.amber : 'transparent'}`,
                           background: w.date === day ? '#0e131c' : 'transparent' }}>
                  <div style={{ fontFamily: T.mono, fontSize: 12, color: w.date === day ? T.amber : T.text }}>{label(w.date)}</div>
                  <div style={{ fontSize: 10, color: T.dim, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{unicodeMinus(String(w.teaser ?? ''))}</div>
                </button>
              ))}
            </div>
          </Panel>
          <Panel title={day ? label(day) : ''} accent={T.cyan} badge="context"
            source={sourceOf(day, { source: 'daily_wrap 21:00 IST', maxAgeDays: day === list[0]?.date ? 4 : null })}
            right={<div style={{ display: 'flex', gap: 6 }}>
              <button disabled={i >= (list.length - 1)} onClick={() => setDay(list[i + 1].date)} style={navBtn(i >= list.length - 1)}>‹ OLDER</button>
              <button disabled={i <= 0} onClick={() => setDay(list[i - 1].date)} style={navBtn(i <= 0)}>NEWER ›</button>
            </div>}>
            {foreign.length > 0 && (
              <div data-wrap-foreign style={{ border: `1px solid ${T.amber}66`, background: '#120e04', color: T.amber, fontSize: 11, padding: '6px 10px', marginBottom: 10 }}>
                ⚠ Parts of this wrap carry data from {foreign.join(', ')}, not {day}: the session&apos;s own data was not stored when it was written. Read those sections as that date&apos;s.
              </div>)}
            {!md ? <Loading label="Reading the wrap" /> : <div style={{ maxWidth: 1000 }}><Markdown source={unicodeMinus(md)} /></div>}
          </Panel>
        </div>
      )}
    </div>
  )
}

const navBtn = (off: boolean) => ({ background: 'transparent', border: `1px solid ${T.border}`, color: off ? T.dim : T.cyan, padding: '2px 8px',
                                    fontFamily: T.mono, fontSize: 10, cursor: off ? 'default' : 'pointer', letterSpacing: 0.5 })
