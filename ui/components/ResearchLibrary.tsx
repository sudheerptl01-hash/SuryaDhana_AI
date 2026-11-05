'use client'

import { apiError } from '@/lib/errors'
/**
 * Research library (RSCH) — every study the project ran, its verdict and the full report, in one place.
 * Left: studies filtered by verdict / text. Right: the report (markdown) with its data files.
 * Data: /api/research (services/ui-api/routers/research.py). Verdicts are curated there, one line each.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getResearchDoc, listResearch, researchFileUrl, type ResearchEntry } from '@/lib/api'
import { Chip, ErrorBox, Input, Loading, PageHeader, Panel, T, sourceOf, referenceSource } from '@/components/terminal'
import { Markdown } from '@/components/terminal/Markdown'
import { downloadUrl, isDesktop } from '@/lib/platform'

export const VERDICT_COLOR: Record<string, string> = {
  ADOPTED: T.green, PASS: T.green, PROMISING: T.amber, FAIL: T.red, 'NO EDGE': T.red, REFERENCE: T.cyan,
}
const VERDICTS = ['ADOPTED', 'PASS', 'PROMISING', 'FAIL', 'NO EDGE', 'REFERENCE', 'DESCRIPTIVE', 'ARITHMETIC']
const SEL_KEY = 'suryadhana.rsch.sel.v1'

const ago = (iso: string) => {
  const d = (Date.now() - new Date(iso).getTime()) / 86_400_000
  return d < 1 ? 'today' : d < 2 ? 'yesterday' : d < 30 ? `${Math.floor(d)} days ago`
    : new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function ResearchLibrary() {
  const [list, setList] = useState<ResearchEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sel, setSel] = useState<string | null>(null)
  const [doc, setDoc] = useState<(ResearchEntry & { markdown: string }) | null>(null)
  const [docErr, setDocErr] = useState<string | null>(null)
  const [verdict, setVerdict] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [nonce, setNonce] = useState(0)

  const load = useCallback(async () => {
    try {
      const rows = (await listResearch()).data.data
      setList(rows); setError(null)
      let saved: string | null = null
      try { saved = localStorage.getItem(SEL_KEY) } catch { /* storage unavailable */ }
      setSel(s => s ?? (rows.some(r => r.id === saved) ? saved : rows[0]?.id ?? null))
    } catch (e: any) { setError(apiError(e, 'Research library unavailable')) }
  }, [])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!sel) return
    let live = true
    setDoc(null); setDocErr(null)
    try { localStorage.setItem(SEL_KEY, sel) } catch { /* storage unavailable */ }
    getResearchDoc(sel).then(r => live && setDoc(r.data))
      .catch(e => live && setDocErr(apiError(e, 'Could not load the report')))
    return () => { live = false }
  }, [sel, nonce])

  const shown = useMemo(() => (list ?? []).filter(r =>
    (!verdict || r.verdict === verdict) &&
    (!q.trim() || `${r.title} ${r.area} ${r.takeaway}`.toLowerCase().includes(q.trim().toLowerCase()))), [list, verdict, q])
  const counts = useMemo(() => Object.fromEntries(VERDICTS.map(v => [v, (list ?? []).filter(r => r.verdict === v).length])), [list])

  if (error && !list) return <div><PageHeader code="RSCH" title="Research Library" /><ErrorBox error={error} onRetry={load} /></div>
  if (!list) return <div><PageHeader code="RSCH" title="Research Library" /><Loading label="Loading studies" /></div>

  return (
    <div>
      <PageHeader code="RSCH" title="Research Library"
        subtitle={`${list.length} studies · pre-registered tests, real ICICI costs, out-of-sample holdouts`}
        right={<div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Chip color={T.muted} active={!verdict} onClick={() => setVerdict(null)}>ALL {list.length}</Chip>
          {VERDICTS.filter(v => counts[v]).map(v => (
            <Chip key={v} color={VERDICT_COLOR[v]} active={verdict === v} onClick={() => setVerdict(verdict === v ? null : v)}>
              {v} {counts[v]}
            </Chip>
          ))}
        </div>} />
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(300px, 380px) minmax(0, 1fr)', alignItems: 'start' }}>
        <Panel source={referenceSource('reports/*/FINDINGS.md')} title="Studies" pad={0} style={{ position: 'sticky', top: 8 }}
          right={<Input value={q} onChange={setQ} placeholder="Search…" width={150} />}>
          <div style={{ maxHeight: 'calc(100vh - 230px)', overflowY: 'auto' }}>
            {shown.map(r => {
              const on = r.id === sel
              const c = VERDICT_COLOR[r.verdict] ?? T.muted
              return (
                <button key={r.id} onClick={() => setSel(r.id)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer', padding: '10px 12px',
                           background: on ? T.panel3 : 'transparent', border: 'none', borderBottom: `1px solid ${T.border}`,
                           borderLeft: `2px solid ${on ? c : 'transparent'}` }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontFamily: T.mono, fontSize: 9, fontWeight: 700, letterSpacing: 1, color: c,
                                   border: `1px solid ${c}`, padding: '1px 5px' }}>{r.verdict}</span>
                    <span style={{ fontSize: 9.5, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{r.area}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{ fontSize: 9.5, color: T.dim }}>{ago(r.updated)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: on ? T.bright : T.text, fontWeight: 600, lineHeight: 1.35 }}>{r.title}</div>
                  {r.takeaway && <div style={{ fontSize: 10.5, color: T.muted, lineHeight: 1.5, marginTop: 3,
                                               display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {r.takeaway}</div>}
                </button>
              )
            })}
            {shown.length === 0 && <div style={{ padding: 16, fontSize: 11, color: T.muted }}>No study matches.</div>}
          </div>
        </Panel>

        <div style={{ minWidth: 0 }}>
          {docErr && <ErrorBox error={docErr} onRetry={() => setNonce(n => n + 1)} />}
          {!doc && !docErr && <Loading label="Opening report" />}
          {doc && (
            <Panel source={sourceOf(doc.updated ? String(doc.updated).slice(0, 10) : null, { source: 'study report', maxAgeDays: null })} accent={VERDICT_COLOR[doc.verdict] ?? T.amber}
              title={doc.area}
              subtitle={`${doc.id} · ${doc.lines} lines · updated ${ago(doc.updated)}`}
              right={<Chip color={VERDICT_COLOR[doc.verdict] ?? T.muted} active>{doc.verdict}</Chip>}
              pad={18}>
              {doc.takeaway && (
                <div style={{ border: `1px solid ${T.border}`, borderLeft: `3px solid ${VERDICT_COLOR[doc.verdict] ?? T.amber}`,
                              background: '#080b10', padding: '10px 14px', marginBottom: 18 }}>
                  <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, marginBottom: 4 }}>BOTTOM LINE</div>
                  <div style={{ fontSize: 13, color: T.bright, lineHeight: 1.6 }}>{doc.takeaway}</div>
                </div>
              )}
              <div style={{ maxWidth: 1100 }}><Markdown source={doc.markdown} /></div>
              {doc.data_files.length > 0 && (
                <div style={{ marginTop: 18, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
                  <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, marginBottom: 8 }}>
                    DATA FILES · {doc.data_files.length}
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {doc.data_files.map(f => (
                      <a key={f.name} href={researchFileUrl(doc.id, f.name)} download={f.name} style={{ textDecoration: 'none' }}
                         onClick={e => { if (isDesktop() && !e.defaultPrevented) { e.preventDefault(); void downloadUrl(researchFileUrl(doc.id, f.name), f.name) } }}>
                        <Chip color={T.cyan} style={{ cursor: 'pointer' }}>↓ {f.name} <span style={{ color: T.dim }}>{f.kb} KB</span></Chip>
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
