import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { Listbox, type ListboxOption } from '../src/form/Listbox'
import { PROFILE_SHAPES } from '../src/form/profileShapes'
import { VARIANT_NAMES, fallbackName, variantName } from '../src/form/variantNames'

const OPTIONS: ListboxOption[] = [
  { value: 'a', label: 'Alpha', group: 'Letters', detail: 'the first one' },
  { value: 'b', label: 'Bravo', group: 'Letters' },
  { value: 'c', label: 'Charlie', group: 'Letters' },
  { value: 'z', label: 'Zulu', group: 'Last', disabled: true },
]

function Harness({ onChange }: { onChange?: (v: string) => void } = {}) {
  const [value, setValue] = useState('a')
  return (
    <Listbox
      label="Test picker"
      options={OPTIONS}
      value={value}
      onChange={(v) => {
        setValue(v)
        onChange?.(v)
      }}
    />
  )
}

const trigger = () => screen.getByRole('combobox', { name: 'Test picker' })
const list = () => screen.queryByRole('listbox')

describe('the dropdown behaves like the control it replaces', () => {
  it('opens on click and closes on a second click, selecting nothing', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)

    expect(list()).not.toBeInTheDocument()
    await user.click(trigger())
    expect(list()).toBeInTheDocument()
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')

    await user.click(trigger())
    expect(list()).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('opens with the highlight on the current value, not on the first option', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    await user.keyboard('{ArrowDown}{Enter}')
    // From Alpha, one step down is Bravo. If opening had reset to the top this
    // would have landed on Bravo from a different starting point - so re-open
    // and check the highlight explicitly.
    expect(trigger()).toHaveTextContent('Bravo')
    await user.click(trigger())
    const active = screen.getByRole('option', { name: /Bravo/ })
    expect(active).toHaveAttribute('data-active', 'true')
    expect(trigger()).toHaveAttribute('aria-activedescendant', active.id)
  })

  it('arrows move, Enter commits', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(trigger()).toHaveTextContent('Charlie')
    expect(list()).not.toBeInTheDocument()
  })

  it('Home and End jump to the ends', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    await user.keyboard('{End}{Enter}')
    // Zulu is disabled, so End lands on the last *enabled* option.
    expect(trigger()).toHaveTextContent('Charlie')
    await user.click(trigger())
    await user.keyboard('{Home}{Enter}')
    expect(trigger()).toHaveTextContent('Alpha')
  })

  it('Escape cancels back to what was selected when it opened', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await user.click(trigger())
    await user.keyboard('{ArrowDown}{ArrowDown}{Escape}')
    expect(list()).not.toBeInTheDocument()
    expect(trigger()).toHaveTextContent('Alpha')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('typing jumps to a match, and keeps accumulating', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    await user.keyboard('ch')
    await user.keyboard('{Enter}')
    expect(trigger()).toHaveTextContent('Charlie')
  })

  it('opens from the keyboard alone', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.tab()
    expect(trigger()).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(list()).toBeInTheDocument()
  })

  it('keeps focus on the trigger, so nothing steals it from a touch keyboard', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    expect(trigger()).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(trigger()).toHaveFocus()
  })

  it('returns focus to the trigger after choosing, so Tab continues from here', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(trigger())
    await user.click(screen.getByRole('option', { name: /Bravo/ }))
    expect(trigger()).toHaveFocus()
    expect(list()).not.toBeInTheDocument()
  })

  it('dismisses on a press outside without changing the value', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <div>
        <Harness onChange={onChange} />
        <button type="button">elsewhere</button>
      </div>,
    )
    await user.click(trigger())
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(list()).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('will not select a disabled option', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await user.click(trigger())
    await user.click(screen.getByRole('option', { name: /Zulu/ }))
    expect(onChange).not.toHaveBeenCalled()
    expect(list()).toBeInTheDocument()
  })

  it('is a labelled combobox over a labelled listbox, with the selection marked', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(trigger()).toHaveAttribute('aria-haspopup', 'listbox')
    await user.click(trigger())
    const box = screen.getByRole('listbox', { name: 'Test picker' })
    expect(within(box).getByRole('option', { name: /Alpha/ })).toHaveAttribute('aria-selected', 'true')
    expect(within(box).getByRole('option', { name: /Bravo/ })).toHaveAttribute('aria-selected', 'false')
  })
})

describe('shape names and icons', () => {
  it('names every profile the schema can offer, and draws each one', () => {
    // A profile family added to the core without a name here would show its
    // Pydantic class name, which is what this replaced.
    const kinds = Object.keys(PROFILE_SHAPES)
    expect(kinds).toHaveLength(8)
    for (const kind of kinds) {
      expect(VARIANT_NAMES[kind], `${kind} has no human name`).toBeDefined()
      expect(VARIANT_NAMES[kind].detail, `${kind} has no explanation`).toBeTruthy()
      expect(PROFILE_SHAPES[kind].startsWith('M'), `${kind}'s path is not a path`).toBe(true)
    }
  })

  it('never falls back to a class name', () => {
    expect(variantName('some_new_profile', 'SomeNewProfileModel').name).toBe('Some new profile')
    expect(fallbackName('g2_quintic_obround')).toBe('G2 quintic obround')
  })

  it('groups the eight shapes by silhouette', () => {
    const groups = new Set(Object.keys(PROFILE_SHAPES).map((k) => VARIANT_NAMES[k].group))
    expect(groups).toEqual(new Set(['Rounded ends', 'Rounded corners', 'Fully curved']))
  })
})

describe('grouping', () => {
  it('shows each group once, even though the schema interleaves them', async () => {
    // The core declares the profile variants obround, rect, obround, rect… so
    // an "insert a heading when the group changes" rule printed "Rounded ends"
    // three times. The list is grouped before it is rendered.
    const user = userEvent.setup()
    const interleaved: ListboxOption[] = [
      { value: 'a1', label: 'One', group: 'Alpha' },
      { value: 'b1', label: 'Two', group: 'Beta' },
      { value: 'a2', label: 'Three', group: 'Alpha' },
      { value: 'b2', label: 'Four', group: 'Beta' },
    ]
    render(
      <Listbox label="Grouped" options={interleaved} value="a1" onChange={() => {}} />,
    )
    await user.click(screen.getByRole('combobox', { name: 'Grouped' }))

    const box = screen.getByRole('listbox')
    expect(within(box).getAllByText('Alpha')).toHaveLength(1)
    expect(within(box).getAllByText('Beta')).toHaveLength(1)
    // and the options are reordered to sit under their heading
    const labels = within(box).getAllByRole('option').map((o) => o.textContent)
    expect(labels).toEqual(['One', 'Three', 'Two', 'Four'])
  })

  it('says the full name when closed, since there is no heading to lean on', async () => {
    const user = userEvent.setup()
    const options: ListboxOption[] = [
      { value: 'x', label: 'Seamless', selectedLabel: 'Rounded ends, seamless', group: 'Rounded ends' },
      { value: 'y', label: 'Seamless', selectedLabel: 'Rounded corners, seamless', group: 'Rounded corners' },
    ]
    function Two() {
      const [v, setV] = useState('x')
      return <Listbox label="Shape" options={options} value={v} onChange={setV} />
    }
    render(<Two />)
    const button = screen.getByRole('combobox', { name: 'Shape' })
    expect(button).toHaveTextContent('Rounded ends, seamless')
    await user.click(button)
    await user.click(within(screen.getByRole('listbox')).getAllByRole('option')[1])
    expect(button).toHaveTextContent('Rounded corners, seamless')
  })
})
