/**
 * The typed alert engine's HTTP client (ui-api /api/alerts/*; services/ui-api/routers/alerts.py). Relative paths, like
 * lib/api.ts, so the static release (ui-api :8010) and the Next dev server both reach ui-api. Read-only GETs plus the
 * owner's own rule edits; nothing here places an order (PAPER ONLY) or feeds a ticket price.
 *
 * Routes (documented in routers/alerts.py):
 *   GET  /api/alerts/series             the series kinds (params, unit, badge, ops, source, example)
 *   GET  /api/alerts/rules              every rule (typed + the price alerts) with summary and state
 *   POST /api/alerts/rules              create {series, op, value, window, cooldown_min, repeat, channel, note}
 *   PUT  /api/alerts/rules/{id}/action  {action: snooze | resume | pause | delete, minutes}
 *   GET  /api/alerts/rules/evaluate     each rule's current reading (a dry run: nothing fires)
 *   GET  /api/alerts/fires              the fired inbox, newest first, + grouped by symbol
 */
import axios from 'axios'
import type { AlertFire, AlertRule, AlertRuleDraft, DryRow, FireGroup, SeriesKind } from './alertsEngine'

const client = axios.create({ baseURL: '', timeout: 15000 })

export interface SeriesCatalog { kinds: SeriesKind[]; ops: string[]; op_words: Record<string, string>; pctile_window: number; max_rules: number; note: string }

export const getAlertSeries = () => client.get<SeriesCatalog>('/api/alerts/series')
export const getAlertRules = (origin: 'all' | 'rule' | 'price' = 'all') =>
  client.get<{ rules: AlertRule[]; count: number; as_of: string }>('/api/alerts/rules', { params: { origin } })
export const postAlertRule = (draft: AlertRuleDraft) => client.post<AlertRule>('/api/alerts/rules', draft)
export const alertRuleAction = (id: string, action: 'snooze' | 'resume' | 'pause' | 'delete', minutes?: number) =>
  client.put<AlertRule | { deleted: string }>(`/api/alerts/rules/${encodeURIComponent(id)}/action`, { action, minutes })
export const getAlertDryRun = () => client.get<{ rows: DryRow[]; as_of: string; note: string }>('/api/alerts/rules/evaluate', { timeout: 30000 })
export const getAlertFires = (limit = 200, symbol?: string) =>
  client.get<{ fires: AlertFire[]; groups: FireGroup[]; count: number; as_of: string }>('/api/alerts/fires', { params: { limit, symbol } })
