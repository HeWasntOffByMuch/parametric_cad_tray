/**
 * Where the backend lives.
 *
 * The frontend is statically hosted and the API is not, so the base URL cannot
 * be baked in at build time alone. Resolution order, most specific first:
 *
 *   1. `?api=https://…`            one-off override, also remembered
 *   2. localStorage                 sticky override from (1)
 *   3. `window.__TRAYMOLD_API_BASE__`  editable in the deployed index.html
 *   4. `VITE_API_BASE_URL`          build-time default
 *   5. same origin                  the dev server proxies /api
 */
const STORAGE_KEY = 'traymold.apiBase'

declare global {
  interface Window {
    __TRAYMOLD_API_BASE__?: string
  }
}

function fromQuery(): string | null {
  if (typeof window === 'undefined') return null
  const value = new URLSearchParams(window.location.search).get('api')
  if (!value) return null
  try {
    window.localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* private mode */
  }
  return value
}

function fromStorage(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function apiBase(): string {
  const resolved =
    fromQuery() ??
    fromStorage() ??
    (typeof window !== 'undefined' ? window.__TRAYMOLD_API_BASE__ : '') ??
    import.meta.env?.VITE_API_BASE_URL ??
    ''
  return resolved.replace(/\/$/, '')
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`
}
