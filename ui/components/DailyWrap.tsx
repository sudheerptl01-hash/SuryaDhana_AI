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

  return (
    <div>
      <PageHeader code="WRAP" title="Daily Market Wrap"
        subtitle="one page per session, written 21:00 IST from the terminal's data · facts only, not signals" />
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
                  <div style={{ fontFamily: T.mono, fontSize: 11.5, color: w.date === day ? T.amber : T.text }}>{label(w.date)}</div>
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
            {!md ? <Loading label="Reading the wrap" /> : <div style={{ maxWidth: 1000 }}><Markdown source={unicodeMinus(md)} /></div>}
          </Panel>
        </div>
      )}
    </div>
  )
}

const navBtn = (off: boolean) => ({ background: 'transparent', border: `1px solid ${T.border}`, color: off ? T.dim : T.cyan, padding: '2px 8px',
                                    fontFamily: T.mono, fontSize: 10, cursor: off ? 'default' : 'pointer', letterSpacing: 0.5 })
