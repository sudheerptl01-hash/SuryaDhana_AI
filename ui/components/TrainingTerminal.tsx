'use client'

import React, { useEffect, useRef, useState } from 'react'

interface LogLine {
  ts: string
  msg: string
  event: string
}

interface TrainingTerminalProps {
  jobId: string | null
  streamUrl: string       // e.g. "/api/pipeline/ml-stream/" or "/api/pipeline/rl-stream/"
  title?: string
  onDone?: (status: 'done' | 'error', error?: string) => void
}

export function TrainingTerminal({ jobId, streamUrl, title = 'TRAINING LOG', onDone }: TrainingTerminalProps) {
  const [lines, setLines] = useState<LogLine[]>([])
  const [connected, setConnected] = useState(false)
  const [finished, setFinished] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!jobId) {
      setLines([])
      setConnected(false)
      setFinished(false)
      return
    }

    setLines([{ ts: new Date().toISOString(), msg: `Connecting to ${streamUrl}${jobId}…`, event: 'system' }])
    setConnected(false)
    setFinished(false)

    const es = new EventSource(`${streamUrl}${jobId}`)
    esRef.current = es

    es.onopen = () => {
      setConnected(true)
      setLines(prev => [...prev, { ts: new Date().toISOString(), msg: 'SSE connected', event: 'system' }])
    }

    const handleMsg = (e: MessageEvent, eventType: string) => {
      try {
        const d = JSON.parse(e.data)
        setLines(prev => [...prev, { ts: d.ts || new Date().toISOString(), msg: d.msg || e.data, event: eventType }])
      } catch {
        setLines(prev => [...prev, { ts: new Date().toISOString(), msg: e.data, event: eventType }])
      }
    }

    es.addEventListener('log',    (e) => handleMsg(e as MessageEvent, 'log'))
    es.addEventListener('status', (e) => handleMsg(e as MessageEvent, 'status'))
    es.addEventListener('error',  (e) => handleMsg(e as MessageEvent, 'error'))
    es.addEventListener('done',   (e) => {
      handleMsg(e as MessageEvent, 'done')
      setFinished(true)
      es.close()
      try {
        const d = JSON.parse((e as MessageEvent).data)
        onDone?.(d.status === 'done' ? 'done' : 'error', d.error)
      } catch {
        onDone?.('done')
      }
    })

    es.onerror = () => {
      setLines(prev => [...prev, { ts: new Date().toISOString(), msg: 'Stream disconnected', event: 'error' }])
      setConnected(false)
      es.close()
    }

    return () => {
      es.close()
      esRef.current = null
    }
  }, [jobId, streamUrl])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  const lineColor = (event: string) => {
    if (event === 'done')   return 'text-emerald-400'
    if (event === 'error')  return 'text-red-400'
    if (event === 'system') return 'text-slate-500'
    if (event === 'status') return 'text-violet-400'
    return 'text-amber-300'
  }

  const statusDot = finished
    ? 'bg-emerald-500'
    : connected
    ? 'bg-amber-500 animate-pulse'
    : 'bg-slate-600'

  return (
    <div className="flex flex-col rounded border border-slate-700 bg-[#0a0e17] overflow-hidden">
      {/* Header bar */}
      <div className="flex items-center gap-2 border-b border-slate-700 bg-slate-900 px-3 py-1.5">
        <div className={`h-2 w-2 rounded-full ${statusDot}`} />
        <span className="font-mono text-[10px] text-slate-400 tracking-widest">{title}</span>
        {jobId && (
          <span className="ml-auto font-mono text-[9px] text-slate-600">{jobId.slice(0, 8)}</span>
        )}
      </div>

      {/* Log body */}
      <div className="h-56 overflow-y-auto px-3 py-2 font-mono text-[11px] leading-relaxed">
        {lines.length === 0 ? (
          <span className="text-slate-600">Waiting for job_id…</span>
        ) : (
          lines.map((l, i) => (
            <div key={i} className="flex gap-2">
              <span className="shrink-0 text-slate-600 text-[9px] pt-px">
                {l.ts.slice(11, 19)}
              </span>
              <span className={lineColor(l.event)}>{l.msg}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
