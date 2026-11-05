/** @type {import('next').NextConfig} */
const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

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

module.exports = nextConfig
