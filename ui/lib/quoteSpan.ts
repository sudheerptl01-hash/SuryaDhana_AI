/**
 * "since Fri" when a quote's day change spans more than one weekday: an exchange holiday, or a session the data
 * source skipped (Yahoo had no 12 Oct 2026 bar for USD/INR, so its "day" change was Friday to Tuesday).
 */
export function spanNote(v?: { prev_date?: string | null; market_date?: string | null } | null): string | null {
  if (!v?.prev_date || !v.market_date) return null
  const a = new Date(`${v.prev_date}T00:00:00Z`), b = new Date(`${v.market_date}T00:00:00Z`)
  let weekdays = 0
  for (const d = new Date(a); d < b; d.setUTCDate(d.getUTCDate() + 1)) if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) weekdays++
  return weekdays > 1 ? `since ${a.toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'UTC' })}` : null
}
