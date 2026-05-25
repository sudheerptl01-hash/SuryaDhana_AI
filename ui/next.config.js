/** @type {import('next').NextConfig} */
const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

const nextConfig = {
  reactStrictMode: true,
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
