import { beforeEach, describe, expect, it } from 'vitest'
import { REF_PARAMS } from './harness'
import { decodeDesign, encodeDesign, loadLocal, readHash, restoreDesign, saveLocal } from '../src/state/urlState'

describe('shareable design state', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.history.replaceState(null, '', '/')
  })

  it('round-trips a design through the encoding', async () => {
    const token = await encodeDesign(REF_PARAMS)
    expect(token).toMatch(/^(d1|j1)\./)
    expect(await decodeDesign(token)).toEqual(REF_PARAMS)
  })

  it('is deterministic', async () => {
    expect(await encodeDesign(REF_PARAMS)).toBe(await encodeDesign(REF_PARAMS))
  })

  it('carries parameters, not a cache key', async () => {
    const token = await encodeDesign(REF_PARAMS)
    const decoded = await decodeDesign(token)
    expect(decoded).toHaveProperty('tray.profile.length', 175)
    expect(JSON.stringify(decoded)).not.toContain('cache_key')
  })

  it('reads a versioned token written by another browser', async () => {
    const plain = `j1.${btoa(JSON.stringify({ a: 1 })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`
    expect(await decodeDesign(plain)).toEqual({ a: 1 })
  })

  it('rejects a corrupt token instead of throwing', async () => {
    expect(await decodeDesign('d1.@@@not-base64@@@')).toBeNull()
    expect(await decodeDesign('nonsense')).toBeNull()
  })

  it('reads the hash fragment', async () => {
    const token = await encodeDesign(REF_PARAMS)
    window.history.replaceState(null, '', `/#${token}`)
    expect(readHash()).toBe(token)
  })

  it('prefers the URL over localStorage', async () => {
    saveLocal({ from: 'local' })
    const token = await encodeDesign({ from: 'url' })
    window.history.replaceState(null, '', `/#${token}`)
    const restored = await restoreDesign({ from: 'default' })
    expect(restored.source).toBe('url')
    expect(restored.params).toEqual({ from: 'url' })
  })

  it('falls back to localStorage, then to the given default', async () => {
    saveLocal({ from: 'local' })
    expect((await restoreDesign({ from: 'default' })).source).toBe('local')
    window.localStorage.clear()
    expect((await restoreDesign({ from: 'default' })).source).toBe('default')
  })

  it('survives localStorage being unavailable', () => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('quota')
    }
    expect(() => saveLocal({ a: 1 })).not.toThrow()
    Storage.prototype.setItem = original
  })

  it('ignores unreadable stored state', () => {
    window.localStorage.setItem('traymold.design.v1', '{not json')
    expect(loadLocal()).toBeNull()
  })
})
