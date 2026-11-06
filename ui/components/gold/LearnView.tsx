'use client'

/**
 * GOLD › LEARN (reports/gold_program/PLAN.md §e): zero-to-professional, in reading order.
 *
 * Top: the Part 9 routines (daily / weekly / monthly) as three collapsible lists with deep links to the sub-view that
 * holds each panel. Then: the known corrections to the G-EDU text (duty 15 % dated, Part 8 renames, evidence ledger),
 * the curriculum parts as collapsible sections rendered through the kit's Markdown (never raw HTML), "what is not free
 * and where to click", the Bloomberg function map ("what a Bloomberg gold trader looks at → where it is here"), the
 * Part 8 → panel-id map, and the health-verdict rule table (every clause with its threshold, so the owner can audit the
 * sentence). Right-hand side: the glossary panel with search (inline here; docked on the other views).
 *
 * The curriculum is read through the existing research document viewer (`/api/research/doc?id=…`, read-only from
 * `reports/`; `routers/research.py` carries the CATALOG row for G-EDU/CURRICULUM.md). The [B]/[P] toggle filters the
 * curriculum's `**[B]**` / `**[P]**` paragraphs when "only [layer] copy" is on.
 */
import { useMemo, useState, type ReactNode } from 'react'
import { Chip, Label, Loading, Notice, T } from '@/components/terminal'
import { Markdown } from '@/components/terminal/Markdown'
import { getResearchDoc } from '@/lib/api'
import { HEALTH_SUFFIX, healthLine } from '@/lib/gold/format'
import type { GoldSubViewProps } from '@/lib/gold/types'
import { BBG_MAP, NOT_FREE, PART8_RENAME, PARTS_RENDERED_AS_PANELS, ROUTINES, activeCorrections, describeStep, filterLayerParagraphs, parseCurriculum, parseRoutines, shortPanelTitle, type CurriculumPart, type Routine, type RoutineTarget } from '@/lib/gold/learn'
import { GlossaryPanel } from './GlossaryPanel'
import { Degraded, GPanel, LinkTile, Term, useGoldLoad } from './ViewBits'
import { usePageHealth } from './kit'
import { thresholdText } from './goldViewModel'

export const CURRICULUM_ID = 'reports/gold_program/G-EDU/CURRICULUM.md'

function Section({ title, open, children, id }: { title: ReactNode; open?: boolean; children: ReactNode; id?: string }) {
  return (
    <details open={open} data-learn-section={id} style={{ border: `1px solid ${T.border}`, background: T.panel }}>
      <summary style={{ cursor: 'pointer', padding: '7px 12px', fontFamily: T.display, fontSize: 12, fontWeight: 600, letterSpacing: 1.2, color: T.amber, textTransform: 'uppercase', listStyle: 'none' }}>▸ {title}</summary>
      <div style={{ padding: '6px 12px 10px' }}>{children}</div>
    </details>
  )
}

/** "POSITIONING ›" — opens the sub-view that holds the panel a routine step or a Bloomberg row points at. */
function NavChip({ sub, onNavigate, title }: { sub: RoutineTarget; onNavigate: GoldSubViewProps['onNavigate']; title?: string }) {
  return (
    <span role="button" tabIndex={0} data-nav={sub} onClick={() => onNavigate(sub)} onKeyDown={e => { if (e.key === 'Enter') onNavigate(sub) }}
      style={{ color: T.cyan, cursor: 'pointer', fontSize: 10, fontFamily: T.mono }} title={title}>{sub.toUpperCase()} ›</span>
  )
}

export function LearnView(props: GoldSubViewProps) {
  const { layer, onNavigate, catalog } = props
  const doc = useGoldLoad(() => getResearchDoc(CURRICULUM_ID), [])
  // the SAME verdict HEALTH prints (wave 1e, M-A): the overview's health block for the picked contract, live quote applied
  const health = usePageHealth({ overview: props.overview, overviewStatus: props.overviewStatus, window: props.window, sel: props.sel })
  // Appendix E / F (what is not free; the Bloomberg map) are rendered as the two panels below, not twice
  const parts = useMemo<CurriculumPart[]>(() => (doc.data?.markdown ? parseCurriculum(doc.data.markdown).filter(p => !PARTS_RENDERED_AS_PANELS.test(p.title)) : []), [doc.data])
  // the builder-speak notes (Part 8 panel ids) are [P]-only (C-BEGINNER-23)
  const corrections = useMemo(() => activeCorrections(doc.data?.markdown, layer), [doc.data, layer])
  // the routines come from the document's own Part 9 when it has loaded; the bundled mirror is the fallback
  const routines = useMemo<{ list: readonly Routine[]; live: boolean }>(() => {
    const live = doc.data?.markdown ? parseRoutines(doc.data.markdown) : []
    return live.length === 3 ? { list: live, live: true } : { list: ROUTINES, live: false }
  }, [doc.data])
  const [onlyLayer, setOnlyLayer] = useState(false)
  const filterBody = (body: string): string => (onlyLayer ? filterLayerParagraphs(body, layer) : body)
  const h = health.data
  const line = healthLine(h?.verdict?.line ?? h?.line)

  return (
    <div data-gold-b4b="learn" style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1.7fr) minmax(300px, 1fr)', alignItems: 'start' }}>
      <div style={{ display: 'grid', gap: 10, minWidth: 0 }}>
        {/* routines — the "days, weeks, months" reading order */}
        <GPanel id="learn.routines" title="Reading routines — days, weeks, months" series={[]} catalog={catalog} layer={layer}
          subtitle={`CURRICULUM Part 9 (${routines.live ? 'live from the document' : 'bundled mirror'}) · each step names the panel in words and opens the view that holds it (hover for the panel id)`}
          copyB="what to read and in which order, before the MCX open, on Saturday and on the first weekend of the month."
          copyP="the routines are the owner's 'days, weeks, months' as a reading order; nothing in them is a rule to trade on.">
          <div style={{ display: 'grid', gap: 6 }} data-routines={routines.live ? 'live' : 'bundled'}>
            {routines.list.map(r => (
              <details key={r.id} open={r.id === 'daily'} data-routine={r.id}>
                <summary style={{ cursor: 'pointer', fontSize: 11.5, color: T.bright }}>{r.title} <span style={{ color: T.muted }}>· {r.when}</span></summary>
                <ol style={{ margin: '6px 0 0', paddingLeft: 20, fontSize: 11.5, lineHeight: 1.7, color: T.text }}>
                  {r.steps.map((s, i) => (
                    <li key={i} data-routine-step>
                      {/* panel ids become titles a novice can read; the id stays in the title= of each (C-BEGINNER-8); the view
                          name is not repeated because Part 9 already writes it beside the id ("(`h.verdict`, HEALTH)") */}
                      {describeStep(s.text).map((part, j) => part.kind === 'panel'
                        ? <span key={j} data-panel-ref={part.id} title={`panel ${part.id} — ${part.title}`} style={{ color: T.bright, borderBottom: `1px dotted ${T.dim}` }}>{shortPanelTitle(part.id)}</span>
                        : <span key={j}>{part.text}</span>)}
                      {' '}<NavChip sub={s.sub} onNavigate={onNavigate} title={s.panel ? `panel ${s.panel}` : undefined} />
                    </li>
                  ))}
                </ol>
                {r.evening && <div style={{ fontSize: 10.5, color: T.muted, marginTop: 4 }}>{r.evening}</div>}
              </details>
            ))}
          </div>
        </GPanel>

        {/* corrections — only the ones the loaded document still needs */}
        {corrections.length > 0 && (
          <Notice color={T.amber}>
            <b style={{ color: T.amber }}>Notes on the curriculum text</b>
            <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 11, lineHeight: 1.6 }} data-corrections={corrections.length}>
              {corrections.map(c => <li key={c.where}><b style={{ color: T.text }}>{c.where}:</b> {c.text}</li>)}
            </ul>
          </Notice>
        )}

        {/* curriculum */}
        <GPanel id="learn.curriculum" title="Gold, zero to professional" series={[]} catalog={catalog} layer={layer}
          subtitle={doc.data ? `${doc.data.lines ?? '?'} lines · updated ${doc.data.updated ? new Date(doc.data.updated).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—'}` : 'G-EDU CURRICULUM.md through the research viewer'}
          copyB="Parts 0–9 in order: units, venues, futures mechanics, the players, the drivers, reading the data, advanced topics, panel micro-copy, routines. Open a part, then a section."
          copyP="every claim in Parts 5–7 points at a SOURCES.md entry or a FINDINGS row; the [B]/[P] markers in the text are the two layers of the page toggle."
          right={<Chip color={T.muted} active={onlyLayer} onClick={() => setOnlyLayer(v => !v)} title={layer === 'B' ? 'Only the [B] paragraphs and the app notes: tables, code and the unmarked pro paragraphs are hidden' : 'Hide the [B] paragraphs; everything else stays'}>only [{layer}] copy</Chip>}>
          <Degraded error={doc.error} what="curriculum (research router: the CATALOG row for G-EDU/CURRICULUM.md)" />
          {!doc.data && !doc.error && <Loading label="Opening the curriculum" />}
          {parts.length > 0 && (
            <div style={{ display: 'grid', gap: 6 }}>
              {parts.map((p, i) => (
                <Section key={p.id} id={p.id} title={p.title} open={i === 0}>
                  {p.intro.trim() && <Markdown source={filterBody(p.intro)} />}
                  {p.sections.map(s => (
                    <details key={s.id} style={{ marginTop: 4 }} data-learn-subsection={s.id}>
                      <summary style={{ cursor: 'pointer', fontSize: 12, color: T.bright }}>{s.title}</summary>
                      <div style={{ paddingLeft: 8 }}><Markdown source={filterBody(s.body)} /></div>
                    </details>
                  ))}
                </Section>
              ))}
            </div>
          )}
          <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>Literature citations in Parts 5–7 are from memory or SSRN-blocked pages and are not live-verified (open question j.2 #15).</div>
        </GPanel>

        {/* not free */}
        <GPanel id="learn.notfree" title="What is not free, and where to click" series={[]} catalog={catalog} layer={layer} subtitle="CURRICULUM Appendix E, as link tiles"
          copyB="the sources this terminal links to instead of reading: paid, licensed or bot-walled."
          copyP="LINK-ONLY per SOURCES.md; the stack never fetches these hosts (test T8).">
          <div style={{ display: 'grid', gap: 6 }}>
            {NOT_FREE.map(l => <LinkTile key={l.url} name={l.name} url={l.url} why={l.why} />)}
          </div>
        </GPanel>

        {/* bloomberg map */}
        <GPanel id="learn.bbg" title="What a Bloomberg gold trader looks at → where it is here" series={[]} catalog={catalog} subtitle="CURRICULUM Appendix F (G-KITCO Appendix C; public guides, unverified on a terminal), with deep links" pad={0} layer={layer}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: T.muted, fontSize: 9.5, textAlign: 'left' }}><th style={{ padding: '5px 10px' }}>FUNCTION</th><th>WHAT</th><th style={{ padding: '5px 10px' }}>HERE</th></tr></thead>
            <tbody>
              {BBG_MAP.map(r => (
                <tr key={r.fn} style={{ borderTop: `1px solid ${T.border}` }}>
                  <td style={{ padding: '5px 10px', fontFamily: T.mono, color: T.amber, whiteSpace: 'nowrap' }}>{r.fn}</td>
                  <td style={{ color: T.text }}>{r.what}</td>
                  <td style={{ padding: '5px 10px', color: T.muted }}>{r.here} <NavChip sub={r.sub} onNavigate={onNavigate} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </GPanel>

        {/* part 8 rename map */}
        <GPanel id="learn.rename" title="Where each panel went (Part 8 → panel ids)" series={[]} catalog={catalog} pad={0} layer={layer}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', fontSize: 10.5 }}>
            {PART8_RENAME.map(([from, to]) => (
              <div key={from} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '3px 10px', borderBottom: `1px dashed ${T.border}` }}>
                <span style={{ color: T.muted }}>{from}</span><span style={{ fontFamily: T.mono, color: T.text, textAlign: 'right' }}>{to}</span>
              </div>
            ))}
          </div>
        </GPanel>

        {/* health verdict rules */}
        <GPanel id="learn.health_rules" title="How the health verdict is built" series={[]} catalog={catalog} subtitle={`every clause is a threshold on a stored series; the sentence ends “${HEALTH_SUFFIX}”`} layer={layer}
          copyB="the sentence on HEALTH is assembled from these rules; read the threshold next to each clause."
          copyP="rule_id · series · value · threshold per clause; stale gauges are excluded; no score, no composite (PLAN §f.4).">
          <Degraded error={health.error} what="health rules" />
          {h ? (
            <>
              <div style={{ fontSize: 11.5, color: T.text, marginBottom: 6 }} data-health-line>{line}</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10.5, fontFamily: T.mono }}>
                <thead><tr style={{ color: T.muted, fontSize: 9.5, textAlign: 'left' }}><th>RULE</th><th>SERIES</th><th style={{ textAlign: 'right' }}>VALUE</th><th style={{ textAlign: 'right' }}>THRESHOLD</th><th>CLAUSE</th></tr></thead>
                <tbody>
                  {h.verdict.clauses.map(c => (
                    <tr key={c.rule_id} style={{ borderTop: `1px solid ${T.border}` }}>
                      <td style={{ color: T.amber }}>{c.rule_id}</td><td style={{ color: T.muted }}>{c.series_id ?? '—'}</td>
                      {/* HEALTH_RULES thresholds are objects ({weak_pct, strong_pct, flat_pct} …): printed as text, never as a React child */}
                      <td style={{ textAlign: 'right' }}>{thresholdText(c.value)}</td><td style={{ textAlign: 'right' }} data-rule-threshold>{thresholdText(c.threshold)}</td><td style={{ color: T.text }}>{c.text}</td>
                    </tr>
                  ))}
                  {h.verdict.clauses.length === 0 && <tr><td colSpan={5} style={{ padding: 8, color: T.dim }}>no clauses in this release yet</td></tr>}
                </tbody>
              </table>
            </>
          ) : !health.error && <Loading label="Health rules" />}
          <div style={{ fontSize: 10.5, color: T.muted, marginTop: 8 }}>
            Vocabulary: <Term t="evidence badge">signal · context · arithmetic · heuristic</Term>; no composite score, no “N of 7”; a badge changes only by a PASS row in FINDINGS.md from a pre-registered, <Term t="point-in-time" /> study.
          </div>
        </GPanel>
      </div>

      <div style={{ position: 'sticky', top: 8 }}>
        <Label color={T.muted}>glossary</Label>
        <GlossaryPanel inline />
      </div>
    </div>
  )
}

export default LearnView
