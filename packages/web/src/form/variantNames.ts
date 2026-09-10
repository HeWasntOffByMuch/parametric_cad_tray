/**
 * Human names for the discriminated-union variants.
 *
 * The schema's titles come from Pydantic, which names a model after its class:
 * the shape picker read "G2QuinticObroundProfile", which tells a leatherworker
 * nothing and a CAD engineer only slightly more. These are the names for the
 * thing rather than for the type that implements it.
 *
 * Two parts, because the choice really is two questions. `group` is the
 * silhouette - what the tray looks like from above - and `name` is how the
 * corner is made. The list is grouped by the first and picked by the second;
 * `full` is what the closed control shows, where there is no group heading to
 * lean on.
 *
 * `detail` is one line saying what the difference actually is. "Seamless" and
 * "constant radius" are both "rounded" in prose and visibly different on the
 * finished mold, so the difference is spelled out rather than implied.
 */
export interface VariantName {
  group?: string
  name: string
  full: string
  detail?: string
}

export const VARIANT_NAMES: Record<string, VariantName> = {
  // -- tray plan curves ----------------------------------------------------
  g2_quintic_obround: {
    group: 'Rounded ends',
    name: 'Seamless',
    full: 'Rounded ends, seamless',
    detail: 'No seam where the curve meets the straight',
  },
  circular_obround: {
    group: 'Rounded ends',
    name: 'Constant radius',
    full: 'Rounded ends, constant radius',
    detail: 'A true circular arc',
  },
  conic_obround: {
    group: 'Rounded ends',
    name: 'Adjustable fullness',
    full: 'Rounded ends, adjustable',
    detail: 'A conic curve you can tune between flat and full',
  },
  g2_quintic_rect: {
    group: 'Rounded corners',
    name: 'Seamless',
    full: 'Rounded corners, seamless',
    detail: 'No seam where the corner meets the side',
  },
  circular_rect: {
    group: 'Rounded corners',
    name: 'Constant radius',
    full: 'Rounded corners, constant radius',
    detail: 'The classic rounded rectangle',
  },
  conic_rect: {
    group: 'Rounded corners',
    name: 'Adjustable fullness',
    full: 'Rounded corners, adjustable',
    detail: 'A conic corner you can tune between flat and full',
  },
  ellipse: {
    group: 'Fully curved',
    name: 'Ellipse',
    full: 'Ellipse',
    detail: 'A true oval, with no straight sides at all',
  },
  superellipse: {
    group: 'Fully curved',
    name: 'Squircle',
    full: 'Squircle',
    detail: 'Between a rectangle and an ellipse',
  },

  // -- edge treatments -----------------------------------------------------
  g2_quintic_blend: {
    name: 'Seamless',
    full: 'Seamless',
    detail: 'Curvature-continuous, the softest of the options',
  },
  circular_fillet: {
    name: 'Rounded',
    full: 'Rounded',
    detail: 'A true circular fillet of a set radius',
  },
  chamfer: {
    name: 'Chamfer',
    full: 'Chamfer',
    detail: 'A flat cut across the edge',
  },
  none: {
    name: 'None',
    full: 'None',
    detail: 'Leave the edge sharp',
  },
}

/** Title case from a snake_case key, for a variant nobody has named yet. */
export function fallbackName(key: string): string {
  const words = key.replace(/_/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function variantName(key: string, schemaTitle?: string): VariantName {
  const known = VARIANT_NAMES[key]
  if (known) return known
  // Never the Pydantic class name: "G2QuinticObroundProfile" is worse than
  // anything derivable from the key itself.
  const name = fallbackName(key) || schemaTitle || key
  return { name, full: name }
}
