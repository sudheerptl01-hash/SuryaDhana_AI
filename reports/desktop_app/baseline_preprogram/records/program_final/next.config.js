/** @type {import('next').NextConfig} */
const fs = require('fs')
const path = require('path')

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

// ── dev (`next dev`, :3000 hot reload) and prod (`NEXT_DIST_DIR=.next-prod next build/start`) ──
// This object is UNCHANGED from before the desktop program: the resolved config for both modes is
// byte-for-byte identical (proof: ui/scripts/print-next-config.mjs, reports/desktop_app D1 notes).
const nextConfig = {
  reactStrictMode: true,
  // UI_MODE=prod (start-local.sh) builds into .next-prod so a running `next dev` keeps its own .next
  distDir: process.env.NEXT_DIST_DIR || '.next',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_BACKEND}/api/:path*`,
      },
    ]
  },
}

// ── static export (NEXT_OUTPUT=export): the release that ui-api serves at http://127.0.0.1:8010 ──
// Run ONLY through scripts/build_ui.sh. It builds inside a staging copy of ui/ because Next's export
// mode always writes its intermediate build to <project>/.next (with a custom distDir it even
// *redirects* the intermediate there and treats distDir as the output dir), which would clobber the
// dev server's ui/.next. The staging copy carries a marker file; without it this config refuses.
const EXPORT_STAGING_MARKER = '.suryadhana-export-staging'
const UI_BUILD_RE = /^[A-Za-z0-9._-]{1,64}$/

function exportConfig() {
  if (!fs.existsSync(path.join(__dirname, EXPORT_STAGING_MARKER))) {
    throw new Error(
      'NEXT_OUTPUT=export must run through scripts/build_ui.sh (it builds in a staging copy so ' +
        'ui/.next and ui/.next-prod are never touched). Use: scripts/build_ui.sh --out <dir>',
    )
  }
  const uiBuild = process.env.NEXT_PUBLIC_UI_BUILD || 'unversioned'
  if (!UI_BUILD_RE.test(uiBuild)) {
    throw new Error(`NEXT_PUBLIC_UI_BUILD must match ${UI_BUILD_RE} (got ${JSON.stringify(uiBuild)})`)
  }
  // eslint-disable-next-line no-unused-vars
  const { rewrites, distDir, ...shared } = nextConfig // no rewrites: ui-api serves /api on the same origin
  return {
    ...shared,
    output: 'export',
    distDir: '.next', // inside the staging copy; the export lands in <staging>/out
    images: { unoptimized: true },
    // The 6 app/api/**/route.ts stream proxies are dev-only (ui-api serves those streams itself).
    // Dropping the .ts/.js page extensions excludes every route handler without moving files;
    // page.tsx, layout.tsx, global-error.tsx and the icon.svg metadata file are unaffected.
    pageExtensions: ['tsx', 'jsx'],
    env: { NEXT_PUBLIC_UI_BUILD: uiBuild },
  }
}

module.exports = process.env.NEXT_OUTPUT === 'export' ? exportConfig() : nextConfig
