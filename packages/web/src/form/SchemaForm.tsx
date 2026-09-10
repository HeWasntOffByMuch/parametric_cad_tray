import { useState } from 'react'
import type { Diagnostic, Json, UiHints } from '../api/types'
import { BooleanWidget, EnumWidget, NumberWidget, TextWidget, type WidgetProps } from './widgets'
import { getValue, groupFields, rootFields, setValue, variantDefaults, type Field, type Group } from './schema'
import { Listbox } from './Listbox'
import { ProfileIcon } from './ProfileIcon'
import { PROFILE_SHAPES } from './profileShapes'
import { variantName } from './variantNames'

interface Props {
  jsonSchema: Json
  hints: UiHints
  value: Json
  diagnostics: Diagnostic[]
  allowExperimental: boolean
  onChange: (next: Json) => void
  onCommit: () => void
}

const WIDGETS: Record<string, (p: WidgetProps) => JSX.Element> = {
  number: NumberWidget,
  integer: NumberWidget,
  boolean: BooleanWidget,
  enum: EnumWidget,
  text: TextWidget,
}

function diagnosticsFor(all: Diagnostic[], path: string): Diagnostic[] {
  // Backend diagnostics name a field path; a group-level rule may name a parent
  // ("leather/fit"), so match on prefix as well as equality.
  return all.filter((d) => d.field === path || d.field.split('/').includes(path) || path.startsWith(`${d.field}.`))
}

export function SchemaForm(props: Props) {
  const groups = groupFields(rootFields(props.jsonSchema), props.hints)
  return (
    <div className="form">
      {groups.map((group) => (
        <GroupSection key={group.id} group={group} {...props} />
      ))}
    </div>
  )
}

function GroupSection({ group, ...props }: Props & { group: Group }) {
  const [open, setOpen] = useState(!group.collapsed)
  return (
    <section className="group" data-group={group.id}>
      <h2>
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="chevron">{open ? '▾' : '▸'}</span> {group.title}
        </button>
      </h2>
      {open && (
        <div className="group-body">
          {group.description && <p className="hint">{group.description}</p>}
          {group.fields.map((field) => (
            <FieldRenderer key={field.path} field={field} exclude={group.exclude} {...props} />
          ))}
        </div>
      )}
    </section>
  )
}

function FieldRenderer({ field, exclude, context, ...props }: Props & { field: Field; exclude: Set<string>; context?: string }) {
  if (exclude.has(field.path)) return null
  const hint = props.hints.fields?.[field.path]
  const gated = Boolean(hint?.requires === 'allow_experimental' && !props.allowExperimental)
  const diagnostics = diagnosticsFor(props.diagnostics, field.path)

  if (field.kind === 'variant') return <VariantField field={field} exclude={exclude} context={context} {...props} />

  if (field.kind === 'object') {
    return (
      <fieldset className="object" data-field={field.path}>
        <legend>{field.title}</legend>
        {field.children?.map((child) => (
          <FieldRenderer key={child.path} field={child} exclude={exclude} context={field.title} {...props} />
        ))}
      </fieldset>
    )
  }

  const Widget = WIDGETS[field.kind] ?? TextWidget
  return (
    <div className={gated ? 'gated' : undefined}>
      {gated && (
        <p className="hint warn" data-testid={`experimental-${field.path}`}>
          Experimental — enable experimental parameters to edit. {hint?.note}
        </p>
      )}
      <Widget
        field={field}
        hint={hint}
        context={context}
        value={getValue(props.value, field.path)}
        diagnostics={diagnostics}
        disabled={gated}
        onChange={(next) => props.onChange(setValue(props.value, field.path, next))}
        onCommit={props.onCommit}
      />
    </div>
  )
}

/**
 * Discriminated union: a selector for the variant plus that variant's own
 * fields. Switching variants carries over any field the two share, so changing
 * corner style does not silently reset the tray's dimensions.
 */
function VariantField({ field, exclude, context, ...props }: Props & { field: Field; exclude: Set<string>; context?: string }) {
  const current = getValue(props.value, field.path) ?? {}
  const key = String(current[field.discriminator ?? 'kind'] ?? field.variants?.[0]?.key)
  const variant = field.variants?.find((v) => v.key === key)
  return (
    <fieldset className="object variant" data-field={field.path}>
      <legend>{field.title}</legend>
      <div className="field">
        <Listbox
          label={`${context ? `${context} ` : ''}${field.title} type`}
          value={key}
          options={(field.variants ?? []).map((v) => {
            const named = variantName(v.key, v.title)
            return {
              value: v.key,
              label: named.name,
              selectedLabel: named.full,
              detail: named.detail,
              group: named.group,
              icon: PROFILE_SHAPES[v.key] ? <ProfileIcon kind={v.key} /> : undefined,
            }
          })}
          onChange={(next) => {
            props.onChange(setValue(props.value, field.path, variantDefaults(field, next, current)))
            props.onCommit()
          }}
        />
      </div>
      {variant?.fields.map((child) => (
        <FieldRenderer key={child.path} field={child} exclude={exclude} context={field.title} {...props} />
      ))}
    </fieldset>
  )
}
