import type { Json } from '../api/types'

/**
 * Shareable design state.
 *
 * The URL carries *parameters*, never a cache key: a link must still work after
 * the artifact cache is swept, and must be readable by a different backend.
 *
 * Encoding is versioned and deterministic:
 *   `#d1.<base64url>`  deflate-raw compressed JSON (browsers with CompressionStream)
 *   `#j1.<base64url>`  plain JSON, the fallback
 * A reader accepts both regardless of what it can write, so a link made in one
 * browser opens in another.
 */
const HASH_PREFIX = '#'
export const ENCODINGS = ['d1', 'j1'] as const

function toBase64Url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((b) => (binary += String.fromCharCode(b)))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64Url(text: string): Uint8Array {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/')
  const binary = atob(padded + '='.repeat((4 - (padded.length % 4)) % 4))
  return Uint8Array.from(binary, (c) => c.charCodeAt(0))
}

function blobOf(bytes: Uint8Array): Blob {
  return new Blob([bytes.slice().buffer as ArrayBuffer])
}

async function through(bytes: Uint8Array, transform: string, kind: 'CompressionStream' | 'DecompressionStream'): Promise<Uint8Array> {
  const stream = new (globalThis as any)[kind](transform)
  const piped = new Response(blobOf(bytes).stream().pipeThrough(stream))
  return new Uint8Array(await piped.arrayBuffer())
}

const deflate = (bytes: Uint8Array) => through(bytes, 'deflate-raw', 'CompressionStream')
const inflate = (bytes: Uint8Array) => through(bytes, 'deflate-raw', 'DecompressionStream')

const canCompress = () => typeof (globalThis as any).CompressionStream === 'function'

export async function encodeDesign(params: Json): Promise<string> {
  const json = JSON.stringify(params)
  const bytes = new TextEncoder().encode(json)
  if (canCompress()) {
    try {
      return `d1.${toBase64Url(await deflate(bytes))}`
    } catch {
      /* fall through to plain */
    }
  }
  return `j1.${toBase64Url(bytes)}`
}

export async function decodeDesign(token: string): Promise<Json | null> {
  const separator = token.indexOf('.')
  if (separator < 0) return null
  const version = token.slice(0, separator)
  const payload = token.slice(separator + 1)
  try {
    const bytes = fromBase64Url(payload)
    if (version === 'j1') return JSON.parse(new TextDecoder().decode(bytes))
    if (version === 'd1') return JSON.parse(new TextDecoder().decode(await inflate(bytes)))
  } catch {
    return null
  }
  return null
}

export function readHash(hash = window.location.hash): string | null {
  const value = hash.startsWith(HASH_PREFIX) ? hash.slice(1) : hash
  return value.length > 3 && value.includes('.') ? value : null
}

export async function writeHash(params: Json): Promise<void> {
  const token = await encodeDesign(params)
  const url = `${window.location.pathname}${window.location.search}#${token}`
  window.history.replaceState(null, '', url)
}

export async function shareUrl(params: Json): Promise<string> {
  const token = await encodeDesign(params)
  return `${window.location.origin}${window.location.pathname}${window.location.search}#${token}`
}

// --------------------------------------------------------------------------
const STORAGE_KEY = 'traymold.design.v1'

export function saveLocal(params: Json): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(params))
  } catch {
    /* private mode, quota */
  }
}

export function loadLocal(): Json | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

/** URL takes precedence over localStorage, which takes precedence over a preset. */
export async function restoreDesign(fallback: Json): Promise<{ params: Json; source: 'url' | 'local' | 'default' }> {
  const token = readHash()
  if (token) {
    const decoded = await decodeDesign(token)
    if (decoded) return { params: decoded, source: 'url' }
  }
  const local = loadLocal()
  if (local) return { params: local, source: 'local' }
  return { params: fallback, source: 'default' }
}
