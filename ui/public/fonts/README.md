# Self-hosted terminal fonts

The terminal's two typefaces, served from the UI's own origin, so no font request leaves the machine. The
desktop app and the browser render the same faces, and they work offline. `@font-face` rules: the D4 section at
the end of `ui/app/globals.css`. Preloads: `ui/app/layout.tsx`.

| File | Family · weight · subset | Source URL (fonts.gstatic.com/s/…) | sha256 (first 16) |
|---|---|---|---|
| `chakra-petch-v13-500-latin.woff2` | Chakra Petch 500 latin | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkebIl1R5_F_gUk0w.woff2` | adf007cd277ef6da |
| `chakra-petch-v13-500-latin-ext.woff2` | Chakra Petch 500 latin-ext | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkebIl1SZ_F_gUk0wzH.woff2` | b821fcd55102d303 |
| `chakra-petch-v13-600-latin.woff2` | Chakra Petch 600 latin | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeQI51R5_F_gUk0w.woff2` | 4d6d5f0b31b3a471 |
| `chakra-petch-v13-600-latin-ext.woff2` | Chakra Petch 600 latin-ext | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeQI51SZ_F_gUk0wzH.woff2` | 140bd5c457550ed1 |
| `chakra-petch-v13-700-latin.woff2` | Chakra Petch 700 latin | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeJI91R5_F_gUk0w.woff2` | 3c2433eb167176cd |
| `chakra-petch-v13-700-latin-ext.woff2` | Chakra Petch 700 latin-ext | `chakrapetch/v13/cIflMapbsEk7TDLdtEz1BwkeJI91SZ_F_gUk0wzH.woff2` | afe317b164b50683 |
| `jetbrains-mono-v24-latin.woff2` | JetBrains Mono variable (400–700) latin | `jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwgknk-4.woff2` | 2c32b9b3ee358c11 |
| `jetbrains-mono-v24-latin-ext.woff2` | JetBrains Mono variable (400–700) latin-ext | `jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPx7cwgknk-6nFg.woff2` | 9c38cb2d0d2d93c1 |
| `jetbrains-mono-v24-greek.woff2` | JetBrains Mono variable (400–700) greek | `jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxPcwgknk-6nFg.woff2` | 49c3da6c9a2b279b |

**Why these files:** they are byte-for-byte the files the Google Fonts CSS API served the terminal before
(`css2?family=Chakra+Petch:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap`, fetched
24 Oct 2026 with a current Chrome user agent). So the glyphs, metrics and look are unchanged, and no npm
dependency is added. `@fontsource` would need `ui/package.json` changes and ships slightly different builds.
JetBrains Mono is a variable font, so one file per subset covers all four weights. Kept: latin and latin-ext (the
UI is English plus the rupee sign) and, for JetBrains Mono only, greek: the UI draws σ in 32 places (volatility,
option-pricer, risk and backtest labels), and before self-hosting that glyph came from Google's greek subset of
this same font (C3-10). Cyrillic (JetBrains Mono) and Thai and Vietnamese (Chakra Petch, which has no greek
subset) fall back to system fonts.

**Greek subset (added 25 Oct 2026):** downloaded from the URL in the table, byte-for-byte; it is the file the same
`css2` request above lists under `/* greek */` for all four weights (`unicode-range: U+0370-0377, U+037A-037F,
U+0384-038A, U+038C, U+038E-03A1, U+03A3-03FF`), 6,800 bytes, sha256
`49c3da6c9a2b279b0f1f860f5cfb1f5dc38d88a5c7be9c9b1837bbc4e3db6111`. Same licence as the other JetBrains Mono files
(SIL OFL 1.1, `OFL-JetBrainsMono.txt`). The `@font-face` rules use Google's unicode-range, so the file is fetched
only by a page that actually draws a Greek letter.

**Rupee sign (U+20B9):** Chakra Petch has it. JetBrains Mono does not (checked in the cmap of both the
Google build and upstream v2.304). `globals.css` gives the `JetBrains Mono` family a U+20B9-only face taken
from Chakra Petch latin-ext, weight-matched (400/500 → 500, 600 → 600, 700 → 700). This makes `₹` identical in
WebKit and Chromium.

**Cache:** the file names carry the upstream version (`v13`, `v24`), so they can be served with a long
`max-age` (immutable). A font update means new file names.

**Licence:** SIL Open Font License 1.1, see `OFL-ChakraPetch.txt` and `OFL-JetBrainsMono.txt`.

**Refresh recipe:** fetch the CSS above with a modern UA, keep the `/* latin */` and `/* latin-ext */` blocks (and
JetBrains Mono's `/* greek */` block), download each `src` URL to the names above (version in the name), and
update the table and `globals.css`.
