import { beforeEach, describe, expect, it, vi } from 'vitest'
import { attribution, ids, withSession } from '../src/analytics'

describe('anonymous identity', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.resetModules()
  })

  it('is random, never derived from anything about the machine', async () => {
    const seen = new Set<string>()
    for (let i = 0; i < 200; i++) seen.add(crypto.randomUUID())
    expect(seen.size).toBe(200)

    const { visitor_id, session_id } = ids()
    // Nothing that identifies the browser may appear in an id.
    for (const value of [visitor_id, session_id]) {
      expect(value).not.toContain(navigator.userAgent.slice(0, 8))
      expect(value).not.toMatch(/\d{2,4}x\d{2,4}/) // no screen dimensions
      expect(value.length).toBeGreaterThan(8)
    }
    expect(visitor_id).not.toBe(session_id)
  })

  it('persists the visitor across sessions and the session within one', async () => {
    // A fresh import, because the ids are cached in module state on purpose:
    // they must not change underneath a page that is already open.
    vi.resetModules()
    const fresh = await import('../src/analytics')
    const first = fresh.ids()
    expect(localStorage.getItem('traymold.visitor')).toBe(first.visitor_id)
    expect(sessionStorage.getItem('traymold.session')).toBe(first.session_id)
    expect(fresh.ids()).toEqual(first)

    // A new page in the same tab keeps both; a new tab keeps only the visitor.
    vi.resetModules()
    const reopened = await import('../src/analytics')
    expect(reopened.ids()).toEqual(first)
    sessionStorage.clear()
    vi.resetModules()
    const newTab = await import('../src/analytics')
    const second = newTab.ids()
    expect(second.visitor_id).toBe(first.visitor_id)
    expect(second.session_id).not.toBe(first.session_id)
  })

  it('still produces ids when storage throws', async () => {
    const boom = () => {
      throw new Error('storage disabled')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    vi.resetModules()
    const fresh = await import('../src/analytics')
    expect(fresh.ids().visitor_id.length).toBeGreaterThan(8)
    vi.restoreAllMocks()
  })
})

describe('download links', () => {
  it('carries the session so the server can attribute the file', () => {
    const url = withSession('/api/artifacts/key/male.stl')
    expect(url).toContain('s=')
    expect(url).toContain('v=')
    const second = withSession('/api/artifacts/key/male.stl?x=1')
    expect(second).toContain('?x=1&s=')
  })
})

describe('attribution', () => {
  beforeEach(() => sessionStorage.clear())

  it('sends only the referrer origin, never its path or query', () => {
    vi.spyOn(document, 'referrer', 'get').mockReturnValue(
      'https://www.google.com/search?q=private+terms&hl=en#frag',
    )
    const found = attribution()
    expect(found.referrer).toBe('https://www.google.com')
    const serialized = JSON.stringify(found)
    for (const leak of ['private', 'q=', 'hl=en', 'frag', '/search']) {
      expect(serialized).not.toContain(leak)
    }
    vi.restoreAllMocks()
  })

  it('picks up utm parameters from the landing URL', () => {
    const url = new URL(window.location.href)
    url.search = '?utm_source=makerworld&utm_medium=model&utm_campaign=leather_tray'
    window.history.replaceState({}, '', url)
    sessionStorage.clear()
    const found = attribution()
    expect(found.source).toBe('makerworld')
    expect(found.medium).toBe('model')
    expect(found.campaign).toBe('leather_tray')
  })
})

describe('engagement', () => {
  it('fires once, not once per parameter change', async () => {
    vi.resetModules()
    const fresh = await import('../src/analytics')
    expect(fresh.markEngagedOnce()).toBe(true)
    expect(fresh.markEngagedOnce()).toBe(false)
    expect(fresh.markEngagedOnce()).toBe(false)
  })
})
