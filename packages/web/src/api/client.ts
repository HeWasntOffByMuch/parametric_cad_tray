import { apiUrl } from '../config'
import { ids } from '../analytics'
import type { Diagnostic, Job, Json, Preset, SchemaResponse, ValidateResponse } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: any = null,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch (cause) {
    throw new ApiError('the backend is unreachable', 0, cause)
  }
  const text = await response.text()
  const body = text ? safeJson(text) : null
  if (!response.ok) {
    throw new ApiError(errorMessage(body, response.status), response.status, body)
  }
  return body as T
}

function safeJson(text: string) {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function errorMessage(body: any, status: number): string {
  // A refusal carries the field it is about, and that sentence is the only part
  // anyone can act on. Lead with it rather than with the envelope's summary.
  const [first] = diagnosticsIn(body)
  if (first) return first.field ? `${first.field} ${first.message}` : first.message
  if (body?.detail?.error?.message) return body.detail.error.message
  if (typeof body?.detail === 'string') return body.detail
  if (status === 429) return 'too many build requests; wait a moment'
  if (status === 413) return 'that parameter document is too large'
  return `request failed (${status})`
}

function diagnosticsIn(body: any): Diagnostic[] {
  const list = body?.detail?.error?.diagnostics
  return Array.isArray(list) ? list : []
}

/**
 * The diagnostics a rejected request came back with, if any.
 *
 * A 422 is the server declining to work with the document that is on screen, so
 * its diagnostics describe *that* document - which makes them the ones to show,
 * on the fields they name. Anything else (offline, a 500, a rate limit) has
 * nothing field-shaped in it and yields none.
 */
export function diagnosticsOf(error: unknown): Diagnostic[] {
  return error instanceof ApiError ? diagnosticsIn(error.body) : []
}

export const api = {
  schema: () => request<SchemaResponse>('/api/schema'),
  presets: () => request<Preset[]>('/api/presets'),
  version: () => request<Json>('/api/version'),
  health: () => request<Json>('/api/health'),

  /** Public counters. Any failure is the caller's to ignore, not to surface. */
  stats: () => request<Json>('/api/stats'),

  validate: (params: Json, allowExperimental = false, signal?: AbortSignal) =>
    request<ValidateResponse>('/api/validate', {
      method: 'POST',
      body: JSON.stringify({ params, allow_experimental: allowExperimental }),
      signal,
    }),

  preview: (params: Json, allowExperimental = false) =>
    request<Job>('/api/preview', {
      method: 'POST',
      // The session rides the build request so the server can attribute the
      // outcome itself, rather than believing a later claim from the browser.
      body: JSON.stringify({
        params,
        allow_experimental: allowExperimental,
        session_id: ids().session_id,
      }),
    }),

  export: (
    params: Json,
    opts: { parts?: { male: boolean; female: boolean }; formats?: string[] } = {},
    allowExperimental = false,
  ) =>
    request<Job>('/api/export', {
      method: 'POST',
      body: JSON.stringify({
        params,
        parts: opts.parts,
        formats: opts.formats,
        allow_experimental: allowExperimental,
        session_id: ids().session_id,
      }),
    }),

  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancel: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
}
