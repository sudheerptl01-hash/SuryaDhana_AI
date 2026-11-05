#!/usr/bin/env node
// @ts-check
/**
 * Print the RESOLVED Next.js config (defaults merged, exactly what `next dev` / `next build` /
 * `next start` see) as stable, key-sorted JSON. Used to prove that a next.config.js change leaves
 * the dev and prod modes byte-for-byte identical:
 *
 *   node ui/scripts/print-next-config.mjs --phase dev                        > before-dev.json
 *   NEXT_DIST_DIR=.next-prod node ui/scripts/print-next-config.mjs --phase build > before-prod.json
 *   ... edit next.config.js ...
 *   (same commands) > after-*.json && diff before-dev.json after-dev.json
 *
 * Async config members (rewrites, redirects, headers) are awaited and printed as data; any other
 * function is printed as "[Function <name>]". Environment (NEXT_DIST_DIR, NEXT_OUTPUT,
 * NEXT_PUBLIC_UI_BUILD, ...) is taken from the caller.
 *
 * Options:
 *   --phase dev|build|start   Next phase to resolve for (default: dev)
 *   --dir <path>              project dir holding next.config.js (default: the ui/ dir above this script)
 *   --only <k1,k2>            print only these top-level keys
 */
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))

/** @param {string[]} argv */
function parseArgs(argv) {
  /** @type {{phase: string, dir: string, only: string[] | null}} */
  const out = { phase: 'dev', dir: path.resolve(here, '..'), only: null }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--phase') out.phase = argv[++i]
    else if (a === '--dir') out.dir = path.resolve(argv[++i])
    else if (a === '--only') out.only = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
    else if (a === '-h' || a === '--help') {
      process.stdout.write('usage: print-next-config.mjs [--phase dev|build|start] [--dir <ui dir>] [--only k1,k2]\n')
      process.exit(0)
    } else {
      process.stderr.write(`unknown argument: ${a}\n`)
      process.exit(2)
    }
  }
  return out
}

/**
 * Deterministic JSON-able copy: sorted object keys, functions labelled, RegExp as source.
 * @param {unknown} v
 * @param {WeakSet<object>} seen
 * @returns {unknown}
 */
function normalise(v, seen = new WeakSet()) {
  if (typeof v === 'function') return `[Function ${v.name || 'anonymous'}]`
  if (v instanceof RegExp) return `[RegExp ${v.source}]`
  if (v === undefined) return '[undefined]'
  if (v === null || typeof v !== 'object') return v
  if (seen.has(v)) return '[Circular]'
  seen.add(v)
  if (Array.isArray(v)) return v.map((x) => normalise(x, seen))
  /** @type {Record<string, unknown>} */
  const o = {}
  for (const k of Object.keys(v).sort()) o[k] = normalise(/** @type {any} */ (v)[k], seen)
  return o
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const require = createRequire(path.join(args.dir, 'package.json'))
  const constants = require('next/dist/shared/lib/constants')
  const loadConfig = require('next/dist/server/config').default
  /** @type {Record<string, string>} */
  const phases = {
    dev: constants.PHASE_DEVELOPMENT_SERVER,
    build: constants.PHASE_PRODUCTION_BUILD,
    start: constants.PHASE_PRODUCTION_SERVER,
  }
  const phase = phases[args.phase]
  if (!phase) throw new Error(`--phase must be one of ${Object.keys(phases).join('|')}`)
  const cfg = await loadConfig(phase, args.dir, { silent: true })
  /** @type {Record<string, unknown>} */
  const resolved = { ...cfg }
  for (const k of ['rewrites', 'redirects', 'headers']) {
    if (typeof cfg[k] === 'function') resolved[k] = { '[awaited]': await cfg[k]() }
  }
  let out = /** @type {Record<string, unknown>} */ (normalise(resolved))
  if (args.only) out = Object.fromEntries(args.only.map((k) => [k, out[k] ?? '[absent]']))
  process.stdout.write(JSON.stringify(out, null, 2) + '\n')
}

main().catch((err) => {
  process.stderr.write(`print-next-config: ${err && err.message ? err.message : String(err)}\n`)
  process.exit(1)
})
