/**
 * mlTraining.ts — typed NDJSON streaming client for the ML Engine Workspace.
 *
 * Mirrors the Backtest Lab's streaming contract: POST /api/ml/train/stream emits
 * a newline-delimited sequence  accepted → start → epoch* → (result | error).
 * The kill-switch is a separate POST /api/ml/stop keyed by the run_id handed back
 * in the `accepted` frame, so STOP works even before the first boosting round.
 */

export interface TrainParams {
  mode: 'sample' | 'production'
  tickers?: string[]
  from_date?: string | null
  to_date?: string | null
  n_estimators?: number
  max_depth?: number
  learning_rate?: number
  subsample?: number
  colsample_bytree?: number
  valid_fraction?: number
}

export interface AcceptedEvent { event: 'accepted'; run_id: string; mode: string }

export interface StartEvent {
  event: 'start'
  run_id: string
  mode: string
  n_samples: number
  n_train: number
  n_valid: number
  n_features: number
  features: string[]
  up_rate: number
  total_rounds: number
  train_span: [string, string]
  valid_span: [string, string]
}

export interface EpochEvent {
  event: 'epoch'
  iteration: number
  train_logloss: number | null
  valid_logloss: number | null
  valid_auc: number | null
  gini: number | null
  elapsed: number
}

export interface ResultEvent {
  event: 'result'
  run_id: string
  status: 'COMPLETED' | 'TERMINATED_BY_USER'
  mode: string
  rounds_completed: number
  rounds_requested: number
  up_rate: number
  model_path: string | null
  feature_importance: { feature: string; gain: number }[]
  n_valid: number
  valid_auc: number | null
  gini: number | null
  valid_logloss: number | null
  accuracy: number | null
  confusion: { tp: number; fp: number; tn: number; fn: number }
  mode_flag: string
}

export interface StreamHandlers {
  onAccepted?: (e: AcceptedEvent) => void
  onStart?: (e: StartEvent) => void
  onEpoch?: (e: EpochEvent) => void
  onResult?: (e: ResultEvent) => void
  onError?: (detail: string) => void
  signal?: AbortSignal
}

/** Start a training run and dispatch each NDJSON frame to the matching handler. */
export async function streamTraining(params: TrainParams, h: StreamHandlers): Promise<void> {
  const res = await fetch('/api/ml/train/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: h.signal,
  })
  if (!res.ok || !res.body) {
    let detail = `Training request failed (${res.status})`
    try { detail = (await res.json()).detail || detail } catch { /* keep default */ }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (!line) continue
      let evt: any
      try { evt = JSON.parse(line) } catch { continue }
      switch (evt.event) {
        case 'accepted': h.onAccepted?.(evt as AcceptedEvent); break
        case 'start':    h.onStart?.(evt as StartEvent); break
        case 'epoch':    h.onEpoch?.(evt as EpochEvent); break
        case 'result':   h.onResult?.(evt as ResultEvent); break
        case 'error':    h.onError?.(evt.detail as string); break
      }
    }
  }
}

/** Kill-switch: signal a run to stop at the next round boundary (model preserved). */
export async function stopRun(runId: string): Promise<void> {
  await fetch('/api/ml/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId }),
  }).catch(() => { /* best-effort; the aborted stream also ends the run */ })
}
