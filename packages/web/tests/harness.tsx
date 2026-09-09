import { vi } from 'vitest'
import fixtures from './fixtures.json'
import type { Artifact, Job, Json } from '../src/api/types'

export const SCHEMA = fixtures.schema as any
export const PRESETS = fixtures.presets as any[]
export const REF_PARAMS = PRESETS.find((p) => p.name === 'ref-4x7')!.params as Json

/** A scripted backend. Every response is explicit, so a test says what it means. */
export class FakeBackend {
  validateCalls: Json[] = []
  previewCalls: Json[] = []
  exportCalls: any[] = []
  cancelled: string[] = []
  jobs = new Map<string, Job>()
  /** overrides, applied in order of specificity */
  validateResponse: ((params: Json) => any) | null = null
  /** Public counters the app may display; null means the endpoint is absent. */
  stats: any = null
  statsError = false
  /** Every client telemetry event the app sent, in order. */
  events: any[] = []
  previewResponse: ((params: Json, id: string) => Job) | null = null
  exportResponse: ((body: any, id: string) => Job) | null = null
  private counter = 0

  /** Deterministic content hash, standing in for the backend's params_hash.
   *  Content-sensitive on purpose: the staleness logic keys off it. */
  hashOf(params: Json): string {
    const text = JSON.stringify(params)
    let hash = 5381
    for (let i = 0; i < text.length; i++) hash = ((hash * 33) ^ text.charCodeAt(i)) >>> 0
    return `h-${hash.toString(16)}`
  }

  job(overrides: Partial<Job> = {}): Job {
    return {
      id: `job-${++this.counter}`,
      state: 'complete',
      kind: 'preview',
      progress: null,
      stage: null,
      status: 'done',
      params_hash: null,
      cache_key: 'key',
      cached: false,
      artifacts: {},
      bundle_url: null,
      diagnostics: [],
      derived: {},
      volumes_cm3: {},
      timings: {},
      error: null,
      ...overrides,
    }
  }

  glbArtifact(): Record<string, Artifact> {
    return {
      'preview.glb': {
        name: 'preview.glb', format: 'glb' as const, part: 'assembly' as const,
        bytes: 76856, sha256: 'x', url: '/api/artifacts/key/preview.glb',
      },
    }
  }

  install() {
    const backend = this
    vi.stubGlobal('fetch', vi.fn(async (input: any, init: any = {}) => {
      const url = String(input)
      const body = init.body ? JSON.parse(init.body) : null
      const ok = (payload: any, status = 200) =>
        new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } })

      if (url.endsWith('/api/schema')) return ok(SCHEMA)
      if (url.endsWith('/api/stats')) {
        if (backend.statsError) return new Response('nope', { status: 503 })
        return ok(backend.stats ?? { custom_molds_generated: 0, unique_designs_downloaded: 0,
                                     total_artifact_downloads: 0 })
      }
      if (url.endsWith('/api/analytics/event')) {
        backend.events.push(body)
        return new Response(null, { status: 204 })
      }
      if (url.endsWith('/api/presets')) return ok(PRESETS)

      if (url.endsWith('/api/validate')) {
        backend.validateCalls.push(body.params)
        const custom = backend.validateResponse?.(body.params)
        return ok(custom ?? {
          valid: true, diagnostics: [], derived: { forming_gap: 3.0, plate_length: 235.0 },
          params_hash: backend.hashOf(body.params), schema_version: '2.0.0', model_version: '0.1.0',
        })
      }

      if (url.endsWith('/api/preview')) {
        backend.previewCalls.push(body.params)
        const id = `job-${++backend.counter}`
        const job = backend.previewResponse?.(body.params, id) ?? backend.job({
          id, params_hash: backend.hashOf(body.params), artifacts: backend.glbArtifact(),
        })
        backend.jobs.set(job.id, job)
        return ok(job, job.state === 'complete' ? 200 : 202)
      }

      if (url.endsWith('/api/export')) {
        backend.exportCalls.push(body)
        const id = `job-${++backend.counter}`
        const job = backend.exportResponse?.(body, id) ?? backend.job({
          id, kind: 'export', cached: false,
          artifacts: {
            'male.step': { name: 'male.step', format: 'step' as const, part: 'male' as const, bytes: 419201, sha256: 'a', url: '/api/artifacts/key/male.step' },
            'male.stl': { name: 'male.stl', format: 'stl' as const, part: 'male' as const, bytes: 60484, sha256: 'b', url: '/api/artifacts/key/male.stl' },
          },
          bundle_url: '/api/artifacts/key/bundle.zip',
        })
        backend.jobs.set(job.id, job)
        return ok(job, job.state === 'complete' ? 200 : 202)
      }

      const cancelMatch = url.match(/\/api\/jobs\/([^/]+)\/cancel$/)
      if (cancelMatch) {
        backend.cancelled.push(cancelMatch[1])
        const job = backend.jobs.get(cancelMatch[1])
        return ok(job ? { ...job, state: 'cancelled' } : backend.job({ state: 'cancelled' }))
      }

      const jobMatch = url.match(/\/api\/jobs\/([^/]+)$/)
      if (jobMatch) {
        const job = backend.jobs.get(jobMatch[1])
        return job ? ok(job) : ok({ detail: 'unknown job' }, 404)
      }

      return ok({ detail: 'not found' }, 404)
    }))
  }

  /** Resolve a job that was returned as queued/running, as SSE or polling would. */
  settle(id: string, patch: Partial<Job>) {
    const current = this.jobs.get(id)!
    this.jobs.set(id, { ...current, ...patch })
  }
}

/** jsdom has no EventSource; the client falls back to polling, which is the
 *  behaviour we want to exercise anyway. */
export function noEventSource() {
  vi.stubGlobal('EventSource', undefined)
}
