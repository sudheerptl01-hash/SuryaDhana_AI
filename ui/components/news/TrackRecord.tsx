'use client'

/**
 * News scanner TRACK RECORD — how past picks did after the scan, measured honestly:
 * entry at the next session's open, excess = minus NSE stocks of similar liquidity over the same days,
 * real ICICI round-trip cost. Data: reports/news_scanner/track_record.json (scripts/news_scan_performance.py).
 */
import { T } from './format'

export interface TrackRow {
  scan_date: string; symbol: string; yahoo: string | null; nse_symbol: string | null; company: string | null
  conviction: number | null; theme: string | null; status: string | null; entry_date: string | null
  entry_price: number | null; last_price: number | null; sessions_held: number | null
  r_to_date_pct: number | null; ex_to_date_pct: number | null; peak_pct: number | null; worst_pct: number | null
  r5_pct: number | null; ex5_pct: number | null
}
interface Horizon {
  horizon?: string; group?: string; picks: number; days: number; avg_return_pct: number; median_return_pct: number
  avg_excess_pct: number; beat_similar_stocks_pct: number; after_costs_pct: number; profitable_after_costs_pct: number
}
export interface TrackRecordData {
  generated_at: string; prices_through: string; cost_pct: number; position_rs: number; picks: number; scans: number
  first_scan: string; last_scan: string; t5: { t: number | null; scan_days: number }
  horizons: Horizon[]; sections: Record<string, Horizon[]>; rows: TrackRow[]
}

const pct = (v: number | null | undefined, d = 2) => v == null || !Number.isFinite(v) ? '—' : `${Number(v.toFixed(d)) > 0 ? '+' : Number(v.toFixed(d)) < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`
const tone = (v: number | null | undefined) => v == null ? T.muted : v > 0 ? T.green : v < 0 ? T.red : T.muted

/** One-line verdict used in the top bar and the view header. */
export function trackVerdict(d: TrackRecordData): { text: string; color: string } {
  const h5 = d.horizons.find(h => h.horizon === '5 sessions')
  const t = d.t5.t
  if (!h5 || d.t5.scan_days < 10) {
    return { text: `Too early: ${d.t5.scan_days} scan days measured at 5 sessions (need ≥ 10 for a first read)`, color: T.amber }
  }
  if (t != null && t >= 2 && h5.after_costs_pct > 0) return { text: `Edge: beats similar stocks after costs (t ${t.toFixed(1)})`, color: T.green }
  return { text: `No edge yet: picks behave like similar stocks (t ${t == null ? '—' : t.toFixed(2).replace('-', '−')}) and lose ${Math.abs(h5.after_costs_pct).toFixed(1)}% after costs over 5 sessions`, color: T.red }
}

function Table({ rows, first }: { rows: Horizon[]; first: string }) {
  const th = { padding: '6px 10px', fontSize: 10, letterSpacing: 1, color: T.muted, textAlign: 'right' as const, fontWeight: 600,
               borderBottom: `1px solid ${T.border}`, whiteSpace: 'nowrap' as const, textTransform: 'uppercase' as const }
  const td = { padding: '5px 10px', fontSize: 12, textAlign: 'right' as const, fontFamily: T.mono, borderBottom: `1px solid ${T.border}` }
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>
        <th style={{ ...th, textAlign: 'left' }}>{first}</th><th style={th}>Picks</th><th style={th}>Scan days</th>
        <th style={th}>Avg return</th><th style={th}>vs similar</th><th style={th}>Beat similar</th>
        <th style={th}>After costs</th><th style={th}>Profitable after costs</th>
      </tr></thead>
      <tbody>{rows.map((r, i) => (
        <tr key={i}>
          <td style={{ ...td, textAlign: 'left', color: T.text, fontFamily: undefined }}>{(r.horizon ?? r.group ?? '').replace(/^1 sessions$/, '1 session')}</td>
          <td style={{ ...td, color: T.muted }}>{r.picks}</td><td style={{ ...td, color: T.muted }}>{r.days}</td>
          <td style={{ ...td, color: tone(r.avg_return_pct) }}>{pct(r.avg_return_pct)}</td>
          <td style={{ ...td, color: tone(r.avg_excess_pct) }}>{pct(r.avg_excess_pct)}</td>
          <td style={{ ...td, color: r.beat_similar_stocks_pct >= 50 ? T.green : T.red }}>{r.beat_similar_stocks_pct.toFixed(0)}%</td>
          <td style={{ ...td, color: tone(r.after_costs_pct) }}>{pct(r.after_costs_pct)}</td>
          <td style={{ ...td, color: T.muted }}>{r.profitable_after_costs_pct.toFixed(0)}%</td>
        </tr>
      ))}</tbody>
    </table>
  )
}

function Box({ title, children, sub }: { title: string; children: React.ReactNode; sub?: string }) {
  return (
    <section style={{ border: `1px solid ${T.border}`, background: T.panel, minWidth: 0 }}>
      <header style={{ padding: '7px 12px', borderBottom: `1px solid ${T.border}`, background: '#080b10', display: 'flex', gap: 10, alignItems: 'center' }}>
        <span style={{ width: 3, height: 12, background: T.amber }} />
        <span style={{ fontFamily: T.display, fontSize: 12, fontWeight: 600, letterSpacing: 1.6, color: T.amber, textTransform: 'uppercase' }}>{title}</span>
        {sub && <span style={{ fontSize: 10, color: T.muted }}>{sub}</span>}
      </header>
      <div style={{ overflowX: 'auto' }}>{children}</div>
    </section>
  )
}

function PickList({ rows, title }: { rows: TrackRow[]; title: string }) {
  return (
    <Box title={title} sub="to date, vs similar stocks">
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <tbody>{rows.map(r => (
          <tr key={`${r.scan_date}-${r.symbol}`} style={{ borderBottom: `1px solid ${T.border}` }}>
            <td style={{ padding: '5px 10px', color: T.amber, fontWeight: 700 }}>{r.nse_symbol ?? r.symbol}</td>
            <td style={{ padding: '5px 10px', color: T.dim, fontSize: 10 }}>{r.scan_date} · conv {r.conviction ?? '—'}</td>
            <td style={{ padding: '5px 10px', color: T.muted, fontSize: 10, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.theme ?? ''}</td>
            <td style={{ padding: '5px 10px', textAlign: 'right', fontFamily: T.mono, color: tone(r.r_to_date_pct) }}>{pct(r.r_to_date_pct, 1)}</td>
            <td style={{ padding: '5px 10px', textAlign: 'right', fontFamily: T.mono, color: tone(r.ex_to_date_pct), fontWeight: 700 }}>{pct(r.ex_to_date_pct, 1)}</td>
          </tr>
        ))}</tbody>
      </table>
    </Box>
  )
}

export function TrackRecordView({ data }: { data: TrackRecordData }) {
  const v = trackVerdict(data)
  const measured = data.rows.filter(r => r.ex_to_date_pct != null).sort((a, b) => (b.ex_to_date_pct ?? 0) - (a.ex_to_date_pct ?? 0))
  return (
    <div className="nt-scroll" style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'grid', gap: 12, alignContent: 'start' }}>
      <div style={{ border: `1px solid ${T.border}`, borderLeft: `3px solid ${v.color}`, background: '#080b10', padding: '12px 16px' }}>
        <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, marginBottom: 4 }}>VERDICT SO FAR</div>
        <div style={{ fontSize: 15, color: v.color, fontWeight: 600 }}>{v.text}</div>
        <div style={{ fontSize: 11, color: T.muted, marginTop: 6, lineHeight: 1.6 }}>
          {data.picks} picks from {data.scans} scans ({data.first_scan} → {data.last_scan}) · prices through {data.prices_through} ·
          entry at the next session&apos;s open · &quot;vs similar&quot; = minus NSE stocks of similar liquidity over the same days ·
          round-trip cost {data.cost_pct.toFixed(2)}% at ₹{data.position_rs.toLocaleString('en-IN')} (ICICI) · updated {data.generated_at.replace('T', ' ')}
        </div>
      </div>
      <Box title="How the picks did" sub="by holding period"><Table rows={data.horizons} first="Held" /></Box>
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(520px, 1fr))' }}>
        <PickList title="Best picks" rows={measured.slice(0, 10)} />
        <PickList title="Worst picks" rows={measured.slice(-10).reverse()} />
      </div>
      {Object.entries(data.sections).map(([title, rows]) => (
        <Box key={title} title={title.replace(/\s*\(.*\)$/, '')} sub={title.match(/\((.*)\)$/)?.[1]}>
          <Table rows={rows} first={title.startsWith('By scan') ? 'Scan' : 'Group'} />
        </Box>
      ))}
      <div style={{ fontSize: 10, color: T.dim }}>Refresh: python scripts/news_scan_performance.py (≈ 1 min) · full write-up in Research → News scanner track record.</div>
    </div>
  )
}

/** "Previously flagged" strip for a pick the scanner chose on earlier dates. */
export function PriorPicks({ rows, currentScan }: { rows: TrackRow[]; currentScan: string | undefined }) {
  const prior = rows.filter(r => r.scan_date !== currentScan && r.entry_price != null).sort((a, b) => a.scan_date.localeCompare(b.scan_date))
  if (!prior.length) return null
  return (
    <div style={{ padding: '8px 18px', borderBottom: `1px solid ${T.border}`, display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', background: '#080b10' }}>
      <span style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.muted }}>PREVIOUSLY FLAGGED</span>
      {prior.map(r => (
        <span key={r.scan_date} style={{ fontSize: 11, color: T.text }}>
          {r.scan_date} <span style={{ color: T.dim }}>(conv {r.conviction ?? '—'})</span>{' '}
          <span style={{ color: tone(r.r_to_date_pct) }}>{pct(r.r_to_date_pct, 1)}</span>
          <span style={{ color: T.dim }}> since entry · </span>
          <span style={{ color: tone(r.ex_to_date_pct) }}>{pct(r.ex_to_date_pct, 1)}</span>
          <span style={{ color: T.dim }}> vs similar</span>
        </span>
      ))}
    </div>
  )
}
