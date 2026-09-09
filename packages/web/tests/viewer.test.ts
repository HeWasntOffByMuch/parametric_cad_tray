import { describe, expect, it } from 'vitest'
import { cameraLimits, explodeOffset, gridSpacing, partVisibility } from '../src/viewer/Viewer'

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

describe('camera limits', () => {
  it('derives the near plane from the model, not from where the camera starts', () => {
    // The regression: near was set from the initial camera distance, so zooming
    // closer than that start distance put geometry in front of the plane and the
    // mold rendered sliced open. Two models of the same size must get the same
    // near plane whatever distance the camera happens to open at.
    const a = cameraLimits(145, 40)
    const b = cameraLimits(145, 20) // much longer start distance, same model
    expect(b.distance).toBeGreaterThan(a.distance * 1.5)
    expect(b.near).toBe(a.near)
  })

  it('keeps the closest allowed camera far outside the near plane', () => {
    for (const radius of [20, 145, 400, 2000]) {
      const l = cameraLimits(radius, 40)
      expect(l.near).toBeLessThan(l.minDistance / 100)
      expect(l.maxDistance).toBeGreaterThan(l.distance)
      expect(l.far).toBeGreaterThan(l.maxDistance)
      // depth precision: three.js's own default spread is 20000
      expect(l.far / l.near).toBeLessThanOrEqual(20000)
    }
  })

  it('scales with the model so a 60 mm tray frames like a 500 mm one', () => {
    const small = cameraLimits(30, 40)
    const large = cameraLimits(300, 40)
    expect(large.distance / small.distance).toBeCloseTo(10, 6)
    expect(large.near / small.near).toBeCloseTo(10, 6)
  })

  it('never divides by zero on an empty or degenerate model', () => {
    const l = cameraLimits(0, 40)
    expect(Number.isFinite(l.distance)).toBe(true)
    expect(l.near).toBeGreaterThan(0)
  })
})

describe('grid spacing', () => {
  it('gives any model a readable number of squares', () => {
    for (const radius of [20, 145, 400, 2000]) {
      const g = gridSpacing(radius)
      const squares = g.extent / g.cell
      expect(squares).toBeGreaterThan(8)
      expect(squares).toBeLessThan(400)
      expect(g.section).toBeGreaterThan(g.cell)
    }
  })

  it('is finite, so distant cells cannot alias into a shimmer', () => {
    expect(Number.isFinite(gridSpacing(145).extent)).toBe(true)
  })
})
