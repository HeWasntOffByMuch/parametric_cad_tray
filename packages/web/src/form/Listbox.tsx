import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'

/**
 * A select that can show a picture.
 *
 * The native control cannot: `<option>` renders text and nothing else, and the
 * difference between eight plan curves is not something a word carries. So this
 * is the ARIA combobox-with-listbox pattern, written to behave the way the
 * control it replaces behaves - because a custom dropdown that is *nearly* a
 * select is worse than a plain one.
 *
 * What "like the native one" was taken to mean, concretely:
 *
 *   * Up/Down/Home/End move the selection, Enter and Space commit, Escape
 *     cancels back to what was selected when it opened, Tab commits and moves on.
 *   * Typing jumps to the first option starting with what you typed, and keeps
 *     accumulating for as long as you keep typing.
 *   * Opening puts the highlight on the current value, not on the first option.
 *   * Focus never leaves the button: the active option is named by
 *     `aria-activedescendant`, which keeps a screen reader and a touch keyboard
 *     in step without moving focus into a popup.
 *
 * The popup is `position: fixed`. It has to be: the parameter sidebar is an
 * `overflow-y: auto` column, and an absolutely positioned popup inside it is
 * clipped by that column the moment the list is taller than the space below the
 * button. Fixed means the popup is measured against the viewport instead, which
 * also makes it flip above the button and shrink to fit rather than run off the
 * bottom of a phone.
 */
export interface ListboxOption {
  value: string
  label: string
  /** What the closed control says, when the row's own label leans on its group
   *  heading for meaning: "Seamless" is three different shapes without one. */
  selectedLabel?: string
  detail?: string
  group?: string
  icon?: React.ReactNode
  disabled?: boolean
}

const TYPEAHEAD_MS = 700

export function Listbox({
  options,
  value,
  onChange,
  label,
  id,
  className,
}: {
  options: ListboxOption[]
  value: string
  onChange: (value: string) => void
  label: string
  id?: string
  className?: string
}) {
  const generated = useId()
  const listId = `${id ?? generated}-list`
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(value)
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const openedWith = useRef(value)
  const [box, setBox] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null)

  // Grouped, because the schema lists the variants in declaration order and
  // that order interleaves the families - the picker showed "Rounded ends"
  // three separate times. Groups keep their first-seen order; ungrouped
  // options stay put at the end.
  const ordered = useMemo(() => {
    const seen: string[] = []
    for (const option of options) {
      const group = option.group ?? ''
      if (!seen.includes(group)) seen.push(group)
    }
    return seen.flatMap((group) => options.filter((o) => (o.group ?? '') === group))
  }, [options])

  const enabled = ordered.filter((o) => !o.disabled)
  const selected = ordered.find((o) => o.value === value)

  const place = useCallback(() => {
    const anchor = button.current?.getBoundingClientRect()
    if (!anchor) return
    const margin = 8
    const below = window.innerHeight - anchor.bottom - margin
    const above = anchor.top - margin
    // Below unless there is meaningfully more room above, which is what a
    // native menu does near the bottom of a short window.
    const flip = below < 200 && above > below
    setBox({
      top: flip ? Math.max(margin, anchor.top - Math.min(above, 420)) : anchor.bottom + 4,
      left: Math.max(margin, Math.min(anchor.left, window.innerWidth - anchor.width - margin)),
      width: anchor.width,
      maxHeight: Math.min(flip ? above : below, 420),
    })
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    place()
    // Fixed positioning is measured against the viewport, so anything that
    // moves the button relative to it has to re-measure. Capture, because the
    // sidebar scrolls, not the page.
    const update = () => place()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [open, place])

  // Keep the highlighted option in view, the way arrowing through a native
  // select scrolls it.
  useEffect(() => {
    if (!open) return
    const row = list.current?.querySelector('[data-active="true"]')
    // Optional call, not just optional chain: scrollIntoView is missing in
    // jsdom and in a few older embedded browsers, and keeping a row in view is
    // never worth throwing over.
    row?.scrollIntoView?.({ block: 'nearest' })
  }, [open, active])

  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent | TouchEvent) => {
      const target = event.target as Node
      if (button.current?.contains(target) || list.current?.contains(target)) return
      close(false)
    }
    // Pointer events cover mouse and touch in one listener; `capture` so a
    // click on something that stops propagation still dismisses.
    document.addEventListener('pointerdown', dismiss as EventListener, true)
    return () => document.removeEventListener('pointerdown', dismiss as EventListener, true)
  })

  function openList() {
    openedWith.current = value
    setActive(value)
    setOpen(true)
  }

  function close(commit: boolean, next = active) {
    setOpen(false)
    setBox(null)
    if (commit && next !== value) onChange(next)
    button.current?.focus()
  }

  function step(by: number) {
    if (!enabled.length) return
    const at = enabled.findIndex((o) => o.value === active)
    const to = Math.max(0, Math.min(enabled.length - 1, (at < 0 ? 0 : at) + by))
    setActive(enabled[to].value)
  }

  function jump(to: 'first' | 'last') {
    if (!enabled.length) return
    setActive(enabled[to === 'first' ? 0 : enabled.length - 1].value)
  }

  function typeahead(key: string) {
    const now = Date.now()
    const text = (now - typed.current.at < TYPEAHEAD_MS ? typed.current.text : '') + key.toLowerCase()
    typed.current = { text, at: now }
    const match = enabled.find((o) => o.label.toLowerCase().startsWith(text))
    if (match) {
      setActive(match.value)
      if (!open) onChange(match.value)
    }
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const key = event.key
    if (!open) {
      // A closed native select opens on Down/Up/Enter/Space and steps on
      // arrows in some browsers; opening is the less surprising of the two.
      if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') {
        event.preventDefault()
        openList()
        return
      }
      if (key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault()
        typeahead(key)
      }
      return
    }

    switch (key) {
      case 'ArrowDown': event.preventDefault(); step(1); break
      case 'ArrowUp': event.preventDefault(); step(-1); break
      case 'Home': event.preventDefault(); jump('first'); break
      case 'End': event.preventDefault(); jump('last'); break
      case 'PageDown': event.preventDefault(); step(5); break
      case 'PageUp': event.preventDefault(); step(-5); break
      case 'Enter':
      case ' ':
        event.preventDefault()
        close(true)
        break
      case 'Escape':
        event.preventDefault()
        close(false, openedWith.current)
        break
      case 'Tab':
        // Tab commits and moves on, as a native select does. No preventDefault:
        // the browser still moves focus.
        close(true)
        break
      default:
        if (key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
          event.preventDefault()
          typeahead(key)
        }
    }
  }

  let lastGroup: string | undefined
  return (
    <div className={`listbox${className ? ` ${className}` : ''}`}>
      <button
        ref={button}
        type="button"
        id={id}
        className="listbox-button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        aria-label={label}
        onClick={() => (open ? close(false, openedWith.current) : openList())}
        onKeyDown={onKeyDown}
      >
        {selected?.icon && <span className="listbox-icon" aria-hidden="true">{selected.icon}</span>}
        <span className="listbox-value">{selected?.selectedLabel ?? selected?.label ?? value}</span>
        <svg className="listbox-caret" viewBox="0 0 10 6" aria-hidden="true" focusable="false">
          <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && box && (
        <ul
          ref={list}
          id={listId}
          role="listbox"
          aria-label={label}
          className="listbox-list"
          style={{ top: box.top, left: box.left, width: box.width, maxHeight: box.maxHeight }}
        >
          {ordered.map((option) => {
            const heading = option.group && option.group !== lastGroup ? option.group : null
            lastGroup = option.group
            const isActive = option.value === active
            return (
              <li key={option.value} className="listbox-item">
                {heading && (
                  <span className="listbox-group" role="presentation">
                    {heading}
                  </span>
                )}
                <span
                  id={`${listId}-${option.value}`}
                  role="option"
                  aria-selected={option.value === value}
                  aria-disabled={option.disabled || undefined}
                  data-active={isActive}
                  className="listbox-option"
                  // Pointer, not click: the highlight should follow the finger
                  // or the mouse before the press completes, as a menu does.
                  onPointerMove={() => !option.disabled && setActive(option.value)}
                  onClick={() => !option.disabled && close(true, option.value)}
                >
                  {option.icon && <span className="listbox-icon" aria-hidden="true">{option.icon}</span>}
                  <span className="listbox-text">
                    <span className="listbox-label">{option.label}</span>
                    {option.detail && <span className="listbox-detail">{option.detail}</span>}
                  </span>
                  {option.value === value && (
                    <svg className="listbox-tick" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
                      <path d="M2 6.5l2.8 2.8L10 3.5" fill="none" stroke="currentColor" strokeWidth="1.6"
                            strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
