'use client'

import { apiError } from '@/lib/errors'
import { goToPage } from '@/lib/navigate'
import { useEffect, useMemo, useState, useCallback } from 'react'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { openTicker } from '@/lib/openTicker'
import { BasketRisk } from '@/components/BasketRisk'
import { openExternal } from '@/lib/platform'
import { ICICI_UNREACHABLE, iciciIssue, pickErrorKind } from '@/components/portfolio/iciciState'
import { IciciTotpPanel } from '@/components/gold/IciciTotpPanel'
import { BudgetPanel } from '@/components/brkr/BudgetPanel'
import type { TotpStatus } from '@/components/gold/totpModel'
import {
  Btn, Chip, DataTable, Empty, ErrorBox, Grid, Input, KV, Label, Loading, Meter, Notice, PageHeader, Panel, Stat, T,
  fmtInr, fmtPct, fmtSignedPct, tone, type Column, sourceOf, inputSource, referenceSource } from '@/components/terminal'
import {
  getICICIConnectionStatus,
  getPositionSummary,
  getOpenPositions,
  saveICICICredentials,
  updateSessionToken,
  getTradingConfig, getNewsQuotes } from '@/lib/api'

interface Summary {
  connected: boolean
  error?: string
  /** P4: 'expired' | 'network' | 'credentials' | 'unknown' on connected:false replies (components/portfolio/iciciState.ts) */
  error_kind?: string | null
  total_capital_inr: number
  cash_available_inr: number
  cash_readings_10m?: number[]
  funds?: Record<string, number>
  invested_value_inr: number
  num_open_positions: number
  total_pnl_inr: number
  total_pnl_pct: number
  as_of?: string
}

interface Position {
  symbol: string
  quantity: number
  buy_price: number
  current_price: number
  invested: number
  current_value: number
  pnl: number
  pnl_percent: number
  status?: string        // 'settled' | 'today (settles T+1)' | both
  icici_code?: string
}

interface ICICIConnectionStatus {
  connected: boolean
  error?: string
  /** P4: null when connected, else 'expired' | 'network' | 'credentials' | 'unknown' (read it before needs_session_refresh) */
  error_kind?: string | null
  account_name?: string
  has_api_key: boolean
  has_api_secret: boolean
  has_session_token: boolean
  has_client_id: boolean
  has_password: boolean
  needs_api_credentials: boolean
  needs_session_refresh: boolean
  login_url?: string | null
  token_hint?: string
  backend?: Record<string, { ok: boolean; body?: any; error?: string }>
}

export function PortfolioSummary() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  // today's % change per holding: ICICI's holdings call has no previous close. Live program (reports/live_nse): the live
  // NSE quote service (Breeze websocket → NSE ≈ 1 min → the last close; never Yahoo); the old 60 s quotes call runs only
  // while the live service does not answer
  const [dayChgOld, setDayChg] = useState<Record<string, number>>({})
  const holdKey = positions.map(p => p.symbol).sort().join(',')
  const liveH = useLiveQuotes(holdKey ? holdKey.split(',') : [], { intervalMs: 5_000 })
  const dayChg = useMemo(() => {
    if (!liveH.available) return dayChgOld
    const out: Record<string, number> = {}
    for (const [k, q] of Object.entries(liveH.quotes)) if (q.price != null && q.change_pct != null && q.state !== 'unavailable') out[k] = q.change_pct
    return out
  }, [liveH.available, liveH.quotes, dayChgOld])
  useEffect(() => {
    if (!holdKey || liveH.available) return
    const get = () => getNewsQuotes(holdKey.split(',').map(x => `${x}.NS`)).then(r => {
      const q = r.data.quotes; const out: Record<string, number> = {}
      for (const x of holdKey.split(',')) { const v = q[`${x}.NS`]; if (v?.available && v.change_pct != null) out[x] = v.change_pct }
      setDayChg(out)
    }).catch(() => {})
    get(); const iv = setInterval(get, 60_000); return () => clearInterval(iv)
  }, [holdKey, liveH.available])
  // value × chg / (1 + chg): rupee move today on what is held now (today's buys count from their buy price instead)
  const dayPnl = positions.reduce((a, p) => {
    const c = dayChg[p.symbol]; if (c == null) return a
    return a + ((p.status ?? '').startsWith('today') ? (p.current_value - p.invested) : p.current_value * (c / 100) / (1 + c / 100))
  }, 0)
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<ICICIConnectionStatus | null>(null)

  const [tradingConfig, setTradingConfig] = useState<Record<string, any> | null>(null)
  const [sessionToken, setSessionToken] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [connectMsg, setConnectMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [clientId, setClientId] = useState('')
  const [password, setPassword] = useState('')
  const [savingCredentials, setSavingCredentials] = useState(false)

  const loadConnectionStatus = useCallback(async () => {
    const res = await getICICIConnectionStatus()
    setConnectionStatus(res.data)
    return res.data as ICICIConnectionStatus
  }, [])

  const [loadError, setLoadError] = useState<string | null>(null)
  // BRKR "Auto-login (TOTP)" (PLAN §g): the panel reports its status so the "send /login" advice hides while a login runs
  const [totp, setTotp] = useState<TotpStatus | null>(null)
  const refresh = useCallback(async () => {
    // Independent requests: one Breeze hiccup must not blank the whole page
    const [statusRes, sumRes, posRes, cfgRes] = await Promise.allSettled([
      getICICIConnectionStatus(), getPositionSummary(), getOpenPositions(), getTradingConfig(),
    ])
    if (statusRes.status === 'fulfilled') setConnectionStatus(statusRes.value.data)
    if (sumRes.status === 'fulfilled') setSummary(sumRes.value.data)
    if (posRes.status === 'fulfilled') setPositions(posRes.value.data?.positions || [])
    if (cfgRes.status === 'fulfilled') setTradingConfig(cfgRes.value.data)
    const failed = [sumRes, posRes].find(r => r.status === 'rejected') as PromiseRejectedResult | undefined
    setLoadError(failed ? (apiError(failed.reason, 'Broker request failed')) : null)
    setLastRefresh(new Date())
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [refresh])

  const handleSaveCredentials = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) return
    setSavingCredentials(true)
    setConnectMsg(null)
    try {
      const res = await saveICICICredentials({
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        client_id: clientId.trim() || undefined,
        password: password.trim() || undefined,
      })
      setConnectionStatus(res.data?.status || null)
      setConnectMsg({
        ok: true,
        text: res.data?.status?.has_session_token
          ? 'Credentials saved. Checking existing session token now.'
          : 'Credentials saved. Press LOG IN TO ICICI below, then paste the redirect URL or token.',
      })
      await loadConnectionStatus()
    } catch (err: any) {
      setConnectMsg({ ok: false, text: apiError(err, 'Failed to save credentials.') })
    } finally {
      setSavingCredentials(false)
    }
  }

  const handleConnect = async () => {
    if (!sessionToken.trim()) return
    setConnecting(true)
    setConnectMsg(null)
    try {
      const res = await updateSessionToken(sessionToken.trim())
      if (res.data?.connected) {
        setConnectMsg({ ok: true, text: 'Connected. Syncing backend services and refreshing portfolio…' })
        setSessionToken('')
        await refresh()
      } else {
        setConnectMsg({ ok: false, text: res.data?.error || 'Connection failed. Check your token.' })
        await loadConnectionStatus()
      }
    } catch (err: any) {
      setConnectMsg({ ok: false, text: apiError(err, 'Failed to update token.') })
    } finally {
      setConnecting(false)
    }
  }

  // P4: why it is not connected. A network outage is not an expired session: no '/login' advice for it
  const issueKind = summary?.connected ? null : pickErrorKind(summary, connectionStatus)
  const issue = issueKind ? iciciIssue(issueKind, {
    fallback: connectionStatus?.error || summary?.error,
    keyMissing: connectionStatus ? !(connectionStatus.has_api_key && connectionStatus.has_api_secret) : true,
  }) : null
  const header = (
    <PageHeader code="BRKR" title="Broker Account"
      status={summary?.connected ? <Chip color={T.green} active>● LIVE · ICICI BREEZE</Chip>
        : <Chip color={T.amber} active title={issue?.headline}>{issue?.chip ?? 'NOT CONNECTED'}</Chip>}
      subtitle="real Demat holdings and funds (read-only; orders are never sent from here)"
      right={<>
        <span style={{ fontSize: 10, color: T.dim }}>refreshed {lastRefresh?.toLocaleTimeString('en-IN', { hour12: false }) ?? '—'} · every 15 s</span>
        <Btn size="sm" onClick={refresh}>↻</Btn>
      </>} />
  )
  const rules = (
    <Panel source={referenceSource('owner-approved Desk rules')} title="Rules that will govern live trading" subtitle="Decision Desk · owner-approved monthly rule set">
      <KV cols={2} items={[
        ['Positions', 'up to 20 · equal weight'], ['Per stock', '≤ 15% of capital'],
        ['Per industry', '≤ 40% of positions'], ['Equity share', '66% · rest in liquid fund'],
        ['Crash filter', 'NIFTY < 200-DMA → liquid fund'], ['Emergency stop', '−20% from peak'],
      ]} />
      {tradingConfig && (
        <div style={{ marginTop: 10, fontSize: 10, color: T.dim }}>
          Legacy 5-day engine settings (autopilot OFF): {tradingConfig.max_positions} positions · stop 2×ATR (volatility-adaptive, approved audit §3.4) ·
          time-stop {tradingConfig.holding_period_days} days · daily limit −{(tradingConfig.daily_loss_limit_pct * 100).toFixed(0)}%
        </div>
      )}
    </Panel>
  )

  if (loading) return <div>{header}<Loading label="Contacting ICICI Breeze" /></div>

  if (!summary?.connected) {
    const backendEntries = Object.entries(connectionStatus?.backend || {})
    const steps: [string, boolean | undefined][] = [
      ['API key', connectionStatus?.has_api_key], ['API secret', connectionStatus?.has_api_secret],
      ['Session', connectionStatus?.has_session_token], ['Client ID', connectionStatus?.has_client_id],
      ['Password', connectionStatus?.has_password],
    ]
    return (
      <div>
        {header}
        <div style={{ display: 'grid', gap: 10 }}>
          {loadError && <ErrorBox error={loadError} onRetry={refresh} />}
          <Panel source={inputSource('your ICICI credentials (never echoed)')} title="Connect ICICI Breeze" subtitle="checks the current connection first, then asks only for what is missing"
            right={<Btn size="sm" onClick={loadConnectionStatus}>Recheck</Btn>}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {steps.map(([label, ok]) => <Chip key={label} color={ok ? T.green : T.amber} active={!!ok}>{ok ? '✓' : '•'} {label}</Chip>)}
            </div>
            {issue?.kind === 'network' && (
              <div style={{ marginBottom: 10, fontSize: 12, color: T.amber }} data-icici-kind="network">
                {ICICI_UNREACHABLE}. No new login is needed: press Recheck when the network is back.</div>
            )}
            {connectionStatus?.needs_api_credentials || issue?.showCredentials ? (
              <div style={{ display: 'grid', gap: 8 }}>
                <Grid cols={2}>
                  <Input type="password" value={apiKey} onChange={setApiKey} placeholder="ICICI API key" />
                  <Input type="password" value={apiSecret} onChange={setApiSecret} placeholder="ICICI API secret" />
                  <Input value={clientId} onChange={setClientId} placeholder="ICICI client ID (optional)" />
                  <Input type="password" value={password} onChange={setPassword} placeholder="ICICI password (optional)" />
                </Grid>
                <div><Btn variant="primary" onClick={handleSaveCredentials} disabled={savingCredentials || !apiKey.trim() || !apiSecret.trim()}>
                  {savingCredentials ? 'Saving…' : 'Save API credentials'}</Btn></div>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 8 }}>
                {/* The login URL carries the API key: it opens in the browser and is never printed (C1-trader-ux-05) */}
                {/* P4: no login push while ICICI is unreachable (a new login would end a session that may still be valid) */}
                {connectionStatus?.login_url && issue?.suggestLogin !== false && (
                  <div style={{ border: `1px solid ${T.border}`, padding: 10, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <Label color={T.amber}>1 · Log in at ICICI</Label>
                    <Btn variant="primary" size="sm" onClick={() => openExternal(String(connectionStatus.login_url))}
                         title="Opens ICICI's login page in your browser">LOG IN TO ICICI ↗</Btn>
                    <span style={{ fontSize: 11, color: T.muted }}>after logging in, ICICI redirects to a page whose address holds the session token</span>
                  </div>
                )}
                <Label color={T.amber}>{connectionStatus?.login_url && issue?.suggestLogin !== false ? '2 · ' : ''}Paste the redirect URL or session token</Label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <div style={{ flex: 1 }} onKeyDown={e => e.key === 'Enter' && handleConnect()}>
                    <Input type="password" value={sessionToken} onChange={setSessionToken}
                           placeholder={connectionStatus?.token_hint || 'Paste ICICI redirect URL or session token…'} />
                  </div>
                  <Btn variant="go" onClick={handleConnect} disabled={connecting || !sessionToken.trim()}>{connecting ? 'Connecting…' : 'Connect'}</Btn>
                </div>
              </div>
            )}
            {connectMsg && <div style={{ marginTop: 10, fontSize: 12, color: connectMsg.ok ? T.green : T.red }}>{connectMsg.ok ? '✓ ' : '✕ '}{connectMsg.text}</div>}
          </Panel>
          <Notice>
            {/* P4: 'expired' / 'unknown' keep the server's text and the /login advice; 'network' and 'credentials' do not */}
            <b style={{ color: T.amber }}>{issue && issue.kind !== 'expired' && issue.kind !== 'unknown' ? issue.headline
              : connectionStatus?.error || summary?.error || 'Credentials not configured'}</b>
            {issue?.detail && <div style={{ marginTop: 4, color: T.text }}>{issue.detail}</div>}
            <div style={{ marginTop: 4, color: T.muted }}>Meanwhile your last-known holdings are priced live on
              <span role="button" onClick={() => goToPage('watch')} style={{ color: T.cyan, cursor: 'pointer' }}> WTCH › (P&L, book X-ray)</span>.</div>
            {(issue?.suggestLogin ?? true) && !totp?.login_running && <div style={{ marginTop: 4, color: T.muted }}>Or send /login to the Telegram bot: it logs in to ICICI and asks you for the SMS OTP{totp?.configured ? ' (with the authenticator registered below, the 08:00 job needs no OTP)' : ''}.</div>}
            {!!totp?.login_running && <div style={{ marginTop: 4, color: T.cyan }}>An auto-login is running right now — wait for it before sending /login.</div>}
          </Notice>
          <IciciTotpPanel connected={false} onSessionLive={refresh} onStatus={setTotp} />
          {/* F13: the budget panel needs no broker session — it reads the ledger's own counters. It belongs
              HERE most of all: a day with no session is exactly when the owner wants to know whether the
              budget refused the login, and the chip's hover sends them to this page to find out. */}
          <Panel title="Broker budget" subtitle="Breeze calls today, by caller — the quota the chip refers to"
            source={sourceOf(new Date().toISOString(), { source: 'ui-api budget ledger', maxAgeDays: 1 })}>
            <BudgetPanel />
          </Panel>
          {backendEntries.length > 0 && (
            <Panel source={sourceOf(lastRefresh ? lastRefresh.toISOString() : null, { source: 'ICICI sync', maxAgeDays: 1 })} title="Backend sync status">
              <KV items={backendEntries.map(([name, info]) => {
                // the execution service is not part of the local paper stack (the Desk runs in data-service): not an alarm
                const optional = name === 'execution_service' && !info.ok
                return [name.replace('_', ' '), info.ok ? 'in sync' : optional ? 'not running · not needed in PAPER mode' : (info.error || 'unavailable'),
                        info.ok ? T.green : optional ? T.muted : T.red] as [string, string, string]
              })} />
            </Panel>
          )}
          {rules}
        </div>
      </div>
    )
  }

  const isProfit = summary.total_pnl_inr >= 0
  const investedPct = summary.total_capital_inr > 0 ? (summary.invested_value_inr / summary.total_capital_inr) * 100 : 0
  const posCols: Column<Position>[] = [
    { key: 'symbol', label: 'Symbol', sort: r => r.symbol,
      render: r => <span style={{ color: T.amber, fontWeight: 600 }} title={r.icici_code ? `ICICI code ${r.icici_code}` : undefined}>{r.symbol}</span> },
    { key: 'quantity', label: 'Qty', align: 'right', sort: r => r.quantity },
    { key: 'buy_price', label: 'Avg cost', align: 'right', render: r => fmtInr(r.buy_price, 2) },
    { key: 'current_price', label: 'LTP', align: 'right', render: r => fmtInr(r.current_price, 2) },
    { key: 'day', label: 'Today', align: 'right', sort: r => dayChg[r.symbol] ?? -999,
      render: r => dayChg[r.symbol] == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: tone(dayChg[r.symbol]) }} title={liveH.lineFor(r.symbol) ?? 'quotes route (the live NSE quote service is not answering)'}>{fmtSignedPct(dayChg[r.symbol])}</span> },
    { key: 'current_value', label: 'Value', align: 'right', sort: r => r.current_value, render: r => fmtInr(r.current_value) },
    { key: 'pnl', label: 'P&L', align: 'right', sort: r => r.pnl, render: r => <span style={{ color: tone(r.pnl) }}>{fmtInr(r.pnl)}</span> },
    { key: 'pnl_percent', label: 'Return', align: 'right', sort: r => r.pnl_percent,
      render: r => <span style={{ color: tone(r.pnl_percent) }}>{fmtSignedPct(r.pnl_percent)}</span> },
    { key: 'status', label: 'Status', sort: r => r.status ?? '',
      render: r => <span style={{ color: (r.status ?? '').startsWith('today') ? T.cyan : T.muted }}
                         title="Shares bought today show in ICICI positions until they settle into your demat (T+1)">
                     {r.status ?? 'settled'}</span> },
  ]
  return (
    <div>
      {header}
      <div style={{ display: 'grid', gap: 10 }}>
        {loadError && <ErrorBox error={`${loadError} (showing the last good values)`} onRetry={refresh} />}
        <Grid cols={4}>
          <Stat label="Total portfolio" value={fmtInr(summary.total_capital_inr, 2)} sub="cash + holdings at cost" accent={T.amber} />
          <Stat label="Invested" value={fmtInr(summary.invested_value_inr, 2)} sub={`${investedPct.toFixed(1)}% deployed`} accent={T.violet} />
          <Stat label="Cash available" value={fmtInr(summary.cash_available_inr, 2)} accent={T.cyan}
            sub={(summary.cash_readings_10m?.length ?? 0) > 1
              ? <span style={{ color: T.amber }} title="ICICI's funds API returned different free-cash figures between refreshes (part of the balance shown as allocated and blocked on some calls). Check ICICI Direct before acting.">
                  ⚠ ICICI reported {summary.cash_readings_10m!.map(v => fmtInr(v)).join(' / ')} in the last 10 min</span>
              : summary.funds?.stale ? <span style={{ color: T.amber }}>last good reading · ICICI's funds call just failed</span> : 'ready to invest'} />
          <Stat label="Unrealised P&L" value={fmtInr(summary.total_pnl_inr, 2)} color={tone(summary.total_pnl_inr)}
                sub={<span>{`${fmtPct(summary.total_pnl_pct, 2)} on invested`}{Object.keys(dayChg).length > 0 &&
                  <span style={{ color: tone(dayPnl) }} title={liveH.available && liveH.source ? `day move from live NSE quotes: ${liveH.source.hint ?? ''}` : 'day move from the quotes route (the live NSE quote service is not answering)'}> · today {dayPnl >= 0 ? '+' : '−'}{fmtInr(Math.abs(dayPnl))}</span>}</span>}
                accent={isProfit ? T.green : T.red} />
        </Grid>
        <Panel source={sourceOf(summary?.as_of ?? null, { source: 'ICICI funds', maxAgeDays: 1 })} title="Capital allocation">
          <div style={{ display: 'grid', gap: 10 }}>
            <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: T.muted, marginBottom: 4 }}>
              <span>INVESTED {investedPct.toFixed(1)}%</span><span>{fmtInr(summary.invested_value_inr)}</span></div>
              <Meter value={investedPct / 100} color={T.violet} height={6} /></div>
            <div><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: T.muted, marginBottom: 4 }}>
              <span>CASH {(100 - investedPct).toFixed(1)}%</span><span>{fmtInr(summary.cash_available_inr)}</span></div>
              <Meter value={(100 - investedPct) / 100} color={T.green} height={6} /></div>
          </div>
        </Panel>
        <Panel source={sourceOf(summary?.as_of ?? null, { source: 'ICICI demat', maxAgeDays: 1 })} title={`Open positions (${positions.length})`} subtitle="Demat holdings from ICICI Breeze" pad={0}>
          <DataTable columns={posCols} rows={positions} rowKey={r => r.symbol} onRowClick={r => openTicker(r.symbol)}
            empty={<Empty title="No active holdings in your Demat account" icon="◇" />} />
        </Panel>
        {positions.length >= 2 && (
          <BasketRisk title="Holdings risk" symbols={positions.map((p: any) => String(p.symbol).toUpperCase())}
            weights={Object.fromEntries(positions.map((p: any) => [String(p.symbol).toUpperCase(), Number(p.current_value ?? p.invested ?? 0)]))} />
        )}
        <IciciTotpPanel connected onSessionLive={refresh} onStatus={setTotp} />
        {/* F12: the BRKR chip's hover promised "the BRKR page shows which caller spent the quota" and this
            page showed nothing of the kind — by_caller, remaining_day and refused_today had no reader
            anywhere in ui/. Credential-free counters only. */}
        <Panel title="Broker budget" subtitle="Breeze calls today, by caller — the quota the chip refers to"
          source={sourceOf(new Date().toISOString(), { source: 'ui-api budget ledger', maxAgeDays: 1 })}>
          <BudgetPanel />
        </Panel>
        {rules}
      </div>
    </div>
  )
}
