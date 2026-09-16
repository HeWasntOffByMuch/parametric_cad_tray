import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { App } from '../src/App'
import { enabled, isFlagsChord, readFlags, writeFlags } from '../src/flags'
import { FakeBackend, noEventSource } from './harness'

let backend: FakeBackend

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  backend = new FakeBackend()
  backend.install()
  noEventSource()
})

async function boot(options: any = {}) {
  const view = render(<App options={{ autoPreview: false, validateDebounceMs: 0, previewIdleMs: 0, ...options }} />)
  await waitFor(() => expect(screen.getByLabelText('Length')).toHaveValue(175))
  return view
}

describe('reading and writing switches', () => {
  it('takes them from the query string and remembers them', () => {
    window.history.replaceState(null, '', '/?flags=3mf')
    expect(readFlags()).toEqual(new Set(['3mf']))
    window.history.replaceState(null, '', '/')
    expect(readFlags()).toEqual(new Set(['3mf']))
  })

  it('treats an empty query value as a deliberate none, which is the way back out', () => {
    writeFlags(['3mf'])
    window.history.replaceState(null, '', '/?flags=')
    expect(readFlags()).toEqual(new Set())
    window.history.replaceState(null, '', '/')
    expect(readFlags()).toEqual(new Set())
  })

  it('ignores blanks and whitespace in a hand-typed list', () => {
    window.history.replaceState(null, '', '/?flags=%203mf%20,,')
    expect(readFlags()).toEqual(new Set(['3mf']))
  })

  it('survives a browser that refuses storage, as a private window does', () => {
    const real = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem() { throw new Error('denied') },
        setItem() { throw new Error('denied') },
      },
    })
    try {
      expect(readFlags()).toEqual(new Set())
      expect(() => writeFlags(['3mf'])).not.toThrow()
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real })
    }
  })
})

describe('a switch never grants anything on its own', () => {
  it('needs the deployment to offer the capability as well', () => {
    expect(enabled(new Set(['3mf']), { '3mf': true }, '3mf')).toBe(true)
    expect(enabled(new Set(['3mf']), { '3mf': false }, '3mf')).toBe(false)
    expect(enabled(new Set(), { '3mf': true }, '3mf')).toBe(false)
    expect(enabled(new Set(['3mf']), undefined, '3mf')).toBe(false)
  })
})

describe('the chord', () => {
  it('is ctrl or cmd, shift and a full stop, and nothing else', () => {
    const chord = (init: Partial<KeyboardEvent>) => isFlagsChord(new KeyboardEvent('keydown', init as any))
    expect(chord({ ctrlKey: true, shiftKey: true, key: '.' })).toBe(true)
    expect(chord({ metaKey: true, shiftKey: true, key: '>' })).toBe(true)
    expect(chord({ ctrlKey: true, key: '.' })).toBe(false)
    expect(chord({ shiftKey: true, key: '.' })).toBe(false)
    expect(chord({ ctrlKey: true, shiftKey: true, key: 'p' })).toBe(false)
  })
})

describe('the panel', () => {
  it('is not on the page until the chord is pressed', async () => {
    await boot()
    expect(screen.queryByTestId('flags-panel')).toBeNull()
    await userEvent.keyboard('{Control>}{Shift>}.{/Shift}{/Control}')
    expect(await screen.findByTestId('flags-panel')).toBeInTheDocument()
  })

  it('says when the deployment has the capability turned off', async () => {
    backend.features = { '3mf': false }
    await boot()
    await userEvent.keyboard('{Control>}{Shift>}.{/Shift}{/Control}')
    expect(screen.getByTestId('flag-server-3mf')).toHaveTextContent(/turned off/i)
  })

  it('says when it is offered', async () => {
    backend.features = { '3mf': true }
    await boot()
    await userEvent.keyboard('{Control>}{Shift>}.{/Shift}{/Control}')
    expect(screen.getByTestId('flag-server-3mf')).toHaveTextContent(/offers it/i)
  })
})

describe('what a switch reveals', () => {
  it('offers 3MF only once both the browser and the server say yes', async () => {
    backend.features = { '3mf': true }
    await boot()
    expect(screen.queryByLabelText('3MF')).toBeNull()

    await userEvent.keyboard('{Control>}{Shift>}.{/Shift}{/Control}')
    await userEvent.click(screen.getByLabelText('3mf'))
    expect(await screen.findByLabelText('3MF')).toBeInTheDocument()
  })

  it('does not offer it when the server has it off, however the switch is set', async () => {
    backend.features = { '3mf': false }
    await boot()
    await userEvent.keyboard('{Control>}{Shift>}.{/Shift}{/Control}')
    await userEvent.click(screen.getByLabelText('3mf'))
    expect(screen.queryByLabelText('3MF')).toBeNull()
  })

  it('sends the format when it has been ticked', async () => {
    backend.features = { '3mf': true }
    window.history.replaceState(null, '', '/?flags=3mf')
    await boot()
    await userEvent.click(await screen.findByLabelText('3MF'))
    await userEvent.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(backend.exportCalls).toHaveLength(1))
    expect(backend.exportCalls[0].formats).toEqual(['step', 'stl', '3mf'])
  })
})

describe('the material ledger', () => {
  async function exportWithLedger(ledger: any) {
    backend.features = { '3mf': true }
    window.history.replaceState(null, '', '/?flags=3mf')
    backend.exportResponse = (_body, id) =>
      backend.job({ id, kind: 'export', print_ledger: ledger, artifacts: {} })
    await boot()
    await userEvent.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(backend.exportCalls).toHaveLength(1))
  }

  it('prices every option against what someone is printing today', async () => {
    await exportWithLedger(backend.ledger())
    const table = await screen.findByTestId('print-ledger')
    expect(table).toHaveTextContent('448 g')
    expect(table).toHaveTextContent('-44%')
    expect(table).toHaveTextContent('796 g')
  })

  it('marks the option that is actually in the file', async () => {
    await exportWithLedger(backend.ledger())
    const row = (await screen.findByText('lean')).closest('tr')!
    expect(row.className).toContain('selected')
    expect(row).toHaveTextContent(/in this file/i)
  })

  it('shows no number for the option that writes no settings', async () => {
    await exportWithLedger(backend.ledger())
    const row = (await screen.findByText('slicer')).closest('tr')!
    expect(row).toHaveTextContent('—')
    expect(row).toHaveTextContent(/your own preset/i)
  })

  it('says where the density goes back in, and why', async () => {
    await exportWithLedger(backend.ledger())
    const table = await screen.findByTestId('print-ledger')
    await userEvent.click(within(table).getByText(/where the density goes back in/i))
    expect(table).toHaveTextContent(/clamp-bearing-0/)
    expect(table).toHaveTextContent(/concentrated load/)
  })

  it('is absent from an export that did not write a 3MF', async () => {
    await exportWithLedger({})
    await waitFor(() => expect(screen.getByTestId('export-panel')).toBeInTheDocument())
    expect(screen.queryByTestId('print-ledger')).toBeNull()
  })
})
