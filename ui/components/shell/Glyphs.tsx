/**
 * Monochrome terminal glyphs that have no safe text form (CT-14 / C1-trader-ux-18): the 🔔 character renders as an
 * Apple colour emoji in WebKit, which breaks the glyph terminal look. SVG in `currentColor`, sized in px, inline
 * with the text it sits in (it takes the chip's or button's colour), no font dependency.
 */

/** A bell for alerts / notifications. `title` makes it an image with an accessible name; otherwise decorative. */
export function BellGlyph({ size = 10, title }: { size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinejoin="miter" aria-hidden={title ? undefined : true} role={title ? 'img' : undefined} focusable="false"
      data-glyph="bell" style={{ display: 'inline-block', verticalAlign: '-1px', flex: 'none' }}>
      {title && <title>{title}</title>}
      <path d="M8 1.8c-2.3 0-4 1.8-4 4.1v2.6L2.5 11.2h11L12 8.5V5.9c0-2.3-1.7-4.1-4-4.1Z" />
      <path d="M6.3 13.2c.3.7 1 1.1 1.7 1.1s1.4-.4 1.7-1.1" strokeLinecap="square" />
    </svg>
  )
}
