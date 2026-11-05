#!/usr/bin/env node
// @ts-check
/**
 * SuryaDhana UI release helper: the filesystem half of scripts/build_ui.sh.
 *
 * The bash driver owns locking, the Next build and the overall flow; every step that must be exact
 * (staging copy, output verification, deterministic gzip, build-info, chunk carry-forward, the
 * atomic symlink swap, pruning, rollback) lives here so it is testable (`node --test ui/scripts/*.test.mjs`).
 *
 * Layout of a dist root (default ui/dist):
 *   releases/<id>/        one static export per release (id = YYYYmmdd-HHMMSS-<sha7>, IST)
 *   current  -> releases/<id>   what ui-api serves (resolved per request, so a swap is live)
 *   previous -> releases/<id>   what was current before the last swap/rollback (never pruned)
 *
 * Every subcommand prints ONE JSON object on stdout (machine-readable for the driver) and exits
 * non-zero with `release.mjs: <message>` on stderr on failure.
 *
 * Subcommands:
 *   stage        --src <ui dir> --dest <staging dir>
 *   verify       --dir <export dir>
 *   precompress  --dir <export dir> [--min-bytes 1024]
 *   carry        --dest <release dir> --from <release dir> [--from ...]
 *   build-info   --dir <release dir> --id <id> --git-sha <sha> --next-version <v>
 *                [--git-dirty 0|1] [--source-sha256 <hex>] [--carried <n>] [--build-ms <n>]
 *   swap         --dist <dist root> --id <id>
 *   rollback     --dist <dist root> [--id <id>]
 *   prune        --dist <dist root> [--keep 3]
 *   list         --dist <dist root>
 *   pick-carry   --dist <dist root> --exclude <id> [--count 2]
 *   record-native --dir <release dir>
 *   carry-forward --dest <release dir> --dist <dist root> --exclude <id> [--count 2]
 *                (record-native on dest, then pick-carry + carry)
 *
 * Carry-forward is bounded: each release records the `_next/static` files its own build produced
 * (`.native-static.json`, written before anything is carried in), and only those NATIVE files travel to later
 * releases. A release therefore holds its own chunks plus the native chunks of current and previous (an open
 * window survives two swaps), never the chunks those releases had themselves carried, so dead chunks do not
 * pile up release after release (desktop review C2-reliability-ops-09). A release built before the manifest
 * existed counts every file it has as native (the old behaviour) until it is pruned.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { fileURLToPath } from 'node:url'

/** Release ids: YYYYmmdd-HHMMSS-<7 hex>. They sort chronologically as plain strings. */
export const RELEASE_ID_RE = /^\d{8}-\d{6}-[0-9a-f]{7}$/
/** File types worth gzip-precompressing (text-like). Already-compressed formats are skipped. */
export const COMPRESSIBLE_EXT = new Set([
  '.html', '.js', '.mjs', '.css', '.txt', '.json', '.svg', '.xml', '.map', '.webmanifest', '.ttf', '.otf', '.csv',
])
/** Top-level entries of ui/ that never belong in a staging copy (build outputs, deps, local state). */
// package-lock.json stays out so Next sees ONE lockfile (ui/package-lock.json, found upward) and does not
// warn about an ambiguous workspace root; modules resolve upward to ui/node_modules either way.
const STAGE_EXCLUDE_TOP = new Set([
  'node_modules', 'dist', 'out', 'scripts', '.build-ui', '.gstack', 'tsconfig.tsbuildinfo', 'package-lock.json',
])
/** Marker that ui/next.config.js requires before it allows NEXT_OUTPUT=export. */
export const STAGING_MARKER = '.suryadhana-export-staging'
/** Per-release list of its own (native, not carried) `_next/static` files. A dotfile: ui-api never serves it. */
export const NATIVE_MANIFEST = '.native-static.json'

class ReleaseError extends Error {}

/** @param {string} msg @returns {never} */
function fail(msg) {
  throw new ReleaseError(msg)
}

// ── small fs helpers ──────────────────────────────────────────────────────────────────────────

/**
 * All regular files under `root` (relative POSIX paths, sorted). Symlinks are reported, not followed.
 * @param {string} root
 * @returns {{files: string[], symlinks: string[]}}
 */
export function walk(root) {
  /** @type {string[]} */ const files = []
  /** @type {string[]} */ const symlinks = []
  /** @param {string} dir @param {string} rel */
  const rec = (dir, rel) => {
    const entries = fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
    for (const e of entries) {
      const r = rel ? `${rel}/${e.name}` : e.name
      const abs = path.join(dir, e.name)
      if (e.isSymbolicLink()) symlinks.push(r)
      else if (e.isDirectory()) rec(abs, r)
      else if (e.isFile()) files.push(r)
    }
  }
  rec(root, '')
  return { files, symlinks }
}

/** @param {string} p */
function isDir(p) {
  try {
    return fs.statSync(p).isDirectory()
  } catch {
    return false
  }
}

/** @param {string} p @returns {string | null} target of a symlink, or null */
function readLinkOrNull(p) {
  try {
    return fs.readlinkSync(p)
  } catch {
    return null
  }
}

/**
 * Release id a dist-root pointer (current/previous) refers to, or null.
 * @param {string} dist @param {'current' | 'previous'} name
 */
export function pointerId(dist, name) {
  const t = readLinkOrNull(path.join(dist, name))
  if (!t) return null
  const id = path.basename(t)
  return RELEASE_ID_RE.test(id) && isDir(path.join(dist, 'releases', id)) ? id : null
}

/** @param {string} dist @returns {string[]} release ids, oldest first */
export function listReleases(dist) {
  const dir = path.join(dist, 'releases')
  if (!isDir(dir)) return []
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && RELEASE_ID_RE.test(e.name))
    .map((e) => e.name)
    .sort()
}

/**
 * Atomically point `<dist>/<name>` at `releases/<id>`: a temp symlink renamed over the old one.
 * rename(2) replaces the link itself (it never follows a symlink in the last path component), so a
 * reader resolving the path sees either the old release or the new one, never a missing link.
 * @param {string} dist @param {'current' | 'previous'} name @param {string} id
 */
export function atomicPoint(dist, name, id) {
  if (!RELEASE_ID_RE.test(id)) fail(`bad release id: ${id}`)
  if (!isDir(path.join(dist, 'releases', id))) fail(`release not found: ${id}`)
  const link = path.join(dist, name)
  const existing = fs.lstatSync(link, { throwIfNoEntry: false })
  if (existing && !existing.isSymbolicLink()) fail(`${link} exists and is not a symlink; refusing to replace it`)
  const tmp = path.join(dist, `.${name}.tmp-${process.pid}-${crypto.randomBytes(4).toString('hex')}`)
  fs.symlinkSync(path.posix.join('releases', id), tmp)
  try {
    fs.renameSync(tmp, link)
  } catch (err) {
    fs.rmSync(tmp, { force: true })
    throw err
  }
}

// ── subcommands ───────────────────────────────────────────────────────────────────────────────

/**
 * Copy the UI sources into a staging project dir and drop the export marker in it.
 * Excludes deps, every `.next*` build dir, dist/out, scripts, local tool state and macOS junk.
 * Returns a sha256 over (relative path, bytes) of every staged source file, so a build can be tied
 * to its exact sources even on a dirty working tree.
 * @param {string} src @param {string} dest
 */
export function stage(src, dest) {
  if (!fs.existsSync(path.join(src, 'next.config.js'))) fail(`${src} has no next.config.js`)
  if (fs.existsSync(dest) && fs.readdirSync(dest).length) fail(`staging dir is not empty: ${dest}`)
  fs.mkdirSync(dest, { recursive: true })
  const srcAbs = path.resolve(src)
  /** @param {string} from */
  const keep = (from) => {
    const base = path.basename(from)
    return base !== '.DS_Store' && !base.endsWith('.log')
  }
  // Entry by entry: the staging dir lives inside ui/ (so node_modules resolves upward without
  // symlinks), and fs.cpSync refuses to copy a directory into its own subdirectory.
  for (const top of fs.readdirSync(srcAbs).sort()) {
    if (STAGE_EXCLUDE_TOP.has(top) || top.startsWith('.next') || top.startsWith('.export') || !keep(top)) continue
    fs.cpSync(path.join(srcAbs, top), path.join(dest, top), { recursive: true, verbatimSymlinks: true, filter: keep })
  }
  fs.writeFileSync(path.join(dest, STAGING_MARKER), 'staging copy made by scripts/build_ui.sh; safe to delete\n')
  const { files } = walk(dest)
  const h = crypto.createHash('sha256')
  let bytes = 0
  for (const rel of files) {
    if (rel === STAGING_MARKER) continue
    const buf = fs.readFileSync(path.join(dest, rel))
    bytes += buf.length
    h.update(rel).update('\0').update(buf).update('\0')
  }
  return { dest, files: files.length - 1, bytes, source_sha256: h.digest('hex') }
}

/**
 * Check a static export is complete and contains no route handlers.
 * @param {string} dir
 */
export function verify(dir) {
  /** @type {string[]} */ const problems = []
  const index = path.join(dir, 'index.html')
  if (!fs.existsSync(index)) problems.push('index.html missing')
  if (!isDir(path.join(dir, '_next', 'static'))) problems.push('_next/static missing')
  if (fs.existsSync(path.join(dir, 'api'))) problems.push('an api/ path exists in the export (route handlers must be excluded)')
  const { files, symlinks } = walk(dir)
  if (symlinks.length) problems.push(`symlinks in export: ${symlinks.slice(0, 5).join(', ')}`)
  const apiFiles = files.filter((f) => f === 'api' || f.startsWith('api/'))
  if (apiFiles.length) problems.push(`api files in export: ${apiFiles.slice(0, 5).join(', ')}`)
  /** @type {string[]} */ const missingRefs = []
  if (fs.existsSync(index)) {
    const html = fs.readFileSync(index, 'utf8')
    const refs = new Set([...html.matchAll(/\/_next\/static\/[^"'\s)\\]+/g)].map((m) => m[0]))
    if (!refs.size) problems.push('index.html references no /_next/static assets')
    for (const ref of refs) {
      const rel = decodeURIComponent(ref.slice(1).split('?')[0])
      if (!fs.existsSync(path.join(dir, rel))) missingRefs.push(ref)
    }
    if (missingRefs.length) problems.push(`index.html references missing assets: ${missingRefs.slice(0, 5).join(', ')}`)
  }
  const staticFiles = files.filter((f) => f.startsWith('_next/static/'))
  if (!staticFiles.some((f) => f.endsWith('.js'))) problems.push('_next/static has no .js chunks')
  if (problems.length) fail(`export verification failed in ${dir}: ${problems.join('; ')}`)
  return {
    dir,
    files: files.length,
    static_files: staticFiles.length,
    has_404: fs.existsSync(path.join(dir, '404.html')),
  }
}

/**
 * Write `<file>.gz` (zlib level 9) next to every compressible file larger than `minBytes`.
 * Deterministic: Node's gzip header carries mtime 0 and no file name, so identical input gives
 * identical bytes. A .gz that would not be smaller than its source is not written. The .gz mtime
 * is set to the source's mtime so caches see one consistent generation.
 * @param {string} dir @param {number} [minBytes]
 */
export function precompress(dir, minBytes = 1024) {
  let written = 0
  let skipped = 0
  let inBytes = 0
  let outBytes = 0
  for (const rel of walk(dir).files) {
    if (rel.endsWith('.gz') || rel === 'build-info.json' || rel === NATIVE_MANIFEST) continue
    if (!COMPRESSIBLE_EXT.has(path.extname(rel).toLowerCase())) continue
    const abs = path.join(dir, rel)
    const st = fs.statSync(abs)
    if (st.size <= minBytes) continue
    const src = fs.readFileSync(abs)
    const gz = zlib.gzipSync(src, { level: 9 })
    if (gz.length >= src.length) {
      skipped++
      continue
    }
    const gzPath = `${abs}.gz`
    fs.writeFileSync(gzPath, gz)
    fs.utimesSync(gzPath, st.atimeMs / 1000, st.mtimeMs / 1000) // µs precision (Date would truncate to ms)
    written++
    inBytes += src.length
    outBytes += gz.length
  }
  return { dir, gz_files: written, not_smaller: skipped, source_bytes: inBytes, gz_bytes: outBytes }
}

/**
 * Record the release's own `_next/static` files in `<dir>/.native-static.json` (atomic write). Call it on a
 * fresh build output, before anything is carried in.
 * @param {string} dir
 */
export function recordNative(dir) {
  const staticDir = path.join(dir, '_next', 'static')
  const files = isDir(staticDir) ? walk(staticDir).files : []
  const tmp = path.join(dir, `${NATIVE_MANIFEST}.tmp-${process.pid}`)
  fs.writeFileSync(tmp, JSON.stringify({ schema: 1, files }) + '\n')
  fs.renameSync(tmp, path.join(dir, NATIVE_MANIFEST))
  return { dir, native_files: files.length }
}

/** @param {string} rel a manifest entry: relative, normalised, no `..` (never trusted to stay inside the dir) */
function safeRel(rel) {
  return typeof rel === 'string' && rel !== '' && !path.isAbsolute(rel) && !rel.split('/').some((s) => s === '..' || s === '.' || s === '')
}

/**
 * The `_next/static` files (relative to it) a release needs for its own pages: its native manifest when it has a
 * valid one, otherwise (a release built before manifests existed) every file it has.
 * @param {string} dir
 */
export function nativeFiles(dir) {
  const staticDir = path.join(dir, '_next', 'static')
  if (!isDir(staticDir)) return []
  try {
    const m = JSON.parse(fs.readFileSync(path.join(dir, NATIVE_MANIFEST), 'utf8'))
    if (m && m.schema === 1 && Array.isArray(m.files)) return m.files.filter(safeRel)
  } catch {
    // no manifest (legacy release) or an unreadable one: fall back to everything the release has
  }
  return walk(staticDir).files
}

/**
 * Copy the NATIVE `_next/static/**` files of older releases (see nativeFiles) that `dest` lacks (never
 * overwriting), so an open window built from an older release can still lazy-load its chunks after a swap.
 * Files those releases had carried in themselves are not copied again (bounded growth). mtimes are preserved,
 * so the copies keep the ETag/Last-Modified the window already has.
 * @param {string} dest @param {string[]} froms
 */
export function carry(dest, froms) {
  let copied = 0
  let bytes = 0
  for (const from of froms) {
    const staticDir = path.join(from, '_next', 'static')
    if (!isDir(staticDir)) continue
    for (const rel of nativeFiles(from)) {
      const target = path.join(dest, '_next', 'static', rel)
      if (fs.existsSync(target)) continue
      const source = path.join(staticDir, rel)
      if (!fs.existsSync(source)) continue // listed in the manifest but gone: nothing to carry
      fs.mkdirSync(path.dirname(target), { recursive: true })
      try {
        fs.copyFileSync(source, target, fs.constants.COPYFILE_EXCL)
      } catch (err) {
        if (/** @type {NodeJS.ErrnoException} */ (err).code === 'EEXIST') continue
        throw err
      }
      const st = fs.statSync(source)
      fs.utimesSync(target, st.atimeMs / 1000, st.mtimeMs / 1000)
      copied++
      bytes += st.size
    }
  }
  return { dest, carried_files: copied, carried_bytes: bytes }
}

/**
 * Write build-info.json into a release root (served by ui-api at /build-info.json, no-store).
 * `files`/`bytes` count the servable files excluding .gz siblings and build-info.json itself.
 * @param {string} dir
 * @param {{id: string, gitSha: string, nextVersion: string, gitDirty?: boolean, sourceSha256?: string,
 *          carried?: number, buildMs?: number, builtAt?: string}} meta
 */
export function writeBuildInfo(dir, meta) {
  let files = 0
  let bytes = 0
  let gzFiles = 0
  let gzBytes = 0
  for (const rel of walk(dir).files) {
    if (rel === 'build-info.json' || rel === NATIVE_MANIFEST) continue
    const size = fs.statSync(path.join(dir, rel)).size
    if (rel.endsWith('.gz')) {
      gzFiles++
      gzBytes += size
    } else {
      files++
      bytes += size
    }
  }
  const info = {
    id: meta.id,
    git_sha: meta.gitSha,
    built_at: meta.builtAt || new Date().toISOString(),
    files,
    bytes,
    next_version: meta.nextVersion,
    schema: 1,
    git_dirty: Boolean(meta.gitDirty),
    source_sha256: meta.sourceSha256 || null,
    gz_files: gzFiles,
    gz_bytes: gzBytes,
    carried_forward_files: meta.carried || 0,
    build_ms: meta.buildMs ?? null,
  }
  const tmp = path.join(dir, `.build-info.json.tmp-${process.pid}`)
  fs.writeFileSync(tmp, JSON.stringify(info, null, 2) + '\n')
  fs.renameSync(tmp, path.join(dir, 'build-info.json'))
  return info
}

/**
 * Make release `id` current: previous := old current, then current := id (both atomic).
 * @param {string} dist @param {string} id
 */
export function swap(dist, id) {
  const before = pointerId(dist, 'current')
  if (before === id) fail(`${id} is already current`)
  if (before) atomicPoint(dist, 'previous', before)
  atomicPoint(dist, 'current', id)
  return { current: id, previous: before }
}

/**
 * Roll back: make `id` (or, by default, the newest release older than current) current.
 * The release rolled back FROM becomes `previous` (kept, inspectable). Repeating --rollback walks
 * further back instead of toggling into the build that was just rolled back.
 * Before the swap, the outgoing release's native `_next/static` files that the target lacks are copied
 * into it (add-only, never overwriting): windows still running the newer build lazy-load per-tab chunks
 * (`next/dynamic`), and those must keep resolving after the rollback.
 * @param {string} dist @param {string | null} [id]
 */
export function rollback(dist, id = null) {
  const cur = pointerId(dist, 'current')
  const all = listReleases(dist)
  let target = id
  if (target) {
    if (!all.includes(target)) fail(`no such release: ${target} (have: ${all.join(', ') || 'none'})`)
    if (target === cur) fail(`${target} is already current`)
  } else {
    const older = all.filter((r) => (cur ? r < cur : true))
    target = older.length ? older[older.length - 1] : null
    if (!target) fail(`no release older than ${cur || '(none)'} to roll back to`)
  }
  const carried = cur
    ? carry(path.join(dist, 'releases', target), [path.join(dist, 'releases', cur)]).carried_files
    : 0
  if (cur) atomicPoint(dist, 'previous', cur)
  atomicPoint(dist, 'current', target)
  return { current: target, previous: cur, carried_files: carried }
}

/**
 * Delete old releases, keeping the newest `keep`, plus current and previous whatever their age.
 * Also removes stale temp entries (.incoming-*, .current.tmp-*) left by killed runs.
 * @param {string} dist @param {number} [keep]
 */
export function prune(dist, keep = 3) {
  if (!Number.isInteger(keep) || keep < 2) fail('--keep must be an integer >= 2')
  const all = listReleases(dist)
  const protect = new Set(all.slice(-keep))
  for (const p of [pointerId(dist, 'current'), pointerId(dist, 'previous')]) if (p) protect.add(p)
  /** @type {string[]} */ const removed = []
  for (const id of all) {
    if (protect.has(id)) continue
    fs.rmSync(path.join(dist, 'releases', id), { recursive: true, force: true })
    removed.push(id)
  }
  const relDir = path.join(dist, 'releases')
  if (isDir(relDir)) {
    for (const e of fs.readdirSync(relDir)) {
      if (e.startsWith('.incoming-')) {
        const pid = Number(e.split('-').pop())
        if (!Number.isFinite(pid) || !isAlive(pid)) fs.rmSync(path.join(relDir, e), { recursive: true, force: true })
      }
    }
  }
  for (const e of fs.existsSync(dist) ? fs.readdirSync(dist) : []) {
    if (/^\.(current|previous)\.tmp-/.test(e)) fs.rmSync(path.join(dist, e), { force: true })
  }
  return { kept: [...protect].sort(), removed }
}

/** @param {number} pid */
function isAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (err) {
    return /** @type {NodeJS.ErrnoException} */ (err).code === 'EPERM'
  }
}

/**
 * The releases whose chunks a new release should carry forward: current, previous, then newest
 * by id — distinct, excluding the new one.
 * @param {string} dist @param {string} exclude @param {number} [count]
 */
export function pickCarry(dist, exclude, count = 2) {
  const order = [pointerId(dist, 'current'), pointerId(dist, 'previous'), ...listReleases(dist).reverse()]
  /** @type {string[]} */ const out = []
  for (const id of order) {
    if (!id || id === exclude || out.includes(id)) continue
    out.push(id)
    if (out.length >= count) break
  }
  return { ids: out, dirs: out.map((id) => path.join(dist, 'releases', id)) }
}

/** @param {string} dist */
export function list(dist) {
  const cur = pointerId(dist, 'current')
  const prev = pointerId(dist, 'previous')
  return {
    dist,
    current: cur,
    previous: prev,
    releases: listReleases(dist).map((id) => {
      /** @type {Record<string, unknown> | null} */
      let info = null
      try {
        info = JSON.parse(fs.readFileSync(path.join(dist, 'releases', id, 'build-info.json'), 'utf8'))
      } catch {
        info = null
      }
      return { id, current: id === cur, previous: id === prev, bytes: info?.bytes ?? null, built_at: info?.built_at ?? null }
    }),
  }
}

// ── CLI ───────────────────────────────────────────────────────────────────────────────────────

/** @param {string[]} argv @returns {{cmd: string, opts: Record<string, string[]>}} */
function parseCli(argv) {
  const [cmd = '', ...rest] = argv
  /** @type {Record<string, string[]>} */
  const opts = {}
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i]
    if (!a.startsWith('--')) fail(`unexpected argument: ${a}`)
    const v = rest[i + 1]
    if (v === undefined || v.startsWith('--')) fail(`${a} needs a value`)
    ;(opts[a.slice(2)] ||= []).push(v)
    i++
  }
  return { cmd, opts }
}

/** @param {Record<string, string[]>} opts @param {string} k @returns {string} */
function req(opts, k) {
  const v = opts[k]?.[0]
  if (!v) fail(`--${k} is required`)
  return v
}

/** @param {Record<string, string[]>} opts @param {string} k @param {number} d */
function intOpt(opts, k, d) {
  const v = opts[k]?.[0]
  if (v === undefined) return d
  const n = Number(v)
  if (!Number.isInteger(n) || n < 0) fail(`--${k} must be a non-negative integer`)
  return n
}

/** @param {string[]} argv */
export function runCli(argv) {
  const { cmd, opts } = parseCli(argv)
  switch (cmd) {
    case 'stage':
      return stage(req(opts, 'src'), req(opts, 'dest'))
    case 'verify':
      return verify(req(opts, 'dir'))
    case 'precompress':
      return precompress(req(opts, 'dir'), intOpt(opts, 'min-bytes', 1024))
    case 'carry':
      return carry(req(opts, 'dest'), opts.from || [])
    case 'build-info':
      return writeBuildInfo(req(opts, 'dir'), {
        id: req(opts, 'id'),
        gitSha: req(opts, 'git-sha'),
        nextVersion: req(opts, 'next-version'),
        gitDirty: opts['git-dirty']?.[0] === '1',
        sourceSha256: opts['source-sha256']?.[0],
        carried: intOpt(opts, 'carried', 0),
        buildMs: opts['build-ms'] ? intOpt(opts, 'build-ms', 0) : undefined,
      })
    case 'swap':
      return swap(req(opts, 'dist'), req(opts, 'id'))
    case 'rollback':
      return rollback(req(opts, 'dist'), opts.id?.[0] || null)
    case 'prune':
      return prune(req(opts, 'dist'), intOpt(opts, 'keep', 3))
    case 'list':
      return list(req(opts, 'dist'))
    case 'pick-carry':
      return pickCarry(req(opts, 'dist'), req(opts, 'exclude'), intOpt(opts, 'count', 2))
    case 'record-native':
      return recordNative(req(opts, 'dir'))
    case 'carry-forward': {
      const dest = req(opts, 'dest')
      const native = recordNative(dest) // before carrying: only the build's own files are native
      const picks = pickCarry(req(opts, 'dist'), req(opts, 'exclude'), intOpt(opts, 'count', 2))
      return { from: picks.ids, native_files: native.native_files, ...carry(dest, picks.dirs) }
    }
    default:
      return fail(`unknown subcommand: ${cmd || '(none)'} (see the header of ui/scripts/release.mjs)`)
  }
}

/** realpath on both sides: on macOS /var and /tmp are symlinks into /private, so the same file can be
 * spelled two ways. */
function isMainModule() {
  if (!process.argv[1]) return false
  try {
    return fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
}
const isMain = isMainModule()
if (isMain) {
  try {
    process.stdout.write(JSON.stringify(runCli(process.argv.slice(2))) + '\n')
  } catch (err) {
    const msg = err instanceof ReleaseError ? err.message : err instanceof Error ? `${err.name}: ${err.message}` : String(err)
    process.stderr.write(`release.mjs: ${msg}\n`)
    process.exit(1)
  }
}
