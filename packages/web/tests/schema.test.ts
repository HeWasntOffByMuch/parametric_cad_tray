import { describe, expect, it } from 'vitest'
import { SCHEMA, REF_PARAMS } from './harness'
import { getValue, groupFields, rootFields, setValue, variantDefaults } from '../src/form/schema'

const fields = rootFields(SCHEMA.json_schema)

describe('schema resolution', () => {
  it('walks the served schema rather than restating it', () => {
    expect(fields.map((f) => f.name)).toEqual(Object.keys(SCHEMA.json_schema.properties))
  })

  it('resolves $refs into nested object fields', () => {
    const tray = fields.find((f) => f.name === 'tray')!
    expect(tray.kind).toBe('object')
    expect(tray.children!.map((c) => c.name)).toContain('depth')
    const depth = tray.children!.find((c) => c.name === 'depth')!
    expect(depth.kind).toBe('number')
    expect(depth.path).toBe('tray.depth')
    expect(depth.maximum).toBe(300)
  })

  it('reads numeric bounds from the schema', () => {
    const thickness = groupFields(fields, SCHEMA.ui_hints)
      .flatMap((g) => g.fields)
      .find((f) => f.path === 'leather.thickness')!
    expect(thickness.exclusiveMinimum ?? thickness.minimum).toBe(0)
    expect(thickness.maximum).toBe(12)
  })

  it('turns a discriminated union into a variant field', () => {
    const tray = fields.find((f) => f.name === 'tray')!
    const profile = tray.children!.find((c) => c.name === 'profile')!
    expect(profile.kind).toBe('variant')
    expect(profile.discriminator).toBe('kind')
    const keys = profile.variants!.map((v) => v.key)
    expect(keys).toContain('g2_quintic_obround')
    expect(keys).toContain('circular_obround')
    const obround = profile.variants!.find((v) => v.key === 'g2_quintic_obround')!
    expect(obround.fields.map((f) => f.name)).toEqual(['length', 'width'])
    // the discriminator tag itself is not an editable field
    expect(obround.fields.some((f) => f.name === 'kind')).toBe(false)
  })

  it('unwraps optional numbers', () => {
    const fit = fields.find((f) => f.name === 'fit')!
    const override = fit.children!.find((c) => c.name === 'gap_override')!
    expect(override.kind).toBe('number')
    expect(override.nullable).toBe(true)
  })

  it('recognises enums', () => {
    const tray = fields.find((f) => f.name === 'tray')!
    const datum = tray.children!.find((c) => c.name === 'datum')!
    expect(datum.kind).toBe('enum')
    expect(datum.options).toEqual(['inner', 'outer'])
  })
})

describe('grouping', () => {
  const groups = groupFields(fields, SCHEMA.ui_hints)

  it('uses the order the backend declares', () => {
    expect(groups.map((g) => g.id)).toEqual([
      'shape', 'dimensions', 'leather', 'mold', 'features', 'manufacturing', 'advanced',
    ])
  })

  it('puts dimensions where a user expects them', () => {
    const dimensions = groups.find((g) => g.id === 'dimensions')!
    expect(dimensions.fields.map((f) => f.path)).toEqual([
      'tray.profile.length', 'tray.profile.width', 'tray.depth',
    ])
  })

  it('sweeps a parameter the hints do not mention into Advanced', () => {
    // Simulates adding a parameter to the core without touching the frontend.
    const extended = structuredClone(SCHEMA.json_schema)
    extended.$defs.LeatherParams.properties.temper = {
      type: 'number', title: 'Temper', default: 1, minimum: 0, maximum: 3,
    }
    const advanced = groupFields(rootFields(extended), SCHEMA.ui_hints).find((g) => g.id === 'advanced')!
    expect(advanced.fields.map((f) => f.path)).toContain('leather.temper')
  })

  it('does not re-render a field a group already placed', () => {
    const everything = groups.flatMap((g) => g.fields.map((f) => f.path))
    expect(everything.filter((p) => p === 'tray.depth')).toHaveLength(1)
    const shape = groups.find((g) => g.id === 'shape')!
    expect(shape.exclude.has('tray.profile.length')).toBe(true)
  })

  it('hides bookkeeping fields', () => {
    const everything = groups.flatMap((g) => g.fields.map((f) => f.path))
    expect(everything).not.toContain('schema_version')
    expect(everything).not.toContain('name')
  })
})

describe('value helpers', () => {
  it('reads and writes nested paths immutably', () => {
    const next = setValue(REF_PARAMS, 'tray.profile.length', 200)
    expect(getValue(next, 'tray.profile.length')).toBe(200)
    expect(getValue(REF_PARAMS, 'tray.profile.length')).toBe(175)
    expect(next.leather).toBe(REF_PARAMS.leather)
  })

  it('carries shared fields across a variant switch', () => {
    const tray = fields.find((f) => f.name === 'tray')!
    const profile = tray.children!.find((c) => c.name === 'profile')!
    const before = { kind: 'g2_quintic_obround', length: 175, width: 105 }
    const after = variantDefaults(profile, 'circular_rect', before)
    expect(after.kind).toBe('circular_rect')
    expect(after.length).toBe(175)
    expect(after.width).toBe(105)
    expect(after).toHaveProperty('corner_radius')
  })
})
