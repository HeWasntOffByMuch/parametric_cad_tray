import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiBase, apiUrl } from '../src/config'

describe('where the backend lives', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.history.replaceState(null, '', '/')
    delete (window as any).__TRAYMOLD_API_BASE__
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('uses the URL baked in at build time', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')
    expect(apiBase()).toBe('https://api.example.com')
  })

  // The regression that broke the hosted page: index.html declares the runtime
  // override as an empty string so the deployed file has a line to edit, and an
  // empty string is not null - so a `??` chain stopped there and never reached
  // the build-time URL. Every request then went to the page's own origin, and a
  // static host answers /api/schema with a 404.
  it('reaches the build-time URL past an empty runtime placeholder', () => {
    window.__TRAYMOLD_API_BASE__ = ''
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')
    expect(apiBase()).toBe('https://api.example.com')
    expect(apiUrl('/api/schema')).toBe('https://api.example.com/api/schema')
  })

  it('lets a filled-in index.html override the build', () => {
    window.__TRAYMOLD_API_BASE__ = 'https://edited.example.com'
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')
    expect(apiBase()).toBe('https://edited.example.com')
  })

  it('lets ?api= win over everything, and remembers it', () => {
    window.history.replaceState(null, '', '/?api=https://pinned.example.com')
    window.__TRAYMOLD_API_BASE__ = 'https://edited.example.com'
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')
    expect(apiBase()).toBe('https://pinned.example.com')

    window.history.replaceState(null, '', '/')
    expect(apiBase()).toBe('https://pinned.example.com')
  })

  it('ignores a stored override that is blank', () => {
    window.localStorage.setItem('traymold.apiBase', '   ')
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com')
    expect(apiBase()).toBe('https://api.example.com')
  })

  it('drops a trailing slash so paths do not double up', () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com/')
    expect(apiUrl('/api/schema')).toBe('https://api.example.com/api/schema')
  })

  it('falls back to the same origin when nothing is configured', () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    expect(apiBase()).toBe('')
    expect(apiUrl('/api/schema')).toBe('/api/schema')
  })
})
