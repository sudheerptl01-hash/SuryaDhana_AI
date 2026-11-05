/**
 * Inline-markdown tokens for the research reader (terminal/Markdown.tsx): **bold**, `code`, [links](url) and
 * *italic*, in text order, as [start, end) spans.
 *
 * RUP-07: written without a regex lookbehind. WebKit before 16.4 (macOS 13.0–13.2, the app's floor is 13.0) cannot
 * parse one, so the page chunk would fail to load. The old pattern's `(?<![\w*])` guard on *italic* (the opening
 * '*' must not follow a word character or another '*') is applied in the loop instead, retrying one character
 * later exactly as the regex engine did. Same tokens as before (pages.check compares both on every report).
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

export interface InlineToken { start: number; end: number; text: string }

export function inlineTokens(text: string): InlineToken[] {
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*(?!\w))/g
  const out: InlineToken[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    const t = m[0]
    if (t[0] === '*' && t[1] !== '*' && m.index > 0 && /[\w*]/.test(text[m.index - 1])) { re.lastIndex = m.index + 1; continue }
    out.push({ start: m.index, end: m.index + t.length, text: t })
  }
  return out
}
