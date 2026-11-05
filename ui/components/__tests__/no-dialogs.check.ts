/**
 * Guard (FEATURE_PARITY.md R2): the terminal must never use window.confirm / alert / prompt. Inside SuryaDhana.app the
 * dialog plugin makes them asynchronous, so `if (!window.confirm(...)) return` reads a Promise as "yes" and the action
 * runs without asking (it cleared the HARD −20% emergency stop). Use an in-page confirmation instead.
 *
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/no-dialogs.check.ts
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOTS = ['app', 'components', 'lib', 'context'].map(d => join(import.meta.dirname, '..', '..', d))
const RX = /(?<![.\w])(?:window\s*\.\s*)?(confirm|alert|prompt)\s*\(/g
const hits: string[] = []
const walk = (dir: string): void => {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) { if (name !== '__tests__' && name !== 'node_modules') walk(p); continue }
    if (!/\.(tsx?|jsx?)$/.test(name)) continue
    readFileSync(p, 'utf8').split('\n').forEach((line, i) => {
      const code = line.replace(/\/\/.*$/, '')
      if (/^\s*\*/.test(code)) return
      for (const m of code.matchAll(RX)) hits.push(`${p}:${i + 1}: ${m[0]}`)
    })
  }
}
ROOTS.forEach(walk)
if (hits.length) { console.error(`no-dialogs.check: ${hits.length} browser dialog call(s):\n` + hits.join('\n')); process.exit(1) }
console.log('no-dialogs.check: 0 window.confirm/alert/prompt calls in ui/{app,components,lib,context}')
