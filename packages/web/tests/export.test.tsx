import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { App } from '../src/App'
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

describe('the formats on offer', () => {
  it('offers 3MF with nothing switched on first', async () => {
    await boot()
    expect(screen.getByLabelText('STEP')).toBeInTheDocument()
    expect(screen.getByLabelText('STL')).toBeInTheDocument()
    expect(screen.getByLabelText('3MF')).toBeInTheDocument()
  })

  it('marks it experimental, and only it', async () => {
    await boot()
    const marked = (label: string) =>
      screen.getByLabelText(label).closest('label')!.textContent?.toLowerCase() ?? ''
    expect(marked('3MF')).toContain('experimental')
    expect(marked('STEP')).not.toContain('experimental')
    expect(marked('STL')).not.toContain('experimental')
  })

  it('is off until it is asked for, so the usual export is unchanged', async () => {
    await boot()
    expect(screen.getByLabelText('3MF')).not.toBeChecked()
    expect(screen.getByLabelText('STEP')).toBeChecked()
    expect(screen.getByLabelText('STL')).toBeChecked()

    await userEvent.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(backend.exportCalls).toHaveLength(1))
    expect(backend.exportCalls[0].formats).toEqual(['step', 'stl'])
  })

  it('says what the format is for once it is ticked', async () => {
    await boot()
    expect(screen.queryByTestId('format-3mf-note')).toBeNull()
    await userEvent.click(screen.getByLabelText('3MF'))
    expect(screen.getByTestId('format-3mf-note')).toHaveTextContent(/print plan/i)
  })

  it('sends the format when it has been ticked', async () => {
    await boot()
    await userEvent.click(screen.getByLabelText('3MF'))
    await userEvent.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(backend.exportCalls).toHaveLength(1))
    expect(backend.exportCalls[0].formats).toEqual(['step', 'stl', '3mf'])
  })
})

describe('the material ledger', () => {
  async function exportWithLedger(ledger: any) {
    backend.exportResponse = (_body, id) =>
      backend.job({ id, kind: 'export', print_ledger: ledger, artifacts: {} })
    await boot()
    await userEvent.click(screen.getByLabelText('3MF'))
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

  it('shows no number for the option that writes no settings, and says why', async () => {
    await exportWithLedger(backend.ledger())
    const row = (await screen.findByText('slicer')).closest('tr')!
    expect(row).toHaveTextContent('—')
    // the reason is prose, so it sits under the row rather than in the column
    // where a percentage would have been
    expect(row).not.toHaveTextContent(/your own preset/i)
    expect(screen.getByTestId('print-ledger')).toHaveTextContent(/your own preset/i)
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
