import { apiUrl } from '../config'
import { api } from './client'
import type { Job } from './types'

const TERMINAL = new Set(['complete', 'failed', 'cancelled'])

/**
 * Follow a job to its terminal state.
 *
 * Server-sent events are the primary channel: the backend pushes on every state
 * transition, so the browser learns a build finished the moment the worker
 * returns. If the stream never opens or drops early - a proxy that buffers, an
 * API restart - this falls back to `GET /api/jobs/{id}`, which is exactly why
 * that endpoint still exists.
 *
 * Returns an abort function. Aborting stops the listener; it does not cancel the
 * build (that is `api.cancel`).
 */
export function followJob(
  jobId: string,
  handlers: { onUpdate: (job: Job) => void; onDone: (job: Job) => void; onError?: (e: Error) => void },
): () => void {
  let stopped = false
  let source: EventSource | null = null
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let sawAnyEvent = false

  const finish = (job: Job) => {
    if (stopped) return
    stopped = true
    source?.close()
    if (pollTimer) clearTimeout(pollTimer)
    handlers.onDone(job)
  }

  const deliver = (job: Job) => {
    if (stopped) return
    sawAnyEvent = true
    handlers.onUpdate(job)
    if (TERMINAL.has(job.state)) finish(job)
  }

  const startPolling = (intervalMs = 400) => {
    if (stopped || pollTimer) return
    const tick = async () => {
      if (stopped) return
      try {
        deliver(await api.job(jobId))
      } catch (error) {
        handlers.onError?.(error as Error)
      }
      if (!stopped) pollTimer = setTimeout(tick, intervalMs)
    }
    pollTimer = setTimeout(tick, 0)
  }

  if (typeof EventSource === 'undefined') {
    startPolling()
    return () => {
      stopped = true
      if (pollTimer) clearTimeout(pollTimer)
    }
  }

  source = new EventSource(apiUrl(`/api/jobs/${jobId}/events`))
  source.onmessage = (event) => deliver(JSON.parse(event.data) as Job)
  for (const name of ['queued', 'running', 'complete', 'failed', 'cancelled']) {
    source.addEventListener(name, (event) => deliver(JSON.parse((event as MessageEvent).data) as Job))
  }
  source.onerror = () => {
    // EventSource retries on its own, but a stream that never delivered anything
    // is more likely blocked than flaky - fall back rather than spin.
    source?.close()
    if (!stopped) {
      if (!sawAnyEvent) handlers.onError?.(new Error('event stream unavailable, falling back to polling'))
      startPolling()
    }
  }

  return () => {
    stopped = true
    source?.close()
    if (pollTimer) clearTimeout(pollTimer)
  }
}
