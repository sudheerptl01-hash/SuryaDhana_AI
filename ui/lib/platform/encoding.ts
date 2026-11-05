/**
 * Byte/Base64 helpers for `shell_save_download` (pure; runs under node for the check script).
 */

/** Shell-side cap on a decoded download (PLAN §5: ≤ 50 MB decoded). */
export const MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

const CHUNK = 0x8000

/** Standard (RFC 4648, padded) base64 of a byte array, chunked so large files never blow the call stack. */
export function bytesToBase64(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += CHUNK) {
    const slice = bytes.subarray(i, Math.min(i + CHUNK, bytes.length))
    bin += String.fromCharCode.apply(null, slice as unknown as number[])
  }
  return btoa(bin)
}

/** Base64 of a Blob's bytes (UTF-8 for text blobs, since the Blob already holds the encoded bytes). */
export async function blobToBase64(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer()
  return bytesToBase64(new Uint8Array(buf))
}

/** Default MIME for string payloads (today's CSV exports use text/csv;charset=utf-8). */
export function toBlob(data: Blob | string, mime?: string): Blob {
  if (typeof data !== 'string') return data
  return new Blob([data], { type: mime || 'text/plain;charset=utf-8' })
}

/**
 * Client-side mirror of the shell's filename rule (basename only, `[A-Za-z0-9._ -]`, ≤ 120 chars).
 * The shell re-sanitizes; doing it here too means the returned path matches what the user expects.
 */
export function sanitizeFilename(name: string, fallback = 'download'): string {
  const base = String(name || '').split(/[\\/]/).pop() || ''
  let s = base.replace(/[^A-Za-z0-9._ -]+/g, '_').replace(/^[.\s]+/, '').replace(/\s+$/, '')
  if (s.length > 120) {
    const dot = s.lastIndexOf('.')
    const ext = dot > 0 && s.length - dot <= 10 ? s.slice(dot) : ''
    s = s.slice(0, 120 - ext.length) + ext
  }
  return s || fallback
}
