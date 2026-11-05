'use client'

/**
 * One latest-request-wins guard (components/requestSeq.ts) per mounted page, kept in a ref (P1 / CT-01).
 *
 * It used to live in `useMemo(createRequestSeq, [])`. React documents useMemo as a cache it may discard, and a new
 * guard would forget the requests already in flight (an old answer would then pass `isCurrent`). A ref is the
 * same object for the whole life of the component. Every token is cancelled on unmount.
 */
import { useEffect, useRef } from 'react'
import { createRequestSeq, type RequestSeq } from '@/components/requestSeq'

export function useRequestSeq(): RequestSeq {
  const ref = useRef<RequestSeq | null>(null)
  if (ref.current === null) ref.current = createRequestSeq()
  const seq = ref.current
  useEffect(() => () => seq.cancel(), [seq])
  return seq
}
