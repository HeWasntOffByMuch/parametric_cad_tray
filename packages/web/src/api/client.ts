import { apiUrl } from '../config'
import { ids } from '../analytics'
import type { Job, Json, Preset, SchemaResponse, ValidateResponse } from './types'

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
  if (body?.detail?.error?.message) return body.detail.error.message
  if (typeof body?.detail === 'string') return body.detail
  if (status === 429) return 'too many build requests; wait a moment'
  if (status === 413) return 'that parameter document is too large'
  return `request failed (${status})`
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
