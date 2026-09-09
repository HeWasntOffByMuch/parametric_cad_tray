import { describe, expect, it } from 'vitest'
import { explodeOffset, partVisibility } from '../src/viewer/Viewer'

describe('viewer part rules', () => {
  it('shows both halves by default', () => {
    expect(partVisibility('both', true, true)).toEqual({ male: true, female: true })
  })

  it('isolates one half in single-part mode', () => {
    expect(partVisibility('male', true, true)).toEqual({ male: true, female: false })
    expect(partVisibility('female', true, true)).toEqual({ male: false, female: true })
  })

  it('lets an individual toggle hide a half inside both mode', () => {
    expect(partVisibility('both', true, false)).toEqual({ male: true, female: false })
    expect(partVisibility('both', false, false)).toEqual({ male: false, female: false })
  })

  it('separates the halves only in exploded view', () => {
    expect(explodeOffset('assembled')).toBe(0)
    expect(explodeOffset('exploded')).toBeGreaterThan(0)
  })
})
