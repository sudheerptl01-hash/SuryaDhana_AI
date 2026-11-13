'use client'

/**
 * RSK › DISCIPLINE — the risk cockpit panel (risk/SPEC.md §2, owner decision O-F3), a sub-view beside RSK › F&O
 * (FoRiskPanel mounts it behind its DISCIPLINE tab).
 *
 * Four cards: TODAY (arithmetic sums over GET /api/options/book/day), RULES (heuristic — the owner's house
 * rules with their rationale), the STAND DOWN state, and SETTINGS (the prefs editor; saved via the generic
 * prefs PUT, LWW, 409 → adopt the server value).
 *
 * Binding (SPEC §7): the cockpit never blocks a booking or any UI action, never reads the real broker balance
 * (BRKR stays the only place), never sends orders (none exist), and carries NO composite "discipline score".
 */
import { useEffect, useState } from 'react'
import { BadgeChip, Btn, Chip, Grid, Input, Label, Loading, Meter, Notice, Panel, Stat, T, inputSource, sourceOf, undatedSource } from '@/components/terminal'
import { useSecondTick } from '@/components/desktop/TitleStrip'
import {
  DEFAULT_SETTINGS, HOUSE_RULE_SUFFIX, bannerMain, capInr, inr, mmss, resetDateOf, ruleRows, warnInr,
  type DisciplineSettings,
} from './disciplineModel'
import { acknowledgeStandDown, refreshDay, saveSettings, useDiscipline } from './useDiscipline'

const FOOTNOTE = 'Counts the PAPER book only — log your real ICICI trades here (OSTR › Book paper) or today’s numbers are incomplete.'

const stateDot = (s: 'ok' | 'warn' | 'hit'): string => (s === 'hit' ? T.red : s === 'warn' ? T.amber : T.muted)

function RevengeCountdown({ until }: { until: number }) {
  const now = useSecondTick()
  if (now >= until) return null
  return (
    <div data-sd-revenge style={{ fontSize: 11, color: T.muted, fontFamily: T.mono }}>
      next paper booking in {mmss(until - now)} — your cooling rule
    </div>
  )
}

function TodayCard() {
  const d = useDiscipline()
  const s = d.settings
  const ev = d.ev
  const cap = s ? capInr(s) : null
  const warn = s ? warnInr(s) : null
  const meterColor = cap != null && ev.lossInr >= cap ? T.red : warn != null && warn > 0 && ev.lossInr >= warn ? T.amber : T.muted
  const src = d.day?.as_of ? sourceOf(d.day.as_of, { source: 'paper book' }) : undatedSource('paper book', 'the day read carries no as-of yet')
  return (
    <Panel title="Today" accent={T.cyan} badge="arithmetic" source={d.day ? src : null}
      subtitle={d.day ? `${d.day.date} · sums over the PAPER book's day read` : 'GET /api/options/book/day'}
      right={<Btn size="sm" onClick={refreshDay}>{d.dayLoading ? '…' : '↻'}</Btn>}>
      {!d.day && d.dayErr === 'pending' && (
        <Notice color={T.muted}>The day read (/api/options/book/day) is not on this ui-api yet — deploy pending. The rules below still show your settings.</Notice>
      )}
      {!d.day && d.dayErr && d.dayErr !== 'pending' && <Notice color={T.amber}>{d.dayErr}</Notice>}
      {!d.day && !d.dayErr && <Loading label="today's book" />}
      {d.day && (
        <div style={{ display: 'grid', gap: 10 }}>
          <Grid cols={4} min={150}>
            <Stat big={false} label="Realised today" value={inr(d.day.realised_inr)}
              sub={d.day.realised_inr == null ? 'no closes recorded today' : 'closed legs, net of costs'} />
            <Stat big={false} label="Open MTM change today" value={inr(d.day.mtm_change_inr)} sub="open legs vs the prior mark" />
            <Stat big={false} label="Trades today" value={`${ev.bookings} booked · ${ev.closes} closed`}
              sub={s ? `your rule: ${s.max_trades_per_day} a day (amber at ${s.trade_warn_at})` : 'set your capital to arm the rules'} />
            <Stat big={false} label="Consecutive losses" value={String(ev.streak)}
              sub={s ? `stand-down at ${s.consecutive_loss_standdown_n}` : '—'} />
          </Grid>
          <div>
            <Label>Today vs your daily cap {cap != null ? `· ${inr(-ev.lossInr)} of ${inr(cap)}` : ''}</Label>
            <div style={{ marginTop: 4 }}>
              {/* the meter is a position on the owner's own scale, not a buy/sell colour */}
              <Meter value={cap != null && cap > 0 ? ev.lossInr / cap : 0} color={meterColor} height={5} />
            </div>
            {cap == null && <div style={{ fontSize: 10, color: T.amber, marginTop: 4 }}>Set your trading capital in SETTINGS below: every rule is computed against it.</div>}
          </div>
          {ev.revengeUntil != null && <RevengeCountdown until={ev.revengeUntil} />}
          <div data-sd-today-footnote style={{ fontSize: 10, color: T.muted, lineHeight: 1.5, borderTop: `1px dashed ${T.border}`, paddingTop: 6 }}>
            {FOOTNOTE}
          </div>
        </div>
      )}
      {!d.day && <div data-sd-today-footnote style={{ fontSize: 10, color: T.muted, lineHeight: 1.5, marginTop: 8 }}>{FOOTNOTE}</div>}
    </Panel>
  )
}

function RulesCard() {
  const d = useDiscipline()
  const s = d.settings ?? DEFAULT_SETTINGS
  const rows = ruleRows(s, d.ev)
  return (
    <Panel title="Rules" accent={T.violet} badge="heuristic"
      source={inputSource('your own rules (SETTINGS below); no market feed behind this card')}
      subtitle={d.settings ? 'your own limits, reported back — nothing here blocks anything' : 'defaults shown — set your capital below to make them yours'}>
      <div style={{ display: 'grid', gap: 2 }}>
        {rows.map(r => (
          <div key={r.id} title={`${r.rationale} — ${HOUSE_RULE_SUFFIX}`} data-sd-rule={r.id}
            style={{ display: 'grid', gridTemplateColumns: '10px 1.2fr 1fr 1fr', gap: 10, alignItems: 'center',
                     padding: '5px 0', borderBottom: `1px dashed ${T.border}`, fontSize: 11 }}>
            <span style={{ width: 7, height: 7, borderRadius: 7, background: stateDot(r.state), justifySelf: 'center' }} />
            <span style={{ color: T.text }}>{r.label}</span>
            <span style={{ color: T.muted, fontFamily: T.mono, fontSize: 11 }}>{r.setting}</span>
            <span style={{ color: T.text, fontFamily: T.mono, fontSize: 11, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{r.current}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 6, lineHeight: 1.5 }}>
        Hover a row for the rationale. {HOUSE_RULE_SUFFIX}.
      </div>
    </Panel>
  )
}

function StandDownCard() {
  const d = useDiscipline()
  const rec = d.tripped ? d.standdown : null
  return (
    <Panel title="Stand down" accent={rec ? T.red : T.muted} badge="heuristic"
      source={inputSource('your stand-down record (settings store); no market feed behind this card')}
      subtitle="the state card — the banner on every page while un-acknowledged">
      {!rec && (
        <Notice color={T.muted}>
          OFF — no rule tripped this session{d.settings?.enabled === false ? ' (the cockpit is switched off in SETTINGS: trips are not evaluated)' : ''}.
        </Notice>
      )}
      {rec && (
        <div style={{ display: 'grid', gap: 8 }} data-sd-standdown-card={rec.rule}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Chip color={T.red} active>STAND DOWN</Chip>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text }}>{bannerMain(rec)}</span>
          </div>
          <div style={{ fontSize: 11, color: T.muted }}>
            {rec.detail} · tripped {new Date(rec.tripped_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false, hour: '2-digit', minute: '2-digit' })} IST
            · resets at the next session open (09:15 IST, {resetDateOf(rec.session)})
          </div>
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>
            Your rule, set below. Acknowledging collapses the banner to a header chip; nothing unlocks — the terminal never blocks (O-F3). It cannot be dismissed for the day.
          </div>
          {!rec.acknowledged && <div><Btn size="sm" onClick={acknowledgeStandDown}>ACKNOWLEDGE</Btn></div>}
        </div>
      )}
    </Panel>
  )
}

function SettingsCard() {
  const d = useDiscipline()
  const configured = d.settings != null
  const seedCapital = d.day?.capital?.value ?? DEFAULT_SETTINGS.trading_capital_inr
  const base: DisciplineSettings = d.settings ?? { ...DEFAULT_SETTINGS, trading_capital_inr: seedCapital }
  const [form, setForm] = useState<Record<string, string>>({})
  const [enabled, setEnabled] = useState(base.enabled)
  const [saved, setSaved] = useState(false)
  useEffect(() => { setEnabled(base.enabled) }, [base.enabled])
  const val = (k: keyof DisciplineSettings): string => form[k] ?? String(base[k])
  const set = (k: keyof DisciplineSettings) => (v: string) => { setSaved(false); setForm(f => ({ ...f, [k]: v })) }
  const n = (k: keyof DisciplineSettings, fallback: number): number => {
    const x = Number(val(k))
    return Number.isFinite(x) && x >= 0 ? x : fallback
  }
  const save = () => {
    saveSettings({
      trading_capital_inr: Math.max(1, n('trading_capital_inr', base.trading_capital_inr)),
      daily_loss_cap_pct: Math.max(0.1, n('daily_loss_cap_pct', base.daily_loss_cap_pct)),
      daily_loss_warn_pct: n('daily_loss_warn_pct', base.daily_loss_warn_pct),
      consecutive_loss_standdown_n: Math.max(1, Math.round(n('consecutive_loss_standdown_n', base.consecutive_loss_standdown_n))),
      max_trades_per_day: Math.max(1, Math.round(n('max_trades_per_day', base.max_trades_per_day))),
      trade_warn_at: Math.round(n('trade_warn_at', base.trade_warn_at)),
      revenge_timer_min: Math.round(n('revenge_timer_min', base.revenge_timer_min)),
      enabled,
    })
    setSaved(true)
  }
  return (
    <Panel title="Settings" accent={T.amber}
      subtitle="your rules, synced to every window and device (last write wins)"
      source={undatedSource('prefs', 'stored in your settings (ui_prefs), not a market feed')}>
      <div style={{ display: 'grid', gap: 10 }}>
        {!configured && (
          <Notice color={T.amber} >
            <b>Set your capital.</b> The default ₹{DEFAULT_SETTINGS.trading_capital_inr.toLocaleString('en-IN')} is a seed
            (the server&apos;s paper-capital default) — type your own trading capital: it is the denominator of every rule here.
            Deliberately separate from net worth and from the Desk&apos;s equity share.
          </Notice>
        )}
        <Grid cols={4} min={160}>
          <Input label="Trading capital ₹" value={val('trading_capital_inr')} onChange={set('trading_capital_inr')} aria-label="trading capital in rupees" />
          <Input label="Daily loss cap %" value={val('daily_loss_cap_pct')} onChange={set('daily_loss_cap_pct')} aria-label="daily loss cap percent" />
          <Input label="Amber warn %" value={val('daily_loss_warn_pct')} onChange={set('daily_loss_warn_pct')} aria-label="daily loss warn percent" />
          <Input label="Stand-down after N losses" value={val('consecutive_loss_standdown_n')} onChange={set('consecutive_loss_standdown_n')} aria-label="consecutive losses stand-down" />
          <Input label="Max trades / day" value={val('max_trades_per_day')} onChange={set('max_trades_per_day')} aria-label="max trades per day" />
          <Input label="Amber at N trades" value={val('trade_warn_at')} onChange={set('trade_warn_at')} aria-label="trade warn at" />
          <Input label="Cooling timer min (0 = off)" value={val('revenge_timer_min')} onChange={set('revenge_timer_min')} aria-label="cooling timer minutes" />
          <label style={{ display: 'grid', gap: 4, alignContent: 'start' }}>
            <Label>Cockpit</Label>
            <Chip color={enabled ? T.green : T.muted} active={enabled} onClick={() => { setSaved(false); setEnabled(v => !v) }}
              aria-label="cockpit enabled">{enabled ? 'ENABLED' : 'OFF'}</Chip>
          </label>
        </Grid>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Btn size="sm" variant="primary" onClick={save}>SAVE RULES</Btn>
          {saved && <Label color={T.green}>saved — every window follows</Label>}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: 10, color: T.dim }}>
            cap {inr(capInr({ ...base, trading_capital_inr: Math.max(1, n('trading_capital_inr', base.trading_capital_inr)), daily_loss_cap_pct: Math.max(0.1, n('daily_loss_cap_pct', base.daily_loss_cap_pct)) }))} a day at these values
          </span>
        </div>
        <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>
          Switching the cockpit off keeps this panel but stops the banner and the trips. {HOUSE_RULE_SUFFIX}.
        </div>
      </div>
    </Panel>
  )
}

/** The DISCIPLINE sub-view: TODAY · RULES · STAND DOWN · SETTINGS. */
export function Discipline() {
  return (
    <div style={{ display: 'grid', gap: 10 }} data-sd-discipline>
      <TodayCard />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 10 }}>
        <RulesCard />
        <StandDownCard />
      </div>
      <SettingsCard />
      <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>
        The cockpit reads the PAPER book and your own settings; it never blocks a booking, never reads the broker balance
        (BRKR stays the only place), and no order route exists. PAPER ONLY.
      </div>
    </div>
  )
}
