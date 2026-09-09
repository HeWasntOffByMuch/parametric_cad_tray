import type { Json, UiHints } from '../api/types'

/**
 * JSON Schema → a flat field tree the form can render.
 *
 * There is exactly one parameter schema and it lives in the backend, so this
 * walks whatever Pydantic produced rather than restating any of it. Everything
 * the form needs - bounds, enums, defaults, discriminated variants - comes from
 * the served document.
 */

export type FieldKind = 'number' | 'integer' | 'boolean' | 'enum' | 'text' | 'object' | 'variant'

export interface Field {
  /** dotted path into the parameter document, e.g. `tray.profile.length` */
  path: string
  name: string
  title: string
  kind: FieldKind
  description?: string
  required: boolean
  nullable: boolean
  default?: any
  /** number */
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  /** enum */
  options?: string[]
  /** object / variant */
  children?: Field[]
  /** variant */
  discriminator?: string
  variants?: { key: string; title: string; fields: Field[] }[]
}

function deref(schema: Json, root: Json): Json {
  let node = schema
  let guard = 0
  while (node?.$ref && guard++ < 20) {
    const path = String(node.$ref).replace(/^#\//, '').split('/')
    node = path.reduce((acc: any, key) => acc?.[key], root)
  }
  return node ?? {}
}

/** `number | null` arrives as `anyOf: [{...}, {type: null}]`. */
function unwrapNullable(schema: Json, root: Json): { schema: Json; nullable: boolean } {
  const options: Json[] = schema.anyOf ?? []
  if (options.length === 2 && options.some((o) => o.type === 'null')) {
    const real = options.find((o) => o.type !== 'null') ?? {}
    return { schema: { ...deref(real, root), default: schema.default, title: schema.title }, nullable: true }
  }
  return { schema, nullable: false }
}

function kindOf(schema: Json): FieldKind {
  if (schema.enum) return 'enum'
  if (schema.const !== undefined) return 'text'
  if (schema.type === 'boolean') return 'boolean'
  if (schema.type === 'integer') return 'integer'
  if (schema.type === 'number') return 'number'
  if (schema.type === 'object' || schema.properties) return 'object'
  return 'text'
}

function humanize(name: string): string {
  return name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

/**
 * Pydantic titles a nested model with its class name ("PryNotches"), which is a
 * developer's word, not a user's. For a container we prefer the humanised field
 * name; for a leaf the schema title is the better description.
 */
function titleFor(name: string, schema: Json, container = false): string {
  if (container || !schema.title) return humanize(name)
  return String(schema.title)
}

export function buildField(name: string, raw: Json, root: Json, path: string, required: boolean): Field | null {
  const { schema: unwrapped, nullable } = unwrapNullable(raw, root)
  const schema = deref(unwrapped, root)

  // discriminated union → a variant selector plus the chosen variant's fields
  const oneOf: Json[] = schema.oneOf ?? raw.oneOf ?? []
  const discriminator = schema.discriminator ?? raw.discriminator
  if (oneOf.length && discriminator) {
    const variants = oneOf.map((option) => {
      const variant = deref(option, root)
      const key = String(variant.properties?.[discriminator.propertyName]?.const ?? variant.title)
      return {
        key,
        title: titleFor(key, variant),
        fields: objectFields(variant, root, path).filter((f) => f.name !== discriminator.propertyName),
      }
    })
    return {
      path,
      name,
      title: titleFor(name, raw, true),
      kind: 'variant',
      description: schema.description ?? raw.description,
      required,
      nullable,
      default: raw.default,
      discriminator: discriminator.propertyName,
      variants,
    }
  }

  const kind = kindOf(schema)
  if (kind === 'text' && schema.const !== undefined) return null // discriminator tag, not editable

  const field: Field = {
    path,
    name,
    title: titleFor(name, raw.title ? raw : schema, kind === 'object'),
    kind,
    description: schema.description ?? raw.description,
    required,
    nullable,
    default: raw.default ?? schema.default,
    minimum: schema.minimum,
    maximum: schema.maximum,
    exclusiveMinimum: schema.exclusiveMinimum,
    exclusiveMaximum: schema.exclusiveMaximum,
    options: schema.enum?.map(String),
  }
  if (kind === 'object') field.children = objectFields(schema, root, path)
  return field
}

export function objectFields(schema: Json, root: Json, prefix = ''): Field[] {
  const properties = schema.properties ?? {}
  const required: string[] = schema.required ?? []
  const out: Field[] = []
  for (const [name, raw] of Object.entries<Json>(properties)) {
    const path = prefix ? `${prefix}.${name}` : name
    const field = buildField(name, raw, root, path, required.includes(name))
    if (field) out.push(field)
  }
  return out
}

export function rootFields(jsonSchema: Json): Field[] {
  return objectFields(jsonSchema, jsonSchema)
}

// --------------------------------------------------------------------------
// grouping
// --------------------------------------------------------------------------
export interface Group {
  id: string
  title: string
  description?: string
  collapsed?: boolean
  fields: Field[]
  /** descendants of this group's fields that another group renders instead */
  exclude: Set<string>
}

function flatten(fields: Field[], out: Map<string, Field> = new Map()): Map<string, Field> {
  for (const field of fields) {
    out.set(field.path, field)
    if (field.children) flatten(field.children, out)
    if (field.variants) field.variants.forEach((v) => flatten(v.fields, out))
  }
  return out
}

function descendants(field: Field, out: Set<string> = new Set()): Set<string> {
  field.children?.forEach((c) => {
    out.add(c.path)
    descendants(c, out)
  })
  field.variants?.forEach((v) =>
    v.fields.forEach((c) => {
      out.add(c.path)
      descendants(c, out)
    }),
  )
  return out
}

/**
 * Assign fields to the groups the backend declares.
 *
 * A group may claim a field whose parent another group also claims - "Shape"
 * takes `tray.profile` for its type selector while "Dimensions" takes
 * `tray.profile.length`. So an explicit listing always wins, and the group that
 * holds the parent is told to skip the child rather than render it twice.
 *
 * Anything the hints do not mention is swept into Advanced, so a parameter added
 * to the core surfaces in the UI without a frontend change.
 */
export function groupFields(fields: Field[], hints: UiHints): Group[] {
  const index = flatten(fields)
  const listed = new Set<string>()
  for (const group of hints.groups) group.fields.forEach((p) => index.has(p) && listed.add(p))

  const placed = new Set<string>()
  const groups: Group[] = []
  for (const group of hints.groups) {
    const collected: Field[] = []
    for (const path of group.fields) {
      const field = index.get(path)
      if (!field || placed.has(path)) continue
      placed.add(path)
      collected.push(field)
    }
    if (!collected.length) continue
    const exclude = new Set<string>()
    for (const field of collected) {
      for (const child of descendants(field)) {
        if (listed.has(child) && !collected.some((f) => f.path === child)) exclude.add(child)
      }
    }
    groups.push({
      id: group.id, title: group.title, description: group.description,
      collapsed: group.collapsed, fields: collected, exclude,
    })
  }

  const hidden = new Set(hints.hidden ?? [])
  const leftovers = unplacedLeaves(fields, placed, hidden)
  if (leftovers.length) {
    const advanced = groups.find((g) => g.id === 'advanced')
    if (advanced) advanced.fields.push(...leftovers)
    else groups.push({ id: 'advanced', title: 'Advanced', collapsed: true, fields: leftovers, exclude: new Set() })
  }
  return groups
}

/**
 * Fields no group asked for, collected at the leaf.
 *
 * Sweeping whole parents would re-render everything a group already placed - the
 * `tray` object contains `tray.depth`, which Dimensions owns. Descending to the
 * leaves instead means a parameter newly added to the core surfaces on its own,
 * exactly once, wherever in the tree it lives.
 */
function unplacedLeaves(fields: Field[], placed: Set<string>, hidden: Set<string>): Field[] {
  const out: Field[] = []
  const walk = (list: Field[]) => {
    for (const field of list) {
      if (placed.has(field.path) || hidden.has(field.path)) continue
      if (field.kind === 'object' && field.children?.length) walk(field.children)
      else out.push(field)
    }
  }
  walk(fields)
  return out
}

// --------------------------------------------------------------------------
// values
// --------------------------------------------------------------------------
export function getValue(doc: Json, path: string): any {
  return path.split('.').reduce<any>((acc, key) => (acc == null ? acc : acc[key]), doc)
}

/** Immutable set: returns a new document with `path` replaced. */
export function setValue(doc: Json, path: string, value: any): Json {
  const [head, ...rest] = path.split('.')
  if (!rest.length) return { ...doc, [head]: value }
  return { ...doc, [head]: setValue(doc[head] ?? {}, rest.join('.'), value) }
}

/** Build a default value document for one variant of a discriminated union. */
export function variantDefaults(field: Field, key: string, previous: Json | undefined): Json {
  const variant = field.variants?.find((v) => v.key === key)
  if (!variant) return {}
  const next: Json = { [field.discriminator ?? 'kind']: key }
  for (const child of variant.fields) {
    const carried = previous?.[child.name]
    next[child.name] = carried !== undefined ? carried : child.default
  }
  return next
}
