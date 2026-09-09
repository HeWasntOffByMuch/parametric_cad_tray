import { useState } from 'react'
import type { Diagnostic, UiHintField } from '../api/types'
import type { Field } from './schema'

export interface WidgetProps {
  field: Field
  value: any
  hint?: UiHintField
  /** Parent legend, e.g. "Pry notches". Several fields share a short title -
   *  three different things are called "Depth" - so the accessible name is
   *  qualified even though the visible label stays short. */
  context?: string
  diagnostics: Diagnostic[]
  disabled?: boolean
  /** every keystroke: cheap, drives validation */
  onChange: (value: any) => void
  /** the user finished: blur, Enter, slider release. Preview may regenerate. */
  onCommit: () => void
}

function bounds(field: Field): { min?: number; max?: number } {
  return {
    min: field.minimum ?? field.exclusiveMinimum,
    max: field.maximum ?? field.exclusiveMaximum,
  }
}

export function FieldMessages({ diagnostics, hint }: { diagnostics: Diagnostic[]; hint?: UiHintField }) {
  return (
    <>
      {hint?.help && <p className="hint">{hint.help}</p>}
      {hint?.note && <p className="hint warn">{hint.note}</p>}
      {diagnostics.map((d) => (
        <p key={d.code} className={`diag ${d.severity}`} data-testid={`diag-${d.code}`}>
          <span className="code">{d.code}</span> {d.message}
        </p>
      ))}
    </>
  )
}

/**
 * Number input plus an optional slider.
 *
 * The text input is authoritative: it accepts any value the schema allows, and
 * the slider is a convenience whose range may be narrower than the schema's.
 * Dragging updates the value (so validation and derived figures track the drag)
 * but only commits on release, because a commit is what may start a CAD build.
 */
function accessibleName(field: Field, context?: string): string {
  return context ? `${context} ${field.title}` : field.title
}

export function NumberWidget({ field, value, hint, context, diagnostics, disabled, onChange, onCommit }: WidgetProps) {
  // The input is controlled by the parameter document, with a local draft only
  // while the user is mid-edit - so "1." and "" survive typing, and a value that
  // changes underneath (a preset, a shared link) appears immediately without an
  // effect to synchronise.
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? (value ?? value === 0 ? String(value) : '')
  const { min, max } = bounds(field)
  const step = hint?.step ?? (field.kind === 'integer' ? 1 : 0.1)
  const slider = hint?.slider

  const push = (raw: string) => {
    setDraft(raw)
    if (raw === '') {
      if (field.nullable) onChange(null)
      return
    }
    const parsed = Number(raw)
    if (!Number.isNaN(parsed)) onChange(parsed)
  }

  const commit = () => {
    setDraft(null)
    onCommit()
  }

  return (
    <div className="field" data-field={field.path}>
      <span className="label" aria-hidden="true">
        {field.title}
        {hint?.unit && <em className="unit">{hint.unit}</em>}
      </span>
      <div className="control">
        <input
          type="number"
          inputMode="decimal"
          aria-label={accessibleName(field, context)}
          value={shown}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(e) => push(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => e.key === 'Enter' && commit()}
        />
        {slider && (
          <input
            type="range"
            aria-label={`${accessibleName(field, context)} slider`}
            className="slider"
            min={slider[0]}
            max={slider[1]}
            step={step}
            disabled={disabled}
            value={Number(value ?? slider[0])}
            onChange={(e) => {
              setDraft(null)
              onChange(Number(e.target.value))
            }}
            onPointerUp={commit}
            onKeyUp={commit}
            onTouchEnd={commit}
          />
        )}
      </div>
      <FieldMessages diagnostics={diagnostics} hint={hint} />
    </div>
  )
}

export function BooleanWidget({ field, value, hint, context, diagnostics, disabled, onChange, onCommit }: WidgetProps) {
  // A checkbox keeps its <label> wrapper - clicking the caption to toggle is
  // worth more than the tidiness - so the caption itself carries the qualified
  // name and there is only one name to compute.
  return (
    <label className="field checkbox" data-field={field.path}>
      <input
        type="checkbox"
        checked={Boolean(value)}
        disabled={disabled}
        onChange={(e) => {
          onChange(e.target.checked)
          onCommit()
        }}
      />
      <span className="label">{accessibleName(field, context)}</span>
      <FieldMessages diagnostics={diagnostics} hint={hint} />
    </label>
  )
}

export function EnumWidget({ field, value, hint, context, diagnostics, disabled, onChange, onCommit }: WidgetProps) {
  const blocked = hint?.disabled_values ?? {}
  const blockedNote = Object.entries(blocked)
    .map(([option, info]) => `${option}: ${info.reason}`)
    .join(' ')
  return (
    <div className="field" data-field={field.path}>
      <span className="label" aria-hidden="true">{field.title}</span>
      <select
        aria-label={accessibleName(field, context)}
        value={String(value ?? '')}
        disabled={disabled}
        onChange={(e) => {
          onChange(e.target.value)
          onCommit()
        }}
      >
        {(field.options ?? []).map((option) => (
          // An unsupported value is offered but disabled, with the reason
          // visible: a user must not be able to pick it and only discover the
          // limitation after a failed submission.
          <option key={option} value={option} disabled={option in blocked}>
            {option}
            {option in blocked ? ' — not available yet' : ''}
          </option>
        ))}
      </select>
      {blockedNote && <p className="hint">{blockedNote}</p>}
      <FieldMessages diagnostics={diagnostics} hint={hint} />
    </div>
  )
}

export function TextWidget({ field, value, hint, context, diagnostics, disabled, onChange, onCommit }: WidgetProps) {
  return (
    <div className="field" data-field={field.path}>
      <span className="label" aria-hidden="true">{field.title}</span>
      <input
        type="text"
        aria-label={accessibleName(field, context)}
        value={String(value ?? '')}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onCommit}
      />
      <FieldMessages diagnostics={diagnostics} hint={hint} />
    </div>
  )
}
