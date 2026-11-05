'use client'

import { apiError } from '@/lib/errors'
/**
 * SystemStatusWidget: service health (data-service, DuckDB, market-data provider),
 * quick refresh, and the ICICI Breeze credential form. Polled via AppContext every 30 s.
 */
import { useCallback, useState } from 'react'
import { useDataServiceStatus } from '@/context/AppContext'
import { configureDataProvider, fetchRefreshBatch } from '@/lib/api'
import { useToast } from '@/context/ToastContext'
import { Btn, Chip, Dot, Input, Label, Notice, Panel, T } from '@/components/terminal'

function Row({ label, ok, detail, pending }: { label: string; ok: boolean; detail: string; pending?: boolean }) {
  const c = pending ? T.amber : ok ? T.green : T.red
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: `1px dashed ${T.border}` }}>
      <Dot color={c} pulse={pending || ok} />
      <span style={{ fontSize: 12, color: T.text }}>{label}</span>
      <span style={{ flex: 1 }} />
      <span style={{ fontSize: 10, letterSpacing: 1, color: c, textTransform: 'uppercase' }}>{detail}</span>
    </div>
  )
}

export function SystemStatusWidget(_: { isDark?: boolean }) {
  const { dataServiceStatus: ds, refreshDataStatus } = useDataServiceStatus()
  const { addToast } = useToast()
  const [showConfig, setShowConfig] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [apiSecret, setApiSecret] = useState('')
  const [sessionToken, setSessionToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [quick, setQuick] = useState(false)
  const unknown = ds.lastChecked === null

  const save = useCallback(async () => {
    if (!apiKey || !apiSecret || !sessionToken) { addToast('All three ICICI fields are required', 'warning'); return }
    setSaving(true)
    try {
      await configureDataProvider({ api_key: apiKey, api_secret: apiSecret, session_token: sessionToken })
      addToast('ICICI Breeze credentials applied — provider reconnecting', 'success')
      setShowConfig(false)
      setTimeout(refreshDataStatus, 2000)
    } catch (err: any) {
      addToast(`Credential save failed: ${apiError(err, 'unknown error')}`, 'error')
    } finally { setSaving(false) }
  }, [apiKey, apiSecret, sessionToken, addToast, refreshDataStatus])

  const quickRefresh = useCallback(async () => {
    setQuick(true)
    try {
      const res = await fetchRefreshBatch({ tickers: ['RELIANCE', 'TCS', 'HDFCBANK'], years: 1 })
      const total = Object.values(res.data?.refreshed ?? {}).reduce((s: number, v: any) => s + (v as number), 0)
      addToast(`Quick refresh: ${total} rows updated`, 'success')
    } catch (err: any) {
      addToast(`Refresh failed: ${apiError(err)}`, 'error')
    } finally { setQuick(false) }
  }, [addToast])

  const provider = ds.provider
    ? ds.provider.replace('Provider', '').replace('ICICIBreeze', 'ICICI Breeze').replace('DirectYahoo', 'Yahoo v8').replace('YFinance', 'yFinance')
    : 'Unknown'

  return (
    <Panel title="System status"
      subtitle={ds.lastChecked ? `checked ${new Date(ds.lastChecked).toLocaleTimeString('en-IN', { hour12: false })}` : 'polling…'}
      right={<>
        <Btn size="sm" onClick={refreshDataStatus} title="Refresh service status">↻</Btn>
        <Btn size="sm" onClick={() => setShowConfig(v => !v)}>{showConfig ? 'Hide config' : '⚙ ICICI'}</Btn>
      </>}>
      <Row label="data-service" ok={ds.health === 'ok'} pending={unknown}
           detail={unknown ? 'polling' : ds.health === 'ok' ? 'healthy' : 'unreachable'} />
      <Row label="DuckDB" ok={ds.ready} pending={unknown} detail={unknown ? 'polling' : ds.ready ? 'mounted' : 'not ready'} />
      <Row label={`Live quotes · ${provider}`} ok={ds.connected} pending={unknown} detail={ds.connected ? 'connected' : 'disconnected'} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
        <Chip color={ds.connected ? T.green : T.amber} active>{ds.connected ? '● LIVE' : '○ FALLBACK'} · {provider}</Chip>
        {!ds.connected && <span style={{ fontSize: 10, color: T.muted }}>history from Yahoo v8</span>}
        <span style={{ flex: 1 }} />
        <Btn size="sm" onClick={quickRefresh} disabled={quick}>{quick ? 'Refreshing…' : '↻ Quick refresh (3)'}</Btn>
      </div>
      {showConfig && (
        <div style={{ marginTop: 12, display: 'grid', gap: 8, borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          <Label color={T.amber}>ICICI Breeze credentials</Label>
          <Notice>Session token rotates daily. Paste the full callback URL or just the token value.</Notice>
          <Input type="password" placeholder="API key" value={apiKey} onChange={setApiKey} />
          <Input type="password" placeholder="API secret" value={apiSecret} onChange={setApiSecret} />
          <Input placeholder="Session token (or full callback URL)" value={sessionToken} onChange={setSessionToken} />
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="go" onClick={save} disabled={saving}>{saving ? 'Applying…' : '✓ Apply & reconnect'}</Btn>
            <Btn onClick={() => setShowConfig(false)}>Cancel</Btn>
          </div>
        </div>
      )}
    </Panel>
  )
}
