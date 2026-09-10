/**
 * Combinations the backend cannot build, kept out of reach rather than reported.
 *
 * The rule they replace: pick Ellipse with a root blend on, wait, and get told
 * that an elliptical plug cannot take a root blend and that you should go and
 * set `mold.male_root_blend` to none. Every part of that is the app asking the
 * user to do its own bookkeeping - it knew the answer before the click landed.
 *
 * So a constraint is applied, not announced. `resolve` runs on every document
 * that enters the app - an edit, a preset, a restored link - and puts the
 * constrained field on its fallback in the same change that made the rule
 * bite. `disallowed` then greys out the options that would break it again, with
 * the reason where the description usually goes. The build is never blocked and
 * there is nothing to fix, because the invalid state is not reachable.
 *
 * The server keeps its own copy of these rules and still refuses the
 * combination (see `trayapi.policy`): the form is not the only thing that can
 * post a parameter document. Nobody driving the app should ever see that error.
 */

import type { Json, UiHints } from '../api/types'
import { getValue, setValue, variantDefaults, type Field } from './schema'

export interface Conflict {
  code: string
  when: { field: string; kind_in: string[] }
  field: string
  allowed: string[]
  fallback: string
  reason: string
}

export interface Applied {
  code: string
  field: string
  reason: string
  /** what the field was on before the rule took it off */
  from: string
}

export function conflictsIn(hints: UiHints | undefined): Conflict[] {
  return hints?.conflicts ?? []
}

/** The discriminator at a path, whether it holds a variant object or an enum. */
function kindAt(params: Json, path: string): string | undefined {
  const value = getValue(params, path)
  if (typeof value === 'string') return value
  return typeof value?.kind === 'string' ? value.kind : undefined
}

export function inForce(params: Json, conflicts: Conflict[]): Conflict[] {
  return conflicts.filter((c) => c.when.kind_in.includes(kindAt(params, c.when.field) ?? '\0'))
}

/**
 * Variant keys that must not be selectable for `field`, given the rest of the
 * document, in the shape `Listbox` already takes for statically gated values.
 */
export function disallowed(
  params: Json,
  conflicts: Conflict[],
  field: string,
  keys: string[],
): Record<string, { code: string; reason: string }> {
  const out: Record<string, { code: string; reason: string }> = {}
  for (const conflict of inForce(params, conflicts)) {
    if (conflict.field !== field) continue
    for (const key of keys) {
      if (!conflict.allowed.includes(key)) out[key] = { code: conflict.code, reason: conflict.reason }
    }
  }
  return out
}

/**
 * The document with every constraint satisfied.
 *
 * Returns the input unchanged - the same object, so React sees no new state -
 * when nothing had to move, which is the overwhelmingly common case.
 */
export function resolve(
  params: Json,
  conflicts: Conflict[],
  fieldAt: (path: string) => Field | undefined,
): { params: Json; applied: Applied[] } {
  let next = params
  const applied: Applied[] = []
  for (const conflict of inForce(params, conflicts)) {
    const current = kindAt(next, conflict.field)
    if (current === undefined || conflict.allowed.includes(current)) continue
    const field = fieldAt(conflict.field)
    if (!field) continue
    // Carrying the outgoing variant's shared fields, exactly as the picker does
    // when someone switches by hand - `none` has none, but a future fallback
    // that does should not silently drop a setback the user chose.
    const fallback = variantDefaults(field, conflict.fallback, getValue(next, conflict.field))
    next = setValue(next, conflict.field, fallback)
    applied.push({ code: conflict.code, field: conflict.field, reason: conflict.reason, from: current })
  }
  return { params: next, applied }
}
