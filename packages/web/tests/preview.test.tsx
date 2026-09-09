import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { FakeBackend, REF_PARAMS, noEventSource } from './harness'
import { encodeDesign } from '../src/state/urlState'

let backend: FakeBackend

/** Render and wait until the restored parameters have reached the form. */
async function boot(props: { options?: any; expectLength?: number } = {}) {
  const view = render(
    <App options={{ autoPreview: false, validateDebounceMs: 0, previewIdleMs: 0, ...(props.options ?? {}) }} />,
  )
  await screen.findByRole('heading', { name: /leather tray mold/i })
  await waitFor(() => expect(screen.getByLabelText('Length')).toHaveValue(props.expectLength ?? 175))
  return view
}

/** Let pending debounces, fetches and effects settle. */
async function tick(ms = 10) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms))
  })
}

const status = () => screen.getByTestId('preview-status').dataset.state

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  backend = new FakeBackend()
  backend.install()
  noEventSource()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('preview lifecycle', () => {
  it('starts with no preview and does not build until asked', async () => {
    await boot()
    expect(status()).toBe('empty')
    expect(screen.getByTestId('viewer-placeholder')).toHaveTextContent(/no preview yet/i)
    await tick(2000)
    expect(backend.previewCalls).toHaveLength(0)
  })

  it('completes a preview and shows the GLB', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))
    expect(screen.getByTestId('viewer-canvas')).toHaveAttribute('data-url', '/api/artifacts/key/preview.glb')
    expect(screen.getByTestId('preview-status')).toHaveTextContent(/up to date/i)
  })

  it('shows a cached preview immediately', async () => {
    backend.previewResponse = (params, id) =>
      backend.job({ id, state: 'complete', cached: true, status: 'served from cache',
                    params_hash: backend.hashOf(params), artifacts: backend.glbArtifact() })
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))
    expect(screen.getByTestId('preview-status')).toHaveTextContent(/served from cache/i)
  })

  it('reports an asynchronous build and settles when it finishes', async () => {
    backend.previewResponse = (params, id) =>
      backend.job({ id, state: 'running', status: 'building geometry', params_hash: backend.hashOf(params) })
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('generating'))
    expect(screen.getByTestId('viewer-placeholder')).toHaveTextContent(/building geometry/i)

    const id = backend.jobs.keys().next().value as string
    backend.settle(id, { state: 'complete', status: 'done', artifacts: backend.glbArtifact() })
    await tick(600)
    await waitFor(() => expect(status()).toBe('clean'))
  })

  it('surfaces a failed build without blanking a previous preview', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))

    backend.previewResponse = (params, id) =>
      backend.job({ id, state: 'failed', status: 'failed', params_hash: backend.hashOf(params),
                    error: { kind: 'geometry_build_error', message: 'the kernel could not build this', diagnostics: [] } })
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '210')
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))

    await waitFor(() => expect(status()).toBe('failed'))
    expect(screen.getByTestId('preview-status')).toHaveTextContent(/the kernel could not build this/i)
    // the previous geometry stays on screen
    expect(screen.getByTestId('viewer-canvas')).toBeInTheDocument()
  })

  it('marks the preview out of date when parameters change, without blanking it', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))

    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '190')
    await tick()

    await waitFor(() => expect(status()).toBe('dirty'))
    expect(screen.getByTestId('preview-status')).toHaveTextContent(/preview out of date/i)
    expect(screen.getByText(/preview out of date/i, { selector: '.stale-badge' })).toBeInTheDocument()
    expect(screen.getByTestId('viewer-canvas')).toBeInTheDocument()
    expect(screen.getByTestId('viewer-canvas')).toHaveAttribute('data-stale', 'true')
  })

  it('coalesces typing into one build rather than one per keystroke', async () => {
    const user = userEvent.setup()
    await boot({ options: { autoPreview: true, previewIdleMs: 120 } })
    await tick()
    backend.previewCalls.length = 0

    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '250')
    // still inside the idle window: nothing has been built yet
    expect(backend.previewCalls).toHaveLength(0)

    await waitFor(() => expect(backend.previewCalls).toHaveLength(1), { timeout: 2000 })
    expect(backend.previewCalls.at(-1)!.tray.profile.length).toBe(250)
  })

  it('does not rebuild geometry that is already on screen', async () => {
    const user = userEvent.setup()
    await boot({ options: { autoPreview: true, previewIdleMs: 120 } })
    await tick()
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '250')
    await waitFor(() => expect(backend.previewCalls).toHaveLength(1), { timeout: 2000 })
    await waitFor(() => expect(screen.getByTestId('preview-status')).toHaveAttribute('data-state', 'clean'))

    // Asking again for exactly what is displayed. The server would answer from
    // cache in milliseconds, which is why this was easy to miss - but it is
    // still a round trip and a rate-limit slot spent on a byte-identical GLB.
    await act(async () => {
      screen.getByRole('button', { name: 'Update preview' }).click()
    })
    await tick(300)
    expect(backend.previewCalls).toHaveLength(1)
  })

  it('sends one build when a click both blurs a field and asks for a preview', async () => {
    const user = userEvent.setup()
    await boot({ options: { autoPreview: true, previewIdleMs: 120 } })
    await tick()
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '250')
    await waitFor(() => expect(backend.previewCalls).toHaveLength(1), { timeout: 2000 })
    await waitFor(() => expect(screen.getByTestId('preview-status')).toHaveAttribute('data-state', 'clean'))
    backend.previewCalls.length = 0

    // Editing and then clicking straight away used to send two: the click blurs
    // the input, which commits and schedules an immediate build, and then the
    // button's own handler starts a second one that cancels and replaces it.
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '260')
    await act(async () => {
      screen.getByRole('button', { name: 'Update preview' }).click()
    })
    await waitFor(() => expect(backend.previewCalls.length).toBeGreaterThan(0), { timeout: 2000 })
    await tick(400)
    expect(backend.previewCalls).toHaveLength(1)
    expect(backend.previewCalls.at(-1)!.tray.profile.length).toBe(260)
  })

  it('still builds when the parameters really have changed', async () => {
    const user = userEvent.setup()
    await boot({ options: { autoPreview: true, previewIdleMs: 120 } })
    await tick()
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '250')
    await waitFor(() => expect(backend.previewCalls).toHaveLength(1), { timeout: 2000 })
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '251')
    await waitFor(() => expect(backend.previewCalls).toHaveLength(2), { timeout: 2000 })
    expect(backend.previewCalls.at(-1)!.tray.profile.length).toBe(251)
  })

  it('does not start a build while a slider is dragged, only on release', async () => {
    await boot({ options: { autoPreview: true } })
    await tick()
    const slider = screen.getByLabelText('Length slider')
    for (const value of [180, 185, 190]) {
      await act(async () => {
        slider.dispatchEvent(new Event('input', { bubbles: true }))
        ;(slider as HTMLInputElement).value = String(value)
      })
    }
    await tick(300)
    expect(backend.previewCalls).toHaveLength(0)
  })
})

describe('stale job handling', () => {
  it('never lets an older completed job replace a newer preview', async () => {
    // Job A is for the original parameters, job B for the edited ones. A finishes
    // last and must be ignored, because its hash is no longer the current one.
    const user = userEvent.setup()
    backend.previewResponse = (params, id) =>
      backend.job({ id, state: 'running', status: 'building geometry', params_hash: backend.hashOf(params) })
    await boot({ options: { autoPreview: true, previewIdleMs: 80 } })
    await tick()

    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('generating'))
    const staleId = backend.jobs.keys().next().value as string

    // editing supersedes it; the idle trigger starts the newer build
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '250')
    await waitFor(() => expect(backend.previewCalls.length).toBeGreaterThan(1), { timeout: 3000 })

    // the superseded job is cancelled rather than left to burn CPU
    expect(backend.cancelled).toContain(staleId)

    // and even if it completes anyway, it must not become the displayed preview
    backend.settle(staleId, {
      state: 'complete', status: 'done',
      artifacts: { 'preview.glb': { ...backend.glbArtifact()['preview.glb'], url: '/api/artifacts/STALE/preview.glb' } },
    })
    await tick(800)
    const canvas = screen.queryByTestId('viewer-canvas')
    expect(canvas?.getAttribute('data-url') ?? '').not.toContain('STALE')
  })

  it('a cancelled job leaves the previous preview in place', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))

    backend.previewResponse = (params, id) =>
      backend.job({ id, state: 'running', status: 'building geometry', params_hash: backend.hashOf(params) })
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '230')
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('generating'))

    await user.click(screen.getByRole('button', { name: /cancel/i }))
    await waitFor(() => expect(status()).toBe('dirty'))
    expect(screen.getByTestId('viewer-canvas')).toBeInTheDocument()
  })
})

describe('presets and shared links', () => {
  it('applying a preset replaces the whole document and revalidates', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '300')
    await tick()
    expect(screen.getByLabelText('Length')).toHaveValue(300)

    backend.validateCalls.length = 0
    await user.selectOptions(screen.getByLabelText('Preset'), 'ref-4x7-step')
    await tick()

    await waitFor(() => expect(screen.getByLabelText('Length')).toHaveValue(175))
    expect(backend.validateCalls.length).toBeGreaterThan(0)
    // the STEP revision has no clamp holes; a partial merge would have kept them
    expect(backend.validateCalls.at(-1)!.features.clamp_holes.enabled).toBe(false)
  })

  it('restores a design from the URL in preference to localStorage', async () => {
    const local = structuredClone(REF_PARAMS) as any
    local.tray.profile.length = 111
    window.localStorage.setItem('traymold.design.v1', JSON.stringify(local))

    const shared = structuredClone(REF_PARAMS) as any
    shared.tray.profile.length = 222
    window.history.replaceState(null, '', `/#${await encodeDesign(shared)}`)

    await boot({ expectLength: 222 })
    expect(screen.getByLabelText('Length')).toHaveValue(222)
  })

  it('falls back to localStorage when there is no link', async () => {
    const local = structuredClone(REF_PARAMS) as any
    local.tray.profile.length = 111
    window.localStorage.setItem('traymold.design.v1', JSON.stringify(local))
    await boot({ expectLength: 111 })
  })

  it('writes the design into the URL so it can be shared', async () => {
    const user = userEvent.setup()
    await boot()
    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '188')
    await tick()
    await waitFor(() => expect(window.location.hash.length).toBeGreaterThan(4))
    const { decodeDesign } = await import('../src/state/urlState')
    const decoded = await decodeDesign(window.location.hash.slice(1))
    expect(decoded!.tray.profile.length).toBe(188)
  })
})

describe('export', () => {
  it('exports without regenerating the preview and lists artifacts when done', async () => {
    const user = userEvent.setup()
    await boot()
    await tick()
    await user.click(screen.getByRole('button', { name: /update preview/i }))
    await waitFor(() => expect(status()).toBe('clean'))
    const previewCount = backend.previewCalls.length

    await user.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(screen.getByTestId('export-artifacts')).toBeInTheDocument())

    expect(backend.previewCalls).toHaveLength(previewCount)
    const links = screen.getByTestId('export-artifacts')
    expect(links).toHaveTextContent('male.step')
    expect(links).toHaveTextContent('male.stl')
    expect(links).toHaveTextContent('bundle.zip')
    expect(status()).toBe('clean')
  })

  it('sends the chosen parts and formats', async () => {
    const user = userEvent.setup()
    await boot()
    await user.selectOptions(screen.getByLabelText('Export parts'), 'female')
    await user.click(screen.getByLabelText('STL'))
    await user.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(backend.exportCalls).toHaveLength(1))
    expect(backend.exportCalls[0].parts).toEqual({ male: false, female: true })
    expect(backend.exportCalls[0].formats).toEqual(['step'])
  })

  it('reports a failed export', async () => {
    backend.exportResponse = (_body, id) =>
      backend.job({ id, kind: 'export', state: 'failed',
                    error: { kind: 'timeout', message: 'the build exceeded its time budget', diagnostics: [] } })
    const user = userEvent.setup()
    await boot()
    await user.click(screen.getByTestId('export-button'))
    await waitFor(() => expect(screen.getByTestId('export-error')).toHaveTextContent(/time budget/i))
    expect(screen.queryByTestId('export-artifacts')).not.toBeInTheDocument()
  })
})
