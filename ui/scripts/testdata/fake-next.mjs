#!/usr/bin/env node
// @ts-check
/**
 * Stand-in for `next build` used by ui/scripts/build_ui.test.mjs (via BUILD_UI_NEXT_BIN).
 * Writes a minimal static export into ./out like Next's export mode does, with a chunk name that is
 * unique per release id so carry-forward can be observed. Behaviour switches (env):
 *   FAKE_NEXT_FAIL=1            exit 1 after printing an error
 *   FAKE_NEXT_API=1             also emit out/api/stream (a route handler leak → verify must fail)
 *   FAKE_NEXT_TOUCH_TSCONFIG=1  rewrite the REAL ui/tsconfig.json like Next would (staging path) → restored
 *   FAKE_NEXT_FOREIGN_EDIT=1    edit ui/tsconfig.json without staging paths (a concurrent human edit) → kept
 *   FAKE_NEXT_SLEEP_MS=<n>      sleep before writing (to test the lock)
 */
import fs from 'node:fs'
import path from 'node:path'

if (process.argv[2] !== 'build') {
  console.error(`fake-next: unsupported command ${process.argv[2]}`)
  process.exit(2)
}
const cwd = process.cwd()
if (!fs.existsSync(path.join(cwd, '.suryadhana-export-staging'))) {
  console.error('fake-next: not running in a staging copy')
  process.exit(3)
}
if (process.env.NEXT_OUTPUT !== 'export') {
  console.error('fake-next: NEXT_OUTPUT is not export')
  process.exit(4)
}
const sleepMs = Number(process.env.FAKE_NEXT_SLEEP_MS || 0)
if (sleepMs > 0) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, sleepMs)
if (process.env.FAKE_NEXT_FAIL === '1') {
  console.error('fake-next: Type error: something is wrong')
  process.exit(1)
}
if (process.env.FAKE_NEXT_TOUCH_TSCONFIG === '1') {
  // what Next does when its distDir changes: add <distDir>/types/** to tsconfig include
  const ts = path.resolve(cwd, '..', '..', 'tsconfig.json')
  const cfg = JSON.parse(fs.readFileSync(ts, 'utf8'))
  cfg.include = [...(cfg.include || []), `.build-ui/${path.basename(cwd)}/.next/types/**/*.ts`]
  fs.writeFileSync(ts, JSON.stringify(cfg, null, 2) + '\n')
}
if (process.env.FAKE_NEXT_FOREIGN_EDIT === '1') {
  // someone else edits tsconfig while the build runs: must be left alone
  fs.appendFileSync(path.resolve(cwd, '..', '..', 'tsconfig.json'), '\n')
}
const id = process.env.NEXT_PUBLIC_UI_BUILD || 'unversioned'
const out = path.join(cwd, 'out')
const chunk = `_next/static/chunks/page-${id}.js`
const shared = '_next/static/chunks/framework-shared.js'
/** @param {string} rel @param {string} data */
const write = (rel, data) => {
  fs.mkdirSync(path.dirname(path.join(out, rel)), { recursive: true })
  fs.writeFileSync(path.join(out, rel), data)
}
write('index.html', `<!doctype html><html><head><script src="/${chunk}"></script><script src="/${shared}"></script></head><body data-build="${id}">${'x'.repeat(2000)}</body></html>`)
write('404.html', `<!doctype html><title>404</title>${'y'.repeat(1500)}`)
write('index.txt', `0:${id} ${'z'.repeat(1200)}`)
write(chunk, `console.log(${JSON.stringify(id)});${' '.repeat(3000)}`)
write(shared, `/* shared framework chunk */${'f'.repeat(3000)}`)
write('icon.svg', '<svg xmlns="http://www.w3.org/2000/svg"/>')
if (process.env.FAKE_NEXT_API === '1') write('api/telemetry/logs/stream', 'route handler output')
console.log(`fake-next: exported ${id}`)
