import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SuryaDhana Terminal',
  description: 'Quantitative trading terminal for NSE stocks',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
        />
      </head>
      <body className="terminal">{children}</body>
    </html>
  )
}
