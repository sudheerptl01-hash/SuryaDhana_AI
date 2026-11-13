/**
 * apiError/normalizeError case harness (design_review minor 13).
 * No test framework configured in ui/, so: type-checked by `tsc --noEmit` on every build,
 * executed by `npx tsx ui/lib/__tests__/errors.check.ts` when tsx is available.
 * Exits non-zero on the first failing case.
 */
import { apiError, normalizeError, UPSTREAM_WAIT_TEXT } from '../errors'

const ax = (data: unknown, message = 'Request failed with status code 503') =>
  ({ message, response: { data } })

const CASES: Array<{ name: string; input: unknown; msg: string; code?: string | null }> = [
  // 1. legacy FastAPI: detail string
  { name: 'detail string', input: ax({ detail: 'no rows for RELIANCE' }), msg: 'no rows for RELIANCE' },
  // 2. new contract: detail string + sibling error{} → error wins; the data-service prefix is calmed (O-F5a)
  {
    name: 'sibling error preferred + calmed',
    input: ax({ detail: 'upstream', error: { code: 'upstream_down', message: 'data-service unreachable', hint: 'start-local.sh' } }),
    msg: UPSTREAM_WAIT_TEXT, code: 'upstream_down',
  },
  // 2b. legacy router detail leaking httpx internals → calm copy on the panel, never the transport text
  {
    name: 'raw transport detail calmed',
    input: ax({ detail: 'data-service unreachable: All connection attempts failed' }),
    msg: UPSTREAM_WAIT_TEXT, code: 'upstream_down',
  },
  // 2c. exception-class flavour (old charts.py shape) calmed too
  {
    name: 'exception-class detail calmed',
    input: ax({ detail: 'data-service unreachable: ConnectError' }),
    msg: UPSTREAM_WAIT_TEXT, code: 'upstream_down',
  },
  // 2d. other upstreams keep their own honest message (gold/mcx use upstream_down for Yahoo)
  {
    name: 'non-data-service upstream_down untouched',
    input: ax({ error: { code: 'upstream_down', message: 'COMEX/USDINR unavailable from Yahoo right now' } }),
    msg: 'COMEX/USDINR unavailable from Yahoo right now', code: 'upstream_down',
  },
  // 2e. a data-service message that is not "unreachable" stays honest
  {
    name: 'data-service non-transport message untouched',
    input: ax({ detail: 'data-service returned no OHLCV rows' }),
    msg: 'data-service returned no OHLCV rows',
  },
  // 3. soft-200 degraded payload passed directly (not thrown)
  { name: 'raw degraded payload', input: { error: { code: 'degraded', message: 'yahoo fallback' } }, msg: 'yahoo fallback', code: 'degraded' },
  // 4. legacy soft-200 string error
  { name: 'legacy error string', input: ax({ error: 'breeze session expired' }), msg: 'breeze session expired', code: 'degraded' },
  // 5. FastAPI validation array
  {
    name: 'validation array',
    input: ax({ detail: [{ msg: 'field required', loc: ['query', 'symbol'] }, { msg: 'value is not a valid integer' }] }),
    msg: 'field required; value is not a valid integer', code: 'invalid',
  },
  // 6. broker family: connected:false
  { name: 'connected false', input: ax({ connected: false }), msg: 'not connected', code: 'state' },
  // 7. network error: no response at all
  { name: 'network error', input: { message: 'Network Error' }, msg: 'Network Error' },
  // 8. plain Error instance
  { name: 'Error instance', input: new Error('boom'), msg: 'boom' },
  // 9. junk → fallback
  { name: 'null falls back', input: null, msg: 'unavailable' },
  // 10. unknown code string → message kept, code dropped to null
  { name: 'unknown code tolerated', input: ax({ error: { code: 'weird', message: 'kept' } }), msg: 'kept', code: null },
  // 11. empty detail string falls through to axios message
  { name: 'empty detail falls through', input: ax({ detail: '' }), msg: 'Request failed with status code 503' },
  // 12. string thrown directly
  { name: 'string input', input: 'plain failure', msg: 'plain failure' },
]

let failed = 0
for (const c of CASES) {
  const info = normalizeError(c.input)
  const okMsg = apiError(c.input) === c.msg && info.message === c.msg
  const okCode = c.code === undefined || info.code === c.code
  if (!okMsg || !okCode) {
    failed++
    console.error(`FAIL ${c.name}: got message=${JSON.stringify(info.message)} code=${JSON.stringify(info.code)}, want message=${JSON.stringify(c.msg)}${c.code !== undefined ? ` code=${JSON.stringify(c.code)}` : ''}`)
  }
}
// custom fallback + hint surfacing
if (apiError(undefined, 'chart unavailable') !== 'chart unavailable') { failed++; console.error('FAIL custom fallback') }
if (normalizeError(ax({ error: { code: 'degraded', message: 'm', hint: 'retry at 09:15' } })).hint !== 'retry at 09:15') { failed++; console.error('FAIL hint surfacing') }
// O-F5a: the calmed info keeps the raw text for logging only, and the message never carries transport internals
const calm = normalizeError(ax({ detail: 'data-service unreachable: All connection attempts failed' }))
if (calm.raw !== 'data-service unreachable: All connection attempts failed') { failed++; console.error('FAIL raw preserved') }
if (/All connection attempts failed|ConnectError/i.test(calm.message)) { failed++; console.error('FAIL transport text leaked into message') }

if (failed) { console.error(`${failed} case(s) failed`); process.exit(1) }
console.log(`errors.check: all ${CASES.length + 4} cases pass`)
