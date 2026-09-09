/**
 * Transport shapes only.
 *
 * The parameter document is deliberately typed as `unknown`-ish JSON: its schema
 * is served by the backend and rendered from that schema, so restating it here
 * in TypeScript would create the second source of truth this project exists to
 * avoid. Only the envelopes are typed.
 */
export type Json = Record<string, any>

export type Severity = 'error' | 'warning' | 'info'

export interface Diagnostic {
  code: string
  severity: Severity
  field: string
  message: string
}

export interface ValidateResponse {
  valid: boolean
  diagnostics: Diagnostic[]
  derived: Record<string, number | string | null>
  params_hash: string
  schema_version: string
  model_version: string
}

export type JobState = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled'

export interface Artifact {
  name: string
  format: 'glb' | 'step' | 'stl'
  part: 'male' | 'female' | 'assembly'
  bytes: number
  sha256: string
  url: string
}

export interface Job {
  id: string
  state: JobState
  kind: 'preview' | 'export'
  /** 0-1 as each build stage lands; null before the first one and on a cache hit. */
  progress: number | null
  /** The stage id behind that fraction, e.g. 'male_floor_blend'. */
  stage: string | null
  status: string | null
  params_hash: string | null
  cache_key: string | null
  cached: boolean
  artifacts: Record<string, Artifact>
  bundle_url: string | null
  diagnostics: Diagnostic[]
  derived: Record<string, number | string | null>
  volumes_cm3: Record<string, number>
  timings: Record<string, number>
  error: { kind: string; message: string; diagnostics: Diagnostic[] } | null
}

export interface UiHintField {
  unit?: string
  step?: number
  slider?: [number, number]
  help?: string
  note?: string
  experimental?: boolean
  requires?: string
  unimplemented?: boolean
  disabled_values?: Record<string, { code: string; reason: string }>
}

export interface UiHints {
  groups: { id: string; title: string; fields: string[]; description?: string; collapsed?: boolean }[]
  hidden: string[]
  fields: Record<string, UiHintField>
  derived: { key: string; label: string; unit?: string; precision?: number }[]
}

export interface SchemaResponse {
  schema_version: string
  model_version: string
  json_schema: Json
  defaults: Json
  ui_hints: UiHints
}

export interface Preset {
  name: string
  title: string
  description: string
  params: Json
}
