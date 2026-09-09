/**
 * Anonymous, best-effort usage telemetry.
 *
 * Two random UUIDs and a first-touch source. Nothing is derived from the IP,
 * the user agent, the screen, the canvas or anything else about the machine -
 * an id here is random or it does not exist. If storage is unavailable the ids
 * are transient and the visit simply counts as new.
 *
 * Everything fails silently. Analytics is not allowed to be the reason a
 * configurator does not work, so no call here throws, retries or blocks.
 *
 * This module cannot move the public counter. Only an artifact the server
 * actually served can do that; these events describe the funnel around it.
 */
import { apiUrl } from './config'

const VISITOR_KEY = 'traymold.visitor'
const SESSION_KEY = 'traymold.session'
const SOURCE_KEY = 'traymold.source'

export type ClientEvent = 'app_opened' | 'config_engaged' | 'share_link_copied' | 'makerworld_clicked'

export interface Attribution {
  source?: string
  medium?: string
  campaign?: string
  referrer?: string
  landing_path?: string
}

function uuid(): string {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
    const bytes = new Uint8Array(16)
    globalThis.crypto.getRandomValues(bytes)
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  } catch {
    // Not cryptographically random, and it does not need to be: this is a
    // bucket label, not a secret. Collisions cost one merged session.
    return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  }
}

function remembered(store: 'local' | 'session', key: string): string {
  const storage = store === 'local' ? globalThis.localStorage : globalThis.sessionStorage
  try {
    const existing = storage?.getItem(key)
    if (existing) return existing
    const created = uuid()
    storage?.setItem(key, created)
    return created
  } catch {
    // Private mode, storage disabled, or a sandboxed frame: carry on with a
    // transient id rather than losing the whole visit.
    return uuid()
  }
}

let visitorId: string | null = null
let sessionId: string | null = null

export function ids(): { visitor_id: string; session_id: string } {
  visitorId ??= remembered('local', VISITOR_KEY)
  sessionId ??= remembered('session', SESSION_KEY)
  return { visitor_id: visitorId, session_id: sessionId }
}

/**
 * First-touch attribution, captured once per session.
 *
 * An explicit `utm_source` wins over the referrer, because a campaign link says
 * what the campaign is while a referrer only says which page the browser came
 * from - possibly a redirector on the way. Only the referrer's *origin* is ever
 * sent; the path and query of the referring page are not ours to collect.
 */
export function attribution(): Attribution {
  try {
    const stored = globalThis.sessionStorage?.getItem(SOURCE_KEY)
    if (stored) return JSON.parse(stored)
  } catch {
    /* fall through and recompute */
  }

  const found: Attribution = {}
  try {
    const params = new URLSearchParams(globalThis.location?.search ?? '')
    const source = params.get('utm_source')
    const medium = params.get('utm_medium')
    const campaign = params.get('utm_campaign')
    if (source) found.source = source.slice(0, 64)
    if (medium) found.medium = medium.slice(0, 64)
    if (campaign) found.campaign = campaign.slice(0, 64)
    found.landing_path = (globalThis.location?.pathname ?? '').slice(0, 128)

    const referrer = globalThis.document?.referrer
    if (referrer) {
      const url = new URL(referrer)
      // origin only: no path, no query string.
      if (url.origin !== globalThis.location?.origin) found.referrer = url.origin
    }
  } catch {
    /* an unparseable referrer is simply not attributed */
  }

  try {
    globalThis.sessionStorage?.setItem(SOURCE_KEY, JSON.stringify(found))
  } catch {
    /* not remembering it costs a re-parse, nothing more */
  }
  return found
}

let lastEngaged = false

/** `config_engaged` is once per session, not once per slider move. */
export function markEngagedOnce(): boolean {
  if (lastEngaged) return false
  lastEngaged = true
  return true
}

export function track(event: ClientEvent): void {
  const body = JSON.stringify({ event, ...ids(), ...attribution() })
  const url = apiUrl('/api/analytics/event')
  try {
    // sendBeacon survives the page being closed, which is exactly the case for
    // a MakerWorld click. It is also fire-and-forget, so it cannot block a
    // navigation the user asked for.
    if (navigator?.sendBeacon?.(url, new Blob([body], { type: 'application/json' }))) return
  } catch {
    /* fall through to fetch */
  }
  try {
    void fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {})
  } catch {
    /* telemetry is optional; the app is not */
  }
}

/**
 * Attach the anonymous session to a download link.
 *
 * A download is a plain browser navigation, so it carries no headers of ours -
 * the ids have to ride the query string for the server to attribute the file to
 * a session. The server still decides whether anything counts.
 */
export function withSession(url: string): string {
  const { session_id, visitor_id } = ids()
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}s=${encodeURIComponent(session_id)}&v=${encodeURIComponent(visitor_id)}`
}
