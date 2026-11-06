'use client'

/**
 * A research verdict read from the RSCH catalog at render time (GET /api/research/verdict, routers/research.py), so a
 * page footer or banner can never quote a superseded verdict (5 Nov 2026 review, M21: FUND said PROMISING while the
 * library said NO EDGE). The `fallback` verdict shows only while the catalog answers or when it cannot be reached,
 * marked as such.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { ResearchNote, T } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'

export interface StudyVerdict { id: string; title: string; area: string; verdict: string; kind: string; takeaway: string; updated: string }

type NoteVerdict = 'FAIL' | 'NO EDGE' | 'PROMISING' | 'PASS' | 'ADOPTED' | 'REFERENCE'
const NOTE_VERDICTS: readonly string[] = ['FAIL', 'NO EDGE', 'PROMISING', 'PASS', 'ADOPTED', 'REFERENCE']

const cache = new Map<string, Promise<StudyVerdict | null>>()

export function fetchStudyVerdict(id: string): Promise<StudyVerdict | null> {
  let p = cache.get(id)
  if (!p) {
    p = fetch(`/api/research/verdict?id=${encodeURIComponent(id)}`)
      .then(r => (r.ok ? (r.json() as Promise<StudyVerdict>) : null))
      .catch(() => null)
    cache.set(id, p)
    void p.then(v => { if (!v) cache.delete(id) })          // a failed read is retried on the next mount
  }
  return p
}

/** The catalog row for `id`: undefined while loading, null when the catalog could not be read. */
export function useStudyVerdict(id: string): StudyVerdict | null | undefined {
  const [v, setV] = useState<StudyVerdict | null | undefined>(undefined)
  useEffect(() => {
    let live = true
    setV(undefined)
    fetchStudyVerdict(id).then(x => { if (live) setV(x) })
    return () => { live = false }
  }, [id])
  return v
}

/** The verdict a note shows: the catalog's when known, else the page's fallback (ResearchNote takes six verdicts). */
export function noteVerdict(catalog: string | null | undefined, fallback: NoteVerdict): NoteVerdict {
  return catalog && NOTE_VERDICTS.includes(catalog) ? (catalog as NoteVerdict) : fallback
}

/** A RESEARCH · <verdict> banner whose verdict and bottom line come from the catalog. `children` is the page's own
 *  sentence about what the verdict means here; the catalog's takeaway follows it. */
export function CatalogNote({ id, fallback, children, showTakeaway = true }: {
  id: string; fallback: NoteVerdict; children?: ReactNode; showTakeaway?: boolean
}) {
  const v = useStudyVerdict(id)
  return (
    <ResearchNote verdict={noteVerdict(v?.verdict, fallback)} report={id}>
      {children}
      {v && showTakeaway && <span style={{ color: T.muted }}>{children ? ' ' : ''}RSCH: {v.takeaway}</span>}
      {v === null && <span style={{ color: T.dim }}> (research catalog unreachable: verdict as last known)</span>}
    </ResearchNote>
  )
}

/** One line of footer text: "RSCH › <title>: <VERDICT>. <takeaway>" from the catalog at render time. */
export function CatalogLine({ id, prefix }: { id: string; prefix?: ReactNode }) {
  const v = useStudyVerdict(id)
  return (
    <span data-rsch-verdict={v?.verdict ?? ''}>
      {prefix}
      <span role="button" tabIndex={0} onClick={() => goToPage('research', { research: id })}
        onKeyDown={e => { if (e.key === 'Enter') goToPage('research', { research: id }) }}
        style={{ color: T.cyan, cursor: 'pointer' }}>RSCH › {v?.title ?? id}</span>
      {v === undefined && ': reading the verdict…'}
      {v === null && ': the research catalog is unreachable; open the study for its verdict.'}
      {v && <>: <b style={{ color: v.verdict === 'FAIL' || v.verdict === 'NO EDGE' ? T.red : v.verdict === 'PROMISING' ? T.amber : T.text }}>{v.verdict}</b>. {v.takeaway}</>}
    </span>
  )
}
