import type { Diagnostic } from '../api/types'

/**
 * Diagnostics also render inline next to their field. This panel is the summary
 * for anything that names a group rather than a single field, and the place a
 * user looks to find out why Preview is disabled.
 */
export function DiagnosticsPanel({ diagnostics, transportError }: { diagnostics: Diagnostic[]; transportError: string | null }) {
  const errors = diagnostics.filter((d) => d.severity === 'error')
  const warnings = diagnostics.filter((d) => d.severity === 'warning')
  if (!errors.length && !warnings.length && !transportError) return null
  return (
    <div className="diagnostics" data-testid="diagnostics-panel">
      {transportError && (
        <p className="diag error" data-testid="transport-error">
          <span className="code">offline</span> {transportError}
        </p>
      )}
      {[...errors, ...warnings].map((d) => (
        <p key={`${d.code}-${d.field}`} className={`diag ${d.severity}`}>
          <span className="code">{d.code}</span> <strong>{d.field}</strong> {d.message}
        </p>
      ))}
    </div>
  )
}
