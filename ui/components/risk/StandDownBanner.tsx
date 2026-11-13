'use client'

/**
 * The terminal-wide STAND DOWN banner (risk/SPEC.md §3, O-F3).
 *
 * A sibling of ConnectionBanner in PlatformShell with the same geometry (24 px strip under the title strip,
 * above the page), shown on EVERY page while the stand-down record carries today's session and is not yet
 * acknowledged. PlatformShell gives it precedence BELOW LINK DOWN / WARMING UP (an outage message outranks a
 * discipline message) and adds its height to --shell-top, exactly like the connection banner.
 *
 * Tone: red outline on the terminal's dark ground, no flashing, 150 ms ease-in (W4 motion rule). Wording per
 * SPEC §3 verbatim: always "your rule" / "your cap"; never "stop trading", never "don't", never a forecast.
 * ACKNOWLEDGE collapses the banner to the header chip — nothing unlocks, because the terminal never blocks.
 */
import { memo } from 'react'
import { Z } from '@/lib/z'
import { T } from '@/components/news/format'
import { BANNER_SUFFIX, bannerMain } from './disciplineModel'
import { acknowledgeStandDown, navigateToDiscipline, useStandDownState } from './useDiscipline'

export { useStandDownState }

/** Same strip height as the connection banner (ShellNotices.BANNER_HEIGHT), duplicated to avoid a cycle. */
export const STAND_DOWN_HEIGHT = 24

const Z_SHELL_BELOW = Z.toast + 9   // one under the title strip (TitleStrip Z_SHELL = Z.toast + 10), like ConnectionBanner

export const StandDownBanner = memo(function StandDownBanner({ top }: { top: number }) {
  const { banner, record } = useStandDownState()
  if (!banner || !record) return null
  return (
    <div role="alert" aria-live="assertive" data-sd-standdown-banner={record.rule}
      style={{ position: 'fixed', left: 0, right: 0, top, height: STAND_DOWN_HEIGHT, zIndex: Z_SHELL_BELOW,
               display: 'flex', alignItems: 'center', gap: 12, padding: '0 8px 0 0', overflow: 'hidden',
               whiteSpace: 'nowrap', fontFamily: T.mono, fontSize: 10, letterSpacing: '.1em',
               background: '#0a0507', color: '#ff8a94', borderBottom: `1px solid ${T.red}`,
               boxShadow: `inset 0 0 0 1px ${T.red}55`, animation: 'sd-standdown-in .15s ease-in both' }}>
      <span style={{ alignSelf: 'stretch', display: 'flex', alignItems: 'center', padding: '0 10px', fontWeight: 700,
                     letterSpacing: '.16em', color: '#05070a', background: T.red }}>STAND DOWN</span>
      <span style={{ fontWeight: 700, textTransform: 'none', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {bannerMain(record)}
      </span>
      <span style={{ color: T.muted }}>{BANNER_SUFFIX}</span>
      <span style={{ flex: 1 }} />
      <button type="button" data-sd-standdown-ack onClick={acknowledgeStandDown}
        style={{ height: 16, padding: '0 8px', background: 'transparent', border: '1px solid currentColor',
                 color: 'inherit', font: 'inherit', fontSize: 9, fontWeight: 700, letterSpacing: '.14em', cursor: 'pointer' }}>
        ACKNOWLEDGE</button>
      <button type="button" onClick={navigateToDiscipline}
        style={{ height: 16, padding: '0 8px', background: 'transparent', border: '1px solid currentColor',
                 color: 'inherit', font: 'inherit', fontSize: 9, fontWeight: 700, letterSpacing: '.14em', cursor: 'pointer' }}>
        REVIEW RULES</button>
      <style>{`@keyframes sd-standdown-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  )
})
