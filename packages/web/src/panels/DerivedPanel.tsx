import type { Job, UiHints, ValidateResponse } from '../api/types'

/**
 * Every number here is computed by the backend and rendered as received.
 * Nothing in this panel is recalculated in React - a second implementation of
 * the derivations would be a second source of truth.
 */
export function DerivedPanel({
  validation,
  hints,
  job,
}: {
  validation: ValidateResponse | null
  hints: UiHints
  job: Job | null
}) {
  if (!validation) return <div className="derived empty">—</div>
  const rows = (hints.derived ?? []).map((spec) => {
    const raw = validation.derived[spec.key]
    return { ...spec, value: raw }
  })
  const volumes = job?.volumes_cm3 ?? {}

  return (
    <div className="derived" data-testid="derived-panel">
      <dl>
        {rows.map((row) => (
          <div key={row.key} className="derived-row">
            <dt>{row.label}</dt>
            <dd data-testid={`derived-${row.key}`}>{format(row.value, row.precision)}{row.unit ? ` ${row.unit}` : ''}</dd>
          </div>
        ))}
        {Object.entries(volumes).map(([key, value]) => (
          <div key={key} className="derived-row">
            <dt>{key.replace('_cm3', '')} volume</dt>
            <dd data-testid={`derived-${key}`}>{value.toFixed(1)} cm³</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function format(value: unknown, precision = 2): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '∞'
    return value.toFixed(precision)
  }
  return String(value)
}
