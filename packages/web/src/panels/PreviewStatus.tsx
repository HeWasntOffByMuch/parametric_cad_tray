import type { PreviewState } from '../state/useDesign'
import type { Job } from '../api/types'

const COPY: Record<PreviewState, { label: string; tone: string }> = {
  empty: { label: 'No preview yet', tone: 'idle' },
  generating: { label: 'Generating…', tone: 'busy' },
  clean: { label: 'Up to date', tone: 'ok' },
  dirty: { label: 'Preview out of date', tone: 'warn' },
  failed: { label: 'Preview failed', tone: 'bad' },
}

export function PreviewStatus({
  state,
  job,
  validating,
  transportError,
  onGenerate,
  onCancel,
  canGenerate,
}: {
  state: PreviewState
  job: Job | null
  validating: boolean
  transportError: string | null
  onGenerate: () => void
  onCancel: () => void
  canGenerate: boolean
}) {
  const copy = COPY[state]
  const detail =
    state === 'generating'
      ? job?.status ?? 'queued'
      : state === 'failed'
        ? job?.error?.message ?? transportError ?? 'the build did not complete'
        : job?.cached
          ? 'served from cache'
          : null

  return (
    <div className="preview-status" data-testid="preview-status" data-state={state}>
      <span className={`pill ${copy.tone}`} role="status" aria-live="polite">
        {copy.label}
      </span>
      {detail && <span className="detail">{detail}</span>}
      {validating && <span className="detail">checking…</span>}
      <span className="spacer" />
      {state === 'generating' ? (
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      ) : (
        <button type="button" className="primary" onClick={onGenerate} disabled={!canGenerate}>
          Update preview
        </button>
      )}
    </div>
  )
}
