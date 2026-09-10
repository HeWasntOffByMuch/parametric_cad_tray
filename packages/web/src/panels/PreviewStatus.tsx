import type { PreviewState } from '../state/useDesign'
import type { Diagnostic, Job } from '../api/types'

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
  errors,
  onReveal,
  onGenerate,
  onCancel,
  canGenerate,
}: {
  state: PreviewState
  job: Job | null
  validating: boolean
  transportError: string | null
  /** Blocking diagnostics. This bar floats over the viewer and is on screen at
   *  every width, which the form and the diagnostics panel are not: stacked on
   *  a phone they sit several screens down, so an invalid parameter used to
   *  read as "Preview out of date" and nothing else. */
  errors: Diagnostic[]
  onReveal: (field: string) => void
  onGenerate: () => void
  onCancel: () => void
  canGenerate: boolean
}) {
  const blocking = errors[0] ?? null
  const copy = blocking ? { label: 'Cannot build these parameters', tone: 'bad' } : COPY[state]
  const detail = blocking
    ? null
    : state === 'generating'
    ? job?.status ?? 'queued'
    : state === 'failed'
      ? job?.error?.message ?? transportError ?? 'the build did not complete'
      : job?.cached
        ? 'served from cache'
        : null

  // Only while generating, and only once the worker has actually reported a
  // stage. Before that there is nothing true to draw: a bar sitting at 0 is a
  // promise, and one that animates on its own is a lie.
  const fraction =
    !blocking && state === 'generating' && typeof job?.progress === 'number' ? job.progress : null
  const percent = fraction === null ? null : Math.round(fraction * 100)

  return (
    <div className="preview-status" data-testid="preview-status" data-state={state}>
      <div className="status-row">
        <span className={`status-dot ${copy.tone}`} aria-hidden="true" />
        <span className="status-label" role="status" aria-live="polite">
          {copy.label}
        </span>
        {detail && <span className="detail">{detail}</span>}
        {percent !== null && (
          <span className="detail progress-percent" data-testid="progress-percent">
            {percent}%
          </span>
        )}
        {validating && !blocking && <span className="detail">checking…</span>}
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
      {blocking && (
        <p className="status-problem" data-testid="blocking-error">
          <span className="what" title={`${blocking.field} ${blocking.message}`}>
            <strong>{fieldLabel(blocking.field)}</strong> {blocking.message}
          </span>
          <button type="button" onClick={() => onReveal(blocking.field)}>
            Show me
          </button>
          {errors.length > 1 && (
            <span className="detail" data-testid="blocking-more">
              +{errors.length - 1} more
            </span>
          )}
        </p>
      )}
      {fraction !== null && (
        <div
          className="progress-track"
          data-testid="progress-bar"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? 0}
          aria-label="Build progress"
        >
          <div className="progress-fill" style={{ transform: `scaleX(${fraction})` }} />
        </div>
      )}
    </div>
  )
}


/** `tray.profile.length` is a path, not a name. Show the leaf, which is what
 *  the field is labelled with on screen. */
function fieldLabel(path: string): string {
  const leaf = path.split('.').pop() ?? path
  return leaf.replace(/_/g, ' ')
}
