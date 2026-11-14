// @ts-check
/**
 * Unit tests for ui/scripts/release.mjs.  Run: node --test ui/scripts/*.test.mjs
 */
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import zlib from 'node:zlib'

import {
  NATIVE_MANIFEST,
  RELEASE_ID_RE,
  STAGE_EXCLUDE_TOP,
  STAGING_MARKER,
  atomicPoint,
  carry,
  list,
  listReleases,
  nativeFiles,
  pickCarry,
  pointerId,
  precompress,
  prune,
  recordNative,
  rollback,
  runCli,
  stage,
  swap,
  verify,
  walk,
  writeBuildInfo,
} from './release.mjs'

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'release-test-'))
/** @param {string} p @param {string | Buffer} d */
const put = (p, d) => {
  fs.mkdirSync(path.dirname(p), { recursive: true })
  fs.writeFileSync(p, d)
}
const ids = ['20261024-100000-aaaaaaa', '20261024-110000-bbbbbbb', '20261024-120000-ccccccc', '20261024-130000-ddddddd']

/** A valid export at dir with one chunk named after `tag`. */
function makeExport(dir, tag = 'a') {
  put(path.join(dir, 'index.html'), `<html><script src="/_next/static/chunks/p-${tag}.js"></script>${'x'.repeat(2000)}</html>`)
  put(path.join(dir, '_next/static/chunks', `p-${tag}.js`), `/*${tag}*/` + 'y'.repeat(3000))
  put(path.join(dir, '404.html'), '<p>404</p>')
  return dir
}

/** dist with releases ids[0..n-1] */
function makeDist(n) {
  const dist = tmp()
  for (let i = 0; i < n; i++) makeExport(path.join(dist, 'releases', ids[i]), String(i))
  return dist
}

test('release ids sort chronologically and match the documented format', () => {
  assert.ok(ids.every((i) => RELEASE_ID_RE.test(i)))
  assert.ok(!RELEASE_ID_RE.test('20261024-1000-aaaaaaa'))
  assert.deepEqual([...ids].reverse().sort(), ids)
})

test('stage copies sources, excludes build dirs and deps, writes the marker, hashes sources', () => {
  const src = tmp()
  put(path.join(src, 'next.config.js'), 'module.exports = {}')
  put(path.join(src, 'package.json'), '{}')
  put(path.join(src, 'package-lock.json'), '{}')
  put(path.join(src, 'tsconfig.json'), '{}')
  put(path.join(src, '.env.local'), 'NEXT_PUBLIC_X=1')
  put(path.join(src, 'app/page.tsx'), 'export default 1')
  put(path.join(src, 'app/.DS_Store'), 'junk')
  put(path.join(src, 'app/debug.log'), 'junk')
  for (const d of ['node_modules/x', '.next/cache', '.next-prod/x', '.next-b4check/x', 'dist/current', 'out/x', 'scripts/x', '.build-ui/lock', '.gstack/x', '.export-old/x']) put(path.join(src, d, 'f'), 'no')
  put(path.join(src, 'tsconfig.tsbuildinfo'), 'no')
  const dest = path.join(src, '.build-ui', 'staging-1')
  const res = stage(src, dest)
  const files = walk(dest).files
  assert.deepEqual(files.sort(), ['.env.local', STAGING_MARKER, 'app/page.tsx', 'next.config.js', 'package.json', 'tsconfig.json'].sort())
  assert.equal(res.files, 5)
  assert.match(res.source_sha256, /^[0-9a-f]{64}$/)
  const again = stage(src, path.join(src, '.build-ui', 'staging-2'))
  assert.equal(again.source_sha256, res.source_sha256, 'hash is deterministic')
  fs.writeFileSync(path.join(src, 'app/page.tsx'), 'export default 2')
  assert.notEqual(stage(src, path.join(src, '.build-ui', 'staging-3')).source_sha256, res.source_sha256)
  assert.throws(() => stage(src, dest), /not empty/)
})

test('verify accepts a good export and names every problem in a bad one', () => {
  const good = makeExport(tmp())
  assert.equal(verify(good).static_files, 1)
  const noIndex = tmp()
  put(path.join(noIndex, '_next/static/chunks/a.js'), 'x')
  assert.throws(() => verify(noIndex), /index\.html missing/)
  const api = makeExport(tmp())
  put(path.join(api, 'api/telemetry/logs/stream'), 'route')
  assert.throws(() => verify(api), /api\/ path exists/)
  const missingRef = makeExport(tmp())
  fs.rmSync(path.join(missingRef, '_next/static/chunks/p-a.js'))
  put(path.join(missingRef, '_next/static/chunks/other.js'), 'x')
  assert.throws(() => verify(missingRef), /references missing assets: \/_next\/static\/chunks\/p-a\.js/)
  const link = makeExport(tmp())
  fs.symlinkSync('/etc/passwd', path.join(link, 'passwd'))
  assert.throws(() => verify(link), /symlinks in export/)
})

test('precompress: >1 KB text only, deterministic, mtime-matched, never bigger', () => {
  const dir = makeExport(tmp())
  put(path.join(dir, 'small.js'), 'x=1')
  put(path.join(dir, 'font.woff2'), Buffer.alloc(4096, 7))
  put(path.join(dir, 'random.js'), crypto.randomBytes(4096)) // incompressible: gz would not be smaller
  put(path.join(dir, 'build-info.json'), '{}' + ' '.repeat(2000))
  const r = precompress(dir)
  assert.equal(r.gz_files, 2) // index.html + the chunk
  assert.equal(r.not_smaller, 1)
  assert.ok(!fs.existsSync(path.join(dir, 'random.js.gz')))
  assert.ok(fs.existsSync(path.join(dir, 'index.html.gz')))
  assert.ok(!fs.existsSync(path.join(dir, 'small.js.gz')))
  assert.ok(!fs.existsSync(path.join(dir, 'font.woff2.gz')))
  assert.ok(!fs.existsSync(path.join(dir, 'build-info.json.gz')))
  const gz = fs.readFileSync(path.join(dir, 'index.html.gz'))
  assert.deepEqual(zlib.gunzipSync(gz), fs.readFileSync(path.join(dir, 'index.html')))
  assert.equal(gz.readUInt32LE(4), 0, 'gzip header mtime is 0')
  assert.ok(Math.abs(fs.statSync(path.join(dir, 'index.html.gz')).mtimeMs - fs.statSync(path.join(dir, 'index.html')).mtimeMs) < 0.01)
  const first = Buffer.from(gz)
  fs.rmSync(path.join(dir, 'index.html.gz'))
  precompress(dir)
  assert.deepEqual(fs.readFileSync(path.join(dir, 'index.html.gz')), first, 'byte-identical on rebuild')
})

test('carry copies only missing static files, never overwrites, preserves mtime', () => {
  const dist = makeDist(2)
  const [a, b] = [path.join(dist, 'releases', ids[0]), path.join(dist, 'releases', ids[1])]
  put(path.join(a, '_next/static/chunks/shared.js'), 'OLD')
  put(path.join(b, '_next/static/chunks/shared.js'), 'NEW')
  const past = new Date('2026-01-01T00:00:00Z')
  fs.utimesSync(path.join(a, '_next/static/chunks/p-0.js'), past, past)
  const r = carry(b, [a])
  assert.equal(r.carried_files, 1)
  assert.equal(fs.readFileSync(path.join(b, '_next/static/chunks/shared.js'), 'utf8'), 'NEW')
  assert.equal(fs.statSync(path.join(b, '_next/static/chunks/p-0.js')).mtimeMs, past.getTime())
  assert.equal(carry(b, [a]).carried_files, 0, 'idempotent')
  assert.equal(carry(b, [path.join(dist, 'nope')]).carried_files, 0)
})

test('recordNative/nativeFiles: the manifest lists the build\'s own files; legacy releases count everything', () => {
  const dir = makeExport(tmp(), 'n')
  assert.deepEqual(nativeFiles(dir), ['chunks/p-n.js'], 'no manifest yet: every file (legacy behaviour)')
  assert.deepEqual(recordNative(dir), { dir, native_files: 1 })
  put(path.join(dir, '_next/static/chunks/carried.js'), 'from an older release')
  assert.deepEqual(nativeFiles(dir), ['chunks/p-n.js'], 'files added after the record are not native')
  assert.ok(!fs.readdirSync(dir).some((e) => e.includes('.tmp-')), 'manifest written atomically')
  // a manifest is never trusted to point outside _next/static
  fs.writeFileSync(path.join(dir, NATIVE_MANIFEST), JSON.stringify({ schema: 1, files: ['../../index.html', '/etc/passwd', 'chunks/./x.js', 'chunks/p-n.js'] }))
  assert.deepEqual(nativeFiles(dir), ['chunks/p-n.js'])
  fs.writeFileSync(path.join(dir, NATIVE_MANIFEST), '{broken')
  assert.deepEqual(nativeFiles(dir).sort(), ['chunks/carried.js', 'chunks/p-n.js'], 'unreadable manifest: everything')
  // the manifest is not a servable file and is never gzipped
  precompress(dir)
  assert.ok(!fs.existsSync(path.join(dir, `${NATIVE_MANIFEST}.gz`)))
  assert.equal(writeBuildInfo(dir, { id: ids[0], gitSha: 'a', nextVersion: 'x' }).files, 4)
})

test('carry moves only native files: carried chunks never accumulate across releases', () => {
  // 10 builds, one new chunk each, carry-forward from current + previous, swap, prune keep 3 (the
  // critic's simulation, C2-reliability-ops-09). Before the fix release n held all n chunks.
  const dist = tmp()
  const counts = []
  for (let n = 0; n < 10; n++) {
    const id = `20261024-${String(100000 + n * 100)}-abcdef${n}`
    const dir = makeExport(path.join(dist, 'releases', id), `c${n}`)
    recordNative(dir)
    carry(dir, pickCarry(dist, id).dirs)
    swap(dist, id)
    prune(dist, 3)
    counts.push(walk(path.join(dir, '_next/static')).files.length)
  }
  assert.deepEqual(counts, [1, 2, 3, 3, 3, 3, 3, 3, 3, 3])
  // the newest release still serves the chunks of the two builds before it (an open window survives 2 swaps)
  const cur = path.join(dist, 'current', '_next/static/chunks')
  assert.deepEqual(fs.readdirSync(cur).sort(), ['p-c7.js', 'p-c8.js', 'p-c9.js'])
})

test('swap is atomic, keeps previous, refuses non-symlinks', () => {
  const dist = makeDist(3)
  assert.deepEqual(swap(dist, ids[0]), { current: ids[0], previous: null })
  assert.deepEqual(swap(dist, ids[1]), { current: ids[1], previous: ids[0] })
  assert.equal(fs.readlinkSync(path.join(dist, 'current')), `releases/${ids[1]}`)
  assert.equal(pointerId(dist, 'previous'), ids[0])
  assert.throws(() => swap(dist, ids[1]), /already current/)
  assert.throws(() => swap(dist, '20990101-000000-0000000'), /release not found/)
  assert.ok(!fs.readdirSync(dist).some((e) => e.includes('.tmp-')), 'no temp links left')
  const blocked = makeDist(1)
  fs.mkdirSync(path.join(blocked, 'current'))
  assert.throws(() => atomicPoint(blocked, 'current', ids[0]), /not a symlink/)
})

test('swap never leaves a moment without a current link (rename(2) replaces the link)', async () => {
  const dist = makeDist(2)
  swap(dist, ids[0])
  let stop = false
  let misses = 0
  let reads = 0
  const reader = (async () => {
    while (!stop) {
      try {
        fs.statSync(path.join(dist, 'current', 'index.html'))
      } catch {
        misses++
      }
      reads++
      await new Promise((r) => setImmediate(r))
    }
  })()
  for (let i = 0; i < 200; i++) swap(dist, ids[i % 2 === 0 ? 1 : 0])
  stop = true
  await reader
  assert.equal(misses, 0, `${misses}/${reads} reads saw no current`)
})

test('rollback walks back, carries the outgoing chunks, accepts an explicit id, refuses when nothing is older', () => {
  const dist = makeDist(3)
  swap(dist, ids[0]); swap(dist, ids[1]); swap(dist, ids[2])
  const r1 = rollback(dist)
  assert.deepEqual([r1.current, r1.previous], [ids[1], ids[2]])
  assert.equal(r1.carried_files, 1, "the outgoing release's chunk is carried into the target")
  assert.ok(fs.existsSync(path.join(dist, 'releases', ids[1], '_next/static/chunks/p-2.js')))
  const r2 = rollback(dist)
  assert.deepEqual([r2.current, r2.previous], [ids[0], ids[1]], 'a second rollback goes further back')
  assert.throws(() => rollback(dist), /no release older/)
  const r3 = rollback(dist, ids[2])
  assert.deepEqual([r3.current, r3.previous], [ids[2], ids[0]])
  assert.throws(() => rollback(dist, ids[2]), /already current/)
  assert.throws(() => rollback(dist, '20990101-000000-0000000'), /no such release/)
})

test('prune keeps the newest N plus current and previous, and removes stale temp entries', () => {
  const dist = makeDist(4)
  swap(dist, ids[0]); swap(dist, ids[1])          // current = 1, previous = 0
  fs.mkdirSync(path.join(dist, 'releases', '.incoming-x-999999'), { recursive: true })
  fs.symlinkSync('releases/x', path.join(dist, '.current.tmp-1-abcd'))
  const r = prune(dist, 2)                        // newest 2 = 2,3 ; plus 0 and 1 protected
  assert.deepEqual(r.removed, [])
  assert.deepEqual(r.kept, ids)
  swap(dist, ids[3])                              // current = 3, previous = 1 → 0 is now prunable
  assert.deepEqual(prune(dist, 2).removed, [ids[0]])
  assert.deepEqual(listReleases(dist), ids.slice(1))
  assert.ok(!fs.existsSync(path.join(dist, 'releases', '.incoming-x-999999')))
  assert.ok(!fs.existsSync(path.join(dist, '.current.tmp-1-abcd')))
  assert.throws(() => prune(dist, 1), /--keep/)
})

test('pickCarry prefers current and previous, then newest; excludes the new id', () => {
  const dist = makeDist(4)
  swap(dist, ids[0]); swap(dist, ids[1])
  assert.deepEqual(pickCarry(dist, ids[3]).ids, [ids[1], ids[0]])
  assert.deepEqual(pickCarry(dist, ids[1]).ids, [ids[0], ids[3]])
  assert.deepEqual(pickCarry(makeDist(0), ids[0]).ids, [])
})

test('build-info counts servable files and is written atomically', () => {
  const dir = makeExport(tmp())
  precompress(dir)
  const info = writeBuildInfo(dir, { id: ids[0], gitSha: 'aaaaaaa', nextVersion: '15.5.18', carried: 3, buildMs: 1234 })
  assert.equal(info.files, 3)
  assert.equal(info.gz_files, 2)
  assert.equal(info.carried_forward_files, 3)
  const onDisk = JSON.parse(fs.readFileSync(path.join(dir, 'build-info.json'), 'utf8'))
  assert.deepEqual(Object.keys(onDisk).slice(0, 6), ['id', 'git_sha', 'built_at', 'files', 'bytes', 'next_version'])
  assert.ok(!fs.readdirSync(dir).some((e) => e.includes('.tmp-')))
})

test('list reports pointers and sizes; CLI rejects bad input', () => {
  const dist = makeDist(2)
  swap(dist, ids[0])
  writeBuildInfo(path.join(dist, 'releases', ids[0]), { id: ids[0], gitSha: 'a', nextVersion: 'x' })
  const l = list(dist)
  assert.equal(l.current, ids[0])
  assert.equal(l.releases.find((r) => r.id === ids[0])?.current, true)
  assert.throws(() => runCli(['nope']), /unknown subcommand/)
  assert.throws(() => runCli(['swap', '--dist']), /needs a value/)
  assert.throws(() => runCli(['swap', '--dist', dist]), /--id is required/)
  assert.throws(() => runCli(['prune', '--dist', dist, '--keep', 'x']), /non-negative integer/)
})

test('a dirty build declares itself in the release id, not only in the manifest', () => {
  // The id is what gets quoted in a report, a bug or a commit message; `git_dirty` sits in a manifest field
  // nobody reads. An id that names a commit the bundle was never built from defeats the one thing a build id
  // exists for — and /version served exactly that for most of 14 Nov.
  assert.ok(RELEASE_ID_RE.test('20261114-133000-abc1234-dirty'))
  assert.ok(RELEASE_ID_RE.test('20261114-133000-abc1234'))
  assert.ok(!RELEASE_ID_RE.test('20261114-133000-abc1234-DIRTY'))
  assert.ok(!RELEASE_ID_RE.test('20261114-133000-abc1234-dirty-dirty'))
  assert.ok(!RELEASE_ID_RE.test('20261114-133000-abc1234-wip'))
})

test('build_ui.sh appends -dirty from the same flag the manifest records', () => {
  const sh = fs.readFileSync(new URL('../../scripts/build_ui.sh', import.meta.url), 'utf8')
  const code = sh.split('\n').filter((l) => !l.trim().startsWith('#')).join('\n')
  assert.match(code, /GIT_DIRTY.*=.*1.*_suffix="-dirty"|_suffix="-dirty"/)
  assert.match(code, /\(-dirty\)\?\$/)       // the validator accepts it too, or every dirty build would die
})

test('the dirty check excludes exactly what the build does not ship', () => {
  // R15 / Platform: the exclusion list went stale twice — five hand-written directories while the build
  // staged every top-level entry, then the whole tree including paths the build provably never ships. The
  // shell now reads STAGE_EXCLUDE_TOP itself, so "could an uncommitted file have changed the bundle?" is
  // answered by the only code that knows which files those are.
  const sh = fs.readFileSync(new URL('../../scripts/build_ui.sh', import.meta.url), 'utf8')
  const code = sh.split('\n').filter((l) => !l.trim().startsWith('#')).join('\n')
  assert.match(code, /STAGE_EXCLUDE_TOP/, 'the dirty check no longer derives its exclusions')
  assert.match(code, /:\(exclude\)ui\//, 'the exclusions are not applied as a git pathspec')
  // and it must refuse rather than silently widen: an empty list would quietly re-include everything, which
  // is exactly how the first version of this failed (a two-stage pipe produced nothing and still "worked")
  assert.match(code, /\[ -n "\$_ex" \] \|\| die/, 'an unreadable exclusion list must stop the build, not widen it')
  // the set itself must still cover the obvious non-bundle inputs
  for (const top of ['node_modules', 'dist', 'scripts', 'package-lock.json', 'tsconfig.tsbuildinfo']) {
    assert.ok(STAGE_EXCLUDE_TOP.has(top), `${top} must not count toward a dirty bundle`)
  }
})
