'use client'

/**
 * A SourceChip for a live option-chain snapshot that keeps ageing between polls (BRF reads the chain once a minute): the
 * chain chip (liveModel.liveChainSource — LIVE · BREEZE only while the band's freshest tick is seconds old) or the OI chip
 * (liveModel.chainOiSource — PCR / walls mix live and NSE OI: the base frame's DELAYED · NSE / EOD chip, never LIVE),
 * re-derived on the live hooks' shared 1 s clock (lib/liveQuotes useLiveClock).
 */
import type { CSSProperties } from 'react'
import { SourceChip } from '@/components/terminal'
import { useLiveClock } from '@/lib/liveQuotes'
import { chainOiSource, isLiveWsChain, liveChainSource, type LiveChainLike } from '@/components/liveModel'

export function LiveChainChip({ chain, marketOpen, kind = 'chain', style }: {
  chain: LiveChainLike; marketOpen: boolean; kind?: 'chain' | 'oi'; style?: CSSProperties
}) {
  const now = useLiveClock(isLiveWsChain(chain))
  const info = kind === 'oi' ? chainOiSource(chain, { now, marketOpen }) : liveChainSource(chain, { now, marketOpen })
  return <SourceChip info={info} style={style} />
}
