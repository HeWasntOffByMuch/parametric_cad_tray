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
 *
 * An empty candidate is not a choice - it is the absence of one - so each step
 * falls through on blank as well as on missing.
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

/**
 * The first candidate that actually says something.
 *
 * `??` is the wrong operator for this chain. index.html declares
 * `window.__TRAYMOLD_API_BASE__ = ''` so that the deployed file has a line to
 * edit - and `'' ?? next` is `''`, because `??` only falls through on null and
 * undefined. That empty placeholder swallowed the rest of the chain, so the
 * build-time VITE_API_BASE_URL was never read on the hosted page and every
 * request went to the page's own origin instead: `/api/schema` on
 * user.github.io, which is a 404 from the static host. A candidate counts only
 * if it has something in it.
 */
function firstSet(...candidates: (string | null | undefined)[]): string {
  for (const candidate of candidates) {
    const value = candidate?.trim()
    if (value) return value
  }
  return ''
}

export function apiBase(): string {
  return firstSet(
    fromQuery(),
    fromStorage(),
    typeof window !== 'undefined' ? window.__TRAYMOLD_API_BASE__ : undefined,
    import.meta.env?.VITE_API_BASE_URL,
  ).replace(/\/$/, '')
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`
}
