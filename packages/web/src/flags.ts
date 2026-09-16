/**
 * Hidden switches.
 *
 * A flag is a *local* opinion about what this browser should show. It never
 * grants anything: the server decides what it offers, publishes that on
 * `/api/schema` as `features`, and refuses a gated format whatever the browser
 * asks for. A flag can only hide a control the deployment already has, or
 * reveal one it already offers - so turning one on by hand cannot break
 * anything or reach past the API.
 *
 * Two ways in, deliberately both:
 *
 *   `?flags=3mf`   shareable, scriptable, and remembered afterwards - the same
 *                  shape as `?api=` in `config.ts`, for the same reason
 *   ctrl/cmd + shift + .   opens the switch panel on the page
 *
 * `?flags=` with nothing after it clears them, which is the way back out of a
 * link someone sent you.
 */
const STORAGE_KEY = 'traymold.flags'

/** Every switch this build knows about, and what turning it on does. */
export const KNOWN_FLAGS: Record<string, string> = {
  '3mf': 'Offer the 3MF export, which carries the print plan and reports what each infill option costs.',
}

/** Flag name -> the `features` key on /api/schema that has to agree. */
export const FLAG_FEATURE: Record<string, string> = {
  '3mf': '3mf',
}

function parse(value: string | null): string[] {
  if (value === null) return []
  return value
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)
}

function fromQuery(): string[] | null {
  if (typeof window === 'undefined') return null
  const raw = new URLSearchParams(window.location.search).get('flags')
  // `?flags=` present but empty is a deliberate "none", not an absent answer.
  if (raw === null) return null
  const names = parse(raw)
  store(names)
  return names
}

function store(names: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, names.join(','))
  } catch {
    /* private mode, quota */
  }
}

export function readFlags(): Set<string> {
  const queried = fromQuery()
  if (queried !== null) return new Set(queried)
  try {
    return new Set(parse(window.localStorage.getItem(STORAGE_KEY)))
  } catch {
    return new Set()
  }
}

export function writeFlags(names: Iterable<string>): Set<string> {
  const set = new Set(names)
  store([...set])
  return set
}

/** Is this switch on here *and* offered by the deployment? Both, always. */
export function enabled(flags: Set<string>, features: Record<string, boolean> | undefined, name: string): boolean {
  const feature = FLAG_FEATURE[name]
  return flags.has(name) && Boolean(features?.[feature])
}

/** The chord that opens the panel. Nothing types a character, so it is safe
 *  inside a text field. */
export function isFlagsChord(event: KeyboardEvent): boolean {
  return (event.ctrlKey || event.metaKey) && event.shiftKey && (event.key === '.' || event.key === '>')
}
