/** NSE's own payloads (corporate announcements, several NextApi feeds) date a day as DD-MM-YYYY; the terminal's chip age
 *  rule (`sourceOf` / `ageDaysOf`) reads ISO. Unconverted, CF read OFFLINE "no source is responding" over 317 filings it had
 *  (5 Nov live audit). ISO input passes through; anything else stays as given (the chip then says it cannot date it). */
export function isoDayFromNse(d: string | null | undefined): string | null {
  if (!d) return null
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec(d.trim())
  return m ? `${m[3]}-${m[2]}-${m[1]}` : d
}

/** The newest 'YYYY-MM-DD HH:MM:SS' stamp of a list (NSE filings; the stamp sorts as text), whatever the list's order. */
export function newestStamp(items: ReadonlyArray<{ time?: string | null }> | null | undefined): string | null {
  let best: string | null = null
  for (const it of items ?? []) {
    const t = it?.time
    if (t && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(t) && (best == null || t > best)) best = t
  }
  return best
}
