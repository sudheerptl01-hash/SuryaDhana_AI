// @ts-check
/**
 * End-to-end tests of scripts/build_ui.sh against a throwaway repo layout, with a stand-in `next`
 * (testdata/fake-next.mjs via BUILD_UI_NEXT_BIN) so each build takes well under a second. The real
 * Next export is exercised separately (reports/desktop_app D1 run log).
 *
 * Covers: --out, the release flow (swap, previous, carry-forward, prune), --rollback, --list,
 * failure cleanup (build error, verification error), tsconfig restore, lock timeout and stale-lock
 * takeover, destination guards, --help/usage exit codes.
 *
 * Run: node --test ui/scripts/*.test.mjs
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const UI = path.resolve(HERE, '..')
const REPO = path.resolve(UI, '..')
const FAKE_NEXT = path.join(HERE, 'testdata', 'fake-next.mjs')

/** A minimal repo: scripts/build_ui.sh + ui/{next.config.js, scripts/release.mjs, sources}. */
function makeRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'build-ui-e2e-'))
  const ui = path.join(root, 'ui')
  fs.mkdirSync(path.join(root, 'scripts'), { recursive: true })
  fs.mkdirSync(path.join(ui, 'scripts'), { recursive: true })
  fs.mkdirSync(path.join(ui, 'app'), { recursive: true })
  fs.mkdirSync(path.join(ui, 'node_modules', 'next'), { recursive: true })
  fs.copyFileSync(path.join(REPO, 'scripts', 'build_ui.sh'), path.join(root, 'scripts', 'build_ui.sh'))
  fs.chmodSync(path.join(root, 'scripts', 'build_ui.sh'), 0o755)
  fs.copyFileSync(path.join(UI, 'scripts', 'release.mjs'), path.join(ui, 'scripts', 'release.mjs'))
  fs.copyFileSync(path.join(UI, 'next.config.js'), path.join(ui, 'next.config.js'))
  fs.writeFileSync(path.join(ui, 'package.json'), '{"name":"t","private":true}')
  fs.writeFileSync(path.join(ui, 'node_modules', 'next', 'package.json'), '{"version":"15.5.18-test"}')
  fs.writeFileSync(path.join(ui, 'tsconfig.json'), '{\n  "include": ["app/**/*.tsx"]\n}\n')
  fs.writeFileSync(path.join(ui, 'next-env.d.ts'), '/// <reference types="next" />\n')
  fs.writeFileSync(path.join(ui, 'app', 'page.tsx'), 'export default function P() { return null }\n')
  return { root, ui, script: path.join(root, 'scripts', 'build_ui.sh'), dist: path.join(ui, 'dist') }
}

/**
 * @param {ReturnType<typeof makeRepo>} repo @param {string[]} args @param {Record<string, string>} [env]
 */
function run(repo, args, env = {}) {
  const r = spawnSync('/bin/bash', [repo.script, ...args], {
    cwd: repo.root,
    encoding: 'utf8',
    env: { ...process.env, BUILD_UI_NEXT_BIN: FAKE_NEXT, NEXT_DIST_DIR: '.next-prod', ...env },
    timeout: 60_000,
  })
  return { code: r.status, out: `${r.stdout}${r.stderr}` }
}

const id = (n) => `20261024-1${n}0000-abcdef${n}`
const link = (dist, name) => {
  try {
    return path.basename(fs.readlinkSync(path.join(dist, name)))
  } catch {
    return null
  }
}
/** nothing temporary left behind in ui/ */
function assertClean(repo) {
  assert.ok(!fs.existsSync(path.join(repo.ui, '.build-ui')), '.build-ui (staging/lock) left behind')
  if (fs.existsSync(path.join(repo.dist, 'releases'))) {
    assert.deepEqual(fs.readdirSync(path.join(repo.dist, 'releases')).filter((e) => e.startsWith('.')), [])
  }
}

test('--help and usage errors', () => {
  const repo = makeRepo()
  const help = run(repo, ['--help'])
  assert.equal(help.code, 0)
  assert.match(help.out, /--rollback \[<id>\]/)
  assert.match(help.out, /Exit codes/)
  assert.equal(run(repo, ['--bogus']).code, 2)
  assert.equal(run(repo, ['--keep', '1']).code, 2)
  assert.equal(run(repo, ['--out']).code, 2)
})

test('--out builds a verified, precompressed export with build-info and leaves the repo clean', () => {
  const repo = makeRepo()
  const before = fs.readFileSync(path.join(repo.ui, 'tsconfig.json'))
  const out = path.join(repo.root, 'scratch-out')
  const r = run(repo, ['--out', out], { BUILD_UI_RELEASE_ID: id(1) })
  assert.equal(r.code, 0, r.out)
  const info = JSON.parse(fs.readFileSync(path.join(out, 'build-info.json'), 'utf8'))
  assert.equal(info.id, id(1))
  assert.equal(info.git_sha, '0000000') // not a git checkout
  assert.equal(info.next_version, '15.5.18-test')
  assert.match(info.source_sha256, /^[0-9a-f]{64}$/)
  assert.ok(fs.existsSync(path.join(out, 'index.html.gz')))
  assert.match(fs.readFileSync(path.join(out, 'index.html'), 'utf8'), new RegExp(`data-build="${id(1)}"`))
  assert.ok(!fs.existsSync(repo.dist), '--out never creates a release')
  assert.deepEqual(fs.readFileSync(path.join(repo.ui, 'tsconfig.json')), before)
  assertClean(repo)
  // rebuilding into the same --out replaces it (it carries build-info.json)
  const again = run(repo, ['--out', out], { BUILD_UI_RELEASE_ID: id(2) })
  assert.equal(again.code, 0, again.out)
  assert.equal(JSON.parse(fs.readFileSync(path.join(out, 'build-info.json'), 'utf8')).id, id(2))
  assert.ok(!fs.readdirSync(repo.root).some((e) => e.includes('.tmp-') || e.includes('.old-')))
})

test('--out refuses to overwrite a non-empty directory that is not a build output, and protected paths', () => {
  const repo = makeRepo()
  const victim = path.join(repo.root, 'precious')
  fs.mkdirSync(victim)
  fs.writeFileSync(path.join(victim, 'notes.txt'), 'keep me')
  const r = run(repo, ['--out', victim])
  assert.equal(r.code, 1)
  assert.match(r.out, /refusing to replace it/)
  assert.equal(fs.readFileSync(path.join(victim, 'notes.txt'), 'utf8'), 'keep me')
  for (const bad of [repo.ui, path.join(repo.ui, '.next'), path.join(repo.ui, '.next-prod'), repo.root]) {
    const g = run(repo, ['--out', bad])
    assert.equal(g.code, 1, bad)
    assert.match(g.out, /must not be/)
  }
})

test('release flow: swap, previous, carry-forward, prune (keep 3 + current + previous), rollback, list', () => {
  const repo = makeRepo()
  const d = repo.dist
  assert.equal(run(repo, [], { BUILD_UI_RELEASE_ID: id(1) }).code, 0)
  assert.equal(link(d, 'current'), id(1))
  assert.equal(link(d, 'previous'), null)
  const r2 = run(repo, [], { BUILD_UI_RELEASE_ID: id(2) })
  assert.equal(r2.code, 0, r2.out)
  assert.equal(link(d, 'current'), id(2))
  assert.equal(link(d, 'previous'), id(1))
  // release 2 carries release 1's page chunk so an open window on build 1 can still lazy-load it
  const carried = path.join(d, 'releases', id(2), '_next/static/chunks', `page-${id(1)}.js`)
  assert.ok(fs.existsSync(carried), r2.out)
  assert.ok(fs.existsSync(`${carried}.gz`))
  const info2 = JSON.parse(fs.readFileSync(path.join(d, 'releases', id(2), 'build-info.json'), 'utf8'))
  assert.equal(info2.carried_forward_files, 2)
  assert.match(r2.out, /carried forward 2 old _next\/static files/)
  // the current page itself is NOT replaced by a carried copy
  assert.match(fs.readFileSync(path.join(d, 'current', 'index.html'), 'utf8'), new RegExp(id(2)))
  for (const n of [3, 4]) assert.equal(run(repo, [], { BUILD_UI_RELEASE_ID: id(n) }).code, 0)
  assert.deepEqual(fs.readdirSync(path.join(d, 'releases')).sort(), [id(2), id(3), id(4)])
  assert.equal(link(d, 'current'), id(4))
  assert.equal(link(d, 'previous'), id(3))
  // carry-forward reaches back two releases (the native chunks of 3 and 2) ...
  assert.ok(fs.existsSync(path.join(d, 'releases', id(4), '_next/static/chunks', `page-${id(2)}.js`)))
  // ... but not further: 1's chunk, which 2 and 3 had only carried, does not travel again (bounded growth)
  assert.ok(!fs.existsSync(path.join(d, 'releases', id(4), '_next/static/chunks', `page-${id(1)}.js`)),
    'carried chunks must not accumulate from release to release')
  const native4 = JSON.parse(fs.readFileSync(path.join(d, 'releases', id(4), '.native-static.json'), 'utf8'))
  assert.ok(native4.files.includes(`chunks/page-${id(4)}.js`) && !native4.files.includes(`chunks/page-${id(3)}.js`))
  // rollback walks back; explicit id; list
  const rb = run(repo, ['--rollback'])
  assert.equal(rb.code, 0, rb.out)
  assert.equal(link(d, 'current'), id(3))
  assert.equal(link(d, 'previous'), id(4))
  assert.match(rb.out, /carried \d+ newer _next\/static files/)
  assert.ok(fs.existsSync(path.join(d, 'releases', id(3), '_next/static/chunks', `page-${id(4)}.js`)),
    'a window on build 4 can still lazy-load its chunk after rolling back to 3')
  assert.match(fs.readFileSync(path.join(d, 'current', 'index.html'), 'utf8'), new RegExp(id(3)))
  assert.equal(run(repo, ['--rollback']).code, 0)
  assert.equal(link(d, 'current'), id(2))
  assert.equal(run(repo, ['--rollback']).code, 1, 'nothing older than the oldest kept release')
  assert.equal(run(repo, ['--rollback', id(4)]).code, 0)
  assert.equal(link(d, 'current'), id(4))
  const ls = run(repo, ['--list'])
  assert.equal(ls.code, 0)
  assert.match(ls.out, new RegExp(`current\\s+${id(4)}`))
  assert.match(ls.out, new RegExp(`previous\\s+${id(2)}`))
  // a build after a rollback protects the rolled-back-to release as previous
  assert.equal(run(repo, ['--rollback', id(2)]).code, 0)
  assert.equal(run(repo, [], { BUILD_UI_RELEASE_ID: id(5) }).code, 0)
  assert.equal(link(d, 'previous'), id(2))
  assert.ok(fs.existsSync(path.join(d, 'releases', id(2))), 'previous is never pruned')
  assertClean(repo)
})

test('a killed build\'s staging dir (pid gone) is removed by the next run; a live one is left alone', () => {
  const repo = makeRepo()
  const work = path.join(repo.ui, '.build-ui')
  const dead = path.join(work, `staging-${id(1)}-999999`)
  const live = path.join(work, `staging-${id(2)}-${process.pid}`)
  for (const dir of [dead, live]) {
    fs.mkdirSync(path.join(dir, '.next'), { recursive: true })
    fs.writeFileSync(path.join(dir, '.next', 'big.bin'), 'x'.repeat(1000))
  }
  const r = run(repo, ['--out', path.join(repo.root, 'o')], { BUILD_UI_RELEASE_ID: id(3) })
  assert.equal(r.code, 0, r.out)
  assert.match(r.out, /removing a killed build's staging dir ui\/\.build-ui\/staging-\S+-999999 \(pid 999999 is gone\)/)
  assert.ok(!fs.existsSync(dead), 'the dead build\'s staging dir is gone')
  assert.ok(fs.existsSync(live), 'a staging dir whose pid is alive is never touched')
  fs.rmSync(work, { recursive: true, force: true })
  assertClean(repo)
})

test('a failing build leaves current untouched and cleans every temp dir', () => {
  const repo = makeRepo()
  assert.equal(run(repo, [], { BUILD_UI_RELEASE_ID: id(1) }).code, 0)
  const r = run(repo, [], { BUILD_UI_RELEASE_ID: id(2), FAKE_NEXT_FAIL: '1' })
  assert.equal(r.code, 1)
  assert.match(r.out, /next build failed/)
  assert.match(r.out, /Type error: something is wrong/, 'the tail of the build log is shown')
  assert.match(r.out, /current unchanged/)
  assert.equal(link(repo.dist, 'current'), id(1))
  assert.deepEqual(fs.readdirSync(path.join(repo.dist, 'releases')), [id(1)])
  assertClean(repo)
})

test('verification failure (a route handler leaked into the export) aborts before any swap', () => {
  const repo = makeRepo()
  assert.equal(run(repo, [], { BUILD_UI_RELEASE_ID: id(1) }).code, 0)
  const r = run(repo, [], { BUILD_UI_RELEASE_ID: id(2), FAKE_NEXT_API: '1' })
  assert.equal(r.code, 1)
  assert.match(r.out, /api\/ path exists/)
  assert.equal(link(repo.dist, 'current'), id(1))
  assertClean(repo)
})

test('a Next-style rewrite of ui/tsconfig.json (staging path) is restored byte-for-byte', () => {
  const repo = makeRepo()
  const before = fs.readFileSync(path.join(repo.ui, 'tsconfig.json'))
  const r = run(repo, ['--out', path.join(repo.root, 'o')], { BUILD_UI_RELEASE_ID: id(1), FAKE_NEXT_TOUCH_TSCONFIG: '1' })
  assert.equal(r.code, 0, r.out)
  assert.match(r.out, /the build rewrote ui\/tsconfig\.json \(staging paths\); restored/)
  assert.deepEqual(fs.readFileSync(path.join(repo.ui, 'tsconfig.json')), before)
})

test('a concurrent edit of ui/tsconfig.json by someone else is NOT reverted', () => {
  const repo = makeRepo()
  const before = fs.readFileSync(path.join(repo.ui, 'tsconfig.json'), 'utf8')
  const r = run(repo, ['--out', path.join(repo.root, 'o')], { BUILD_UI_RELEASE_ID: id(1), FAKE_NEXT_FOREIGN_EDIT: '1' })
  assert.equal(r.code, 0, r.out)
  assert.match(r.out, /changed during the build, not by it/)
  assert.equal(fs.readFileSync(path.join(repo.ui, 'tsconfig.json'), 'utf8'), before + '\n')
})

test('lock: a live holder times out the second run (exit 3); a dead holder is taken over', () => {
  const repo = makeRepo()
  const lock = path.join(repo.ui, '.build-ui', 'lock')
  fs.mkdirSync(lock, { recursive: true })
  fs.writeFileSync(path.join(lock, 'pid'), String(process.pid)) // this test runner: alive
  fs.writeFileSync(path.join(lock, 'what'), 'release test-holder')
  const blocked = run(repo, ['--out', path.join(repo.root, 'o')], { BUILD_UI_LOCK_TIMEOUT: '2' })
  assert.equal(blocked.code, 3, blocked.out)
  assert.match(blocked.out, /still holds the lock/)
  assert.ok(fs.existsSync(lock), 'a lock we do not own is never removed')
  fs.writeFileSync(path.join(lock, 'pid'), '999999') // gone
  const ok = run(repo, ['--out', path.join(repo.root, 'o')], { BUILD_UI_RELEASE_ID: id(1) })
  assert.equal(ok.code, 0, ok.out)
  assert.match(ok.out, /taking over a stale lock/)
  assertClean(repo)
})

test('lock: a waiter proceeds when the holder releases AND removes the empty .build-ui dir', async () => {
  const repo = makeRepo()
  const work = path.join(repo.ui, '.build-ui')
  const lock = path.join(work, 'lock')
  fs.mkdirSync(lock, { recursive: true })
  fs.writeFileSync(path.join(lock, 'pid'), String(process.pid)) // alive holder
  fs.writeFileSync(path.join(lock, 'what'), 'release test-holder')
  const { spawn } = await import('node:child_process')
  const child = spawn('/bin/bash', [repo.script, '--out', path.join(repo.root, 'o')], {
    cwd: repo.root,
    env: { ...process.env, BUILD_UI_NEXT_BIN: FAKE_NEXT, NEXT_DIST_DIR: '.next-prod', BUILD_UI_RELEASE_ID: id(1), BUILD_UI_LOCK_TIMEOUT: '30' },
  })
  let out = ''
  child.stdout.on('data', (d) => { out += d })
  child.stderr.on('data', (d) => { out += d })
  await new Promise((r) => setTimeout(r, 3000))
  fs.rmSync(work, { recursive: true, force: true }) // the holder's cleanup: lock gone, then rmdir of the empty work dir
  const code = await new Promise((r) => child.on('exit', r))
  assert.equal(code, 0, out)
  assert.doesNotMatch(out, /still holds the lock/)
  assertClean(repo)
})

test('export mode refuses to run outside a staging copy (protects ui/.next)', () => {
  const r = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(path.join(UI, 'next.config.js'))})`], {
    env: { ...process.env, NEXT_OUTPUT: 'export' },
    encoding: 'utf8',
  })
  assert.notEqual(r.status, 0)
  assert.match(r.stderr, /must run through scripts\/build_ui\.sh/)
  const dev = spawnSync(process.execPath, ['-e', `const c=require(${JSON.stringify(path.join(UI, 'next.config.js'))});console.log(JSON.stringify(Object.keys(c)))`], {
    env: { ...process.env, NEXT_OUTPUT: '' },
    encoding: 'utf8',
  })
  assert.equal(dev.status, 0)
  assert.deepEqual(JSON.parse(dev.stdout), ['reactStrictMode', 'distDir', 'rewrites'])
})
