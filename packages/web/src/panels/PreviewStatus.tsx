import type { PreviewState } from '../state/useDesign'
import type { Job } from '../api/types'

/**
 * A dot and a sentence, not a coloured chip announcing a state name.
 *
 * The wording deliberately says what the *preview* is, so the indicator reads as
 * information about the model on screen rather than as a status field in a
 * developer tool. "Up to date" and "out of date" are the two a user acts on, so
 * they stay in plain language.
 */
const COPY: Record<PreviewState, { label: string; tone: string }> = {
  empty: { label: 'No preview yet', tone: 'idle' },
  generating: { label: 'Generating preview…', tone: 'busy' },
  clean: { label: 'Preview up to date', tone: 'ok' },
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
      <span className={`status-dot ${copy.tone}`} aria-hidden="true" />
      <span className="status-label" role="status" aria-live="polite">
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
        <button
          type="button"
          // Accented only when there is something to build. Left permanently
          // blue it competes with Export, which is the action that actually
          // ends the session.
          className={canGenerate ? 'primary' : undefined}
          onClick={onGenerate}
          disabled={!canGenerate}
          title={
            state === 'clean'
              ? 'The preview already matches these parameters'
              : 'Build the preview from the current parameters'
          }
        >
          Update preview
        </button>
      )}
    </div>
  )
}
