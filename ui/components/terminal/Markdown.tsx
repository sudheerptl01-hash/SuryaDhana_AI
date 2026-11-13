'use client'

/**
 * Minimal GitHub-flavoured markdown → React, in the terminal style. Covers what the research reports use:
 * headings, paragraphs, bullet/numbered lists, pipe tables, fenced code, block quotes, rules, and inline
 * **bold**, *italic*, `code` and [links](url). Builds React nodes (never raw HTML), so report text cannot inject markup.
 */
import { Fragment, type ReactNode } from 'react'
import { T } from './index'
import { inlineTokens } from './mdInline'

const NUM_CELL = /^[\s+\-−–]*[₹$]?[\d.,]+\s*(%|pp|R|×|x|bp|bps|cr|Cr)?\s*(\(.*\))?$/

function inline(text: string, key = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0, n = 0
  for (const m of inlineTokens(text)) {          // RUP-07: tokenizer without a regex lookbehind (mdInline.ts)
    if (m.start > last) out.push(text.slice(last, m.start))
    const t = m.text, k = `${key}-${n++}`
    if (t.startsWith('**')) out.push(<b key={k} style={{ color: T.bright, fontWeight: 600 }}>{inline(t.slice(2, -2), k)}</b>)
    else if (t.startsWith('`')) out.push(
      <code key={k} style={{ fontFamily: T.mono, fontSize: '0.92em', color: T.cyan, background: T.panel3, padding: '1px 4px' }}>{t.slice(1, -1)}</code>)
    else if (t.startsWith('[')) {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t)!
      const safe = /^https?:\/\//.test(lm[2])
      out.push(safe
        ? <a key={k} href={lm[2]} target="_blank" rel="noreferrer" style={{ color: T.amber }}>{lm[1]}</a>
        : <span key={k} style={{ color: T.amber }}>{lm[1]}</span>)
    } else out.push(<i key={k}>{inline(t.slice(1, -1), k)}</i>)
    last = m.end
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const splitRow = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim())

function Table({ rows, k }: { rows: string[]; k: string }) {
  const head = splitRow(rows[0])
  const body = rows.slice(2).map(splitRow)
  const numeric = head.map((_, c) => body.length > 0 && body.every(r => !r[c] || NUM_CELL.test(r[c].replace(/\*\*/g, ''))))
  return (
    <div style={{ overflowX: 'auto', margin: '10px 0 14px', border: `1px solid ${T.border}` }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
        <thead>
          <tr>{head.map((h, c) => (
            <th key={c} style={{ textAlign: numeric[c] ? 'right' : 'left', padding: '6px 10px', background: '#080b10',
                                 color: T.muted, fontWeight: 600, fontSize: 10, letterSpacing: .8, textTransform: 'uppercase',
                                 borderBottom: `1px solid ${T.border}`, whiteSpace: 'nowrap' }}>{inline(h, `${k}h${c}`)}</th>
          ))}</tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i} style={{ borderBottom: `1px solid ${T.border}` }}>
              {head.map((_, c) => {
                const v = r[c] ?? ''
                const neg = numeric[c] && /^[\s*]*[−\-–]\s*[\d₹]/.test(v)
                const pos = numeric[c] && /^[\s*]*\+/.test(v)
                return (
                  <td key={c} style={{ textAlign: numeric[c] ? 'right' : 'left', padding: '5px 10px', verticalAlign: 'top',
                                       fontFamily: numeric[c] ? T.mono : undefined, color: neg ? T.red : pos ? T.green : T.text }}>
                    {inline(v, `${k}r${i}c${c}`)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  const p = { fontSize: 13, lineHeight: 1.7, color: T.text, margin: '0 0 10px' }
  while (i < lines.length) {
    const line = lines[i], k = `b${i}`
    if (!line.trim()) { i++; continue }
    if (line.startsWith('```')) {
      const code: string[] = []
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) code.push(lines[i])
      i++
      blocks.push(<pre key={k} style={{ fontFamily: T.mono, fontSize: 11, color: T.text, background: '#07090d', border: `1px solid ${T.border}`,
                                         padding: '10px 12px', overflowX: 'auto', margin: '8px 0 12px' }}>{code.join('\n')}</pre>)
      continue
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      const lvl = h[1].length
      const size = [0, 20, 15, 13, 12][lvl]
      blocks.push(
        <div key={k} style={{ fontFamily: T.display, fontSize: size, fontWeight: 700, letterSpacing: lvl === 1 ? 1 : .6,
                              color: lvl <= 2 ? T.amber : T.bright, margin: lvl === 1 ? '0 0 12px' : '18px 0 8px',
                              paddingBottom: lvl === 2 ? 5 : 0, borderBottom: lvl === 2 ? `1px solid ${T.border}` : 'none' }}>
          {inline(h[2], k)}
        </div>)
      i++; continue
    }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { blocks.push(<hr key={k} style={{ border: 'none', borderTop: `1px solid ${T.border}`, margin: '14px 0' }} />); i++; continue }
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const rows: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(lines[i++])
      blocks.push(<Table key={k} rows={rows} k={k} />)
      continue
    }
    if (/^>\s?/.test(line)) {
      const q: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i])) q.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(<div key={k} style={{ ...p, borderLeft: `2px solid ${T.amber}`, paddingLeft: 12, color: T.muted }}>{inline(q.join(' '), k)}</div>)
      continue
    }
    const li = /^(\s*)([-*]|\d+[.)])\s+(.*)$/
    if (li.test(line)) {
      const ordered = /^\s*\d/.test(line)
      const items: { text: string; depth: number }[] = []
      while (i < lines.length && (li.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        const m = li.exec(lines[i])
        if (m) items.push({ text: m[3], depth: Math.floor(m[1].length / 2) })
        else items[items.length - 1].text += ' ' + lines[i].trim()
        i++
      }
      const Tag = ordered ? 'ol' : 'ul'
      blocks.push(
        <Tag key={k} style={{ margin: '0 0 10px', paddingLeft: 20, listStyleType: ordered ? 'decimal' : 'disc', fontSize: 13, lineHeight: 1.7, color: T.text }}>
          {items.map((it, j) => <li key={j} style={{ marginLeft: it.depth * 16, marginBottom: 3 }}>{inline(it.text, `${k}l${j}`)}</li>)}
        </Tag>)
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*\||>|\s*([-*]|\d+[.)])\s)/.test(lines[i])) para.push(lines[i++])
    if (!para.length) para.push(lines[i++])
    blocks.push(<p key={k} style={p}>{inline(para.join(' '), k)}</p>)
  }
  return <Fragment>{blocks}</Fragment>
}
