import type { Metadata, Viewport } from 'next'
import './globals.css'
import { PlatformShell } from '@/components/desktop/PlatformShell'

export const metadata: Metadata = {
  title: 'SuryaDhana Terminal',
  description: 'Quantitative trading terminal for NSE stocks',
}

/** Terminal background (= --t-bg in globals.css). Inline on <html>/<body> so the very first paint is black. */
const TERMINAL_BG = '#05070a'

// <meta name="theme-color"> and <meta name="color-scheme" content="dark">: dark scrollbars, form controls and
// window chrome before any CSS has been parsed (no white flash in WKWebView or a browser).
export const viewport: Viewport = {
  themeColor: TERMINAL_BG,
  colorScheme: 'dark',
}

/**
 * Self-hosted fonts (ui/public/fonts, SIL OFL 1.1; @font-face rules at the end of globals.css). Preloaded: the
 * two faces every page paints first, JetBrains Mono latin (one variable file covers all body weights) and Chakra
 * Petch 700 latin (wordmark, page codes, panel titles). The rest load on demand through unicode-range.
 */
const PRELOAD_FONTS = ['/fonts/jetbrains-mono-v24-latin.woff2', '/fonts/chakra-petch-v13-700-latin.woff2']

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" style={{ background: TERMINAL_BG, colorScheme: 'dark' }}>
      <head>
        {PRELOAD_FONTS.map(href => (
          <link key={href} rel="preload" href={href} as="font" type="font/woff2" crossOrigin="anonymous" />
        ))}
      </head>
      <body className="terminal" style={{ background: TERMINAL_BG, color: '#d6dbe4' }}>
        <PlatformShell>{children}</PlatformShell>
      </body>
    </html>
  )
}
