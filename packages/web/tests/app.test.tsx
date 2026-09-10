import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { FakeBackend, REF_PARAMS, noEventSource } from './harness'

let backend: FakeBackend

/** Render and wait until the restored parameters have reached the form. */
async function boot(props: any = {}) {
  const view = render(<App options={{ autoPreview: false, validateDebounceMs: 0, previewIdleMs: 0, ...(props.options ?? {}) }} />)
  await screen.findByRole('heading', { name: /leather tray mold/i })
  await waitFor(() => expect(screen.getByLabelText('Length')).toHaveValue(175))
  return view
}

/** Let the (zero-length) debounces and their promises settle. */
async function settleValidation() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5))
  })
}

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

describe('boot and form rendering', () => {
  it('renders groups and fields from the served schema', async () => {
    await boot()
    for (const title of ['Shape', 'Dimensions', 'Leather & fit', 'Mold', 'Features', 'Manufacturing', 'Advanced']) {
      expect(screen.getByRole('button', { name: new RegExp(title, 'i') })).toBeInTheDocument()
    }
    expect(screen.getByLabelText('Length')).toHaveValue(175)
    expect(screen.getByLabelText('Width')).toHaveValue(105)
    expect(screen.getByLabelText('Depth')).toHaveValue(25)
    expect(screen.getByLabelText('Thickness')).toHaveValue(3)
  })

  it('shows the number input and a slider, with the number authoritative', async () => {
    await boot()
    expect(screen.getByLabelText('Length')).toHaveAttribute('type', 'number')
    expect(screen.getByLabelText('Length slider')).toHaveAttribute('type', 'range')
  })

  it('renders derived values returned by the backend', async () => {
    await boot()
    await settleValidation()
    await waitFor(() => expect(screen.getByTestId('derived-forming_gap')).toHaveTextContent('3.000 mm'))
    expect(screen.getByTestId('derived-plate_length')).toHaveTextContent('235.0 mm')
  })

  it('reports an unreachable backend instead of rendering an empty form', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    render(<App options={{ autoPreview: false, validateDebounceMs: 0, previewIdleMs: 0 }} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the geometry service/i)
  })
})

describe('a value of zero', () => {
  it('is shown as 0, not as an empty box', async () => {
    /**
     * `value ?? value === 0 ? String(value) : ''` reads as the zero check it
     * was meant to be but is not one: ?? only falls through on null, so 0
     * reached the conditional as 0, which is falsy. Compression and clearance
     * are both 0 in the reference, so two fields shipped looking unset - and a
     * user who typed into one to "fill it in" got a value the API refuses.
     */
    await boot()
    expect(screen.getByLabelText('Compression')).toHaveValue(0)
    expect(screen.getByLabelText('Clearance')).toHaveValue(0)
  })
})

describe('validation', () => {
  it('validates on edit without building geometry', async () => {
    const user = userEvent.setup()
    await boot()
    await settleValidation()
    backend.validateCalls.length = 0

    await user.clear(screen.getByLabelText('Length'))
    await user.type(screen.getByLabelText('Length'), '200')
    await settleValidation()

    expect(backend.validateCalls.length).toBeGreaterThan(0)
    expect(backend.previewCalls).toHaveLength(0)
  })

  it('renders a diagnostic next to its field and blocks preview', async () => {
    backend.validateResponse = () => ({
      valid: false,
      diagnostics: [{ code: 'E-MOLD-040', severity: 'error', field: 'mold.cavity_plate_thickness',
                      message: 'less than the draw depth; the plug would protrude' }],
      derived: {}, params_hash: 'bad', schema_version: '2.0.0', model_version: '0.1.0',
    })
    await boot()
    await settleValidation()

    await waitFor(() => expect(screen.getAllByTestId('diag-E-MOLD-040').length).toBeGreaterThan(0))
    expect(screen.getByTestId('diagnostics-panel')).toHaveTextContent('E-MOLD-040')
    expect(screen.getByRole('button', { name: /update preview/i })).toBeDisabled()
    expect(screen.getByTestId('export-button')).toBeDisabled()
  })

  it('a warning does not block preview', async () => {
    backend.validateResponse = () => ({
      valid: true,
      diagnostics: [{ code: 'W-GAP-021', severity: 'warning', field: 'leather/fit', message: 'below FDM resolution' }],
      derived: {}, params_hash: 'warn', schema_version: '2.0.0', model_version: '0.1.0',
    })
    await boot()
    await settleValidation()
    await waitFor(() => expect(screen.getByTestId('diagnostics-panel')).toHaveTextContent('W-GAP-021'))
    expect(screen.getByRole('button', { name: /update preview/i })).toBeEnabled()
  })
})

describe('a parameter the backend will not accept', () => {
  /**
   * The report this suite came from: on a phone, "422 everywhere, nothing
   * works, errors at the bottom so I cannot see them and they are just 422s
   * with no action to take".
   *
   * Three separate faults met there. A value outside its bounds failed
   * `POST /api/validate` as well as the build, so the app had no diagnostics to
   * show at all. The one message it did have was the status code. And the two
   * places that render diagnostics - inline on the field, and the panel - are
   * both in the stacked column below the viewer, several screens down.
   */
  const outOfRange = [{
    code: 'E-RANGE', severity: 'error', field: 'tray.profile.length',
    message: 'must be greater than 0 (this is 0)',
  }]

  it('shows the reason and the field when the request itself is refused', async () => {
    backend.rejectWith = () => outOfRange
    await boot()
    await settleValidation()

    // Not "request failed (422)", and not a stale validation from before.
    const bar = await screen.findByTestId('blocking-error')
    expect(bar).toHaveTextContent('must be greater than 0')
    expect(bar).toHaveTextContent('length')
    expect(screen.getByRole('button', { name: /update preview/i })).toBeDisabled()
    expect(screen.getByTestId('export-button')).toBeDisabled()
  })

  it('puts it in the status bar, which is the only part on screen on a phone', async () => {
    backend.rejectWith = () => outOfRange
    await boot()
    await settleValidation()
    // The status bar floats over the viewer; the form and the diagnostics panel
    // are below it in the stacked layout.
    expect(within(screen.getByTestId('preview-status')).getByTestId('blocking-error')).toBeInTheDocument()
    expect(screen.getByTestId('preview-status')).toHaveTextContent(/cannot build these parameters/i)
  })

  it('takes you to the field it is about', async () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    backend.rejectWith = () => outOfRange
    await boot()
    await settleValidation()

    await userEvent.setup().click(await screen.findByRole('button', { name: /show me/i }))
    expect(scrollIntoView).toHaveBeenCalled()
    expect(document.activeElement).toBe(screen.getByLabelText('Length'))
  })

  it('recovers as soon as the parameters are acceptable again', async () => {
    let refuse = true
    backend.rejectWith = () => (refuse ? outOfRange : null)
    await boot()
    await settleValidation()
    expect(screen.getByTestId('blocking-error')).toBeInTheDocument()

    refuse = false
    await userEvent.setup().type(screen.getByLabelText('Length'), '5')
    await settleValidation()
    await waitFor(() => expect(screen.queryByTestId('blocking-error')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: /update preview/i })).toBeEnabled()
  })

  it('counts the rest rather than hiding them', async () => {
    backend.rejectWith = () => [...outOfRange, {
      code: 'E-RANGE', severity: 'error', field: 'mold.flange_width',
      message: 'must be at most 200 (this is 9999)',
    }]
    await boot()
    await settleValidation()
    expect(await screen.findByTestId('blocking-more')).toHaveTextContent('+1 more')
  })
})

describe('a combination the backend cannot build', () => {
  /**
   * The instruction this came from: "if there is an error that can be avoided
   * by disabling/changing some setting... do not show some root blend setting
   * can't work with some profile, just disallow it or handle gracefully."
   *
   * So an ellipse does not produce an error about the root blend. It turns the
   * root blend off as part of the same change, and the picker stops offering
   * the ones that cannot be built while the ellipse is selected.
   */
  const pickProfile = async (name: RegExp) => {
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Profile type'))
    await user.click(await screen.findByRole('option', { name }))
  }

  /** Options of one listbox. Two are open-able on this page, and `getAllByRole`
   *  would happily mix them. */
  const optionsOf = (label: string) => {
    // By role, not by label: an open listbox carries the same accessible name
    // as the button that controls it.
    const combobox = screen.getByRole('combobox', { name: label })
    const list = document.getElementById(combobox.getAttribute('aria-controls') ?? '')
    return list ? [...list.querySelectorAll('[role=option]')] : []
  }

  it('settles the conflicting setting instead of reporting it', async () => {
    await boot()
    await settleValidation()
    expect(screen.getByLabelText('Male root blend type')).toHaveTextContent(/rounded/i)

    await pickProfile(/^Ellipse/)
    await settleValidation()

    expect(screen.getByLabelText('Male root blend type')).toHaveTextContent(/none/i)
    expect(screen.queryByTestId('blocking-error')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /update preview/i })).toBeEnabled()
    expect(screen.getByTestId('export-button')).toBeEnabled()
  })

  it('never sends the combination to the backend at all', async () => {
    await boot()
    await settleValidation()
    backend.validateCalls.length = 0

    await pickProfile(/^Ellipse/)
    await settleValidation()

    expect(backend.validateCalls.length).toBeGreaterThan(0)
    for (const params of backend.validateCalls) {
      const profile = (params as any).tray.profile.kind
      const blend = (params as any).mold.male_root_blend.kind
      expect(profile === 'ellipse' && blend !== 'none').toBe(false)
    }
  })

  it('greys out what cannot be built, with the reason, and only while it applies', async () => {
    const user = userEvent.setup()
    await boot()
    await settleValidation()

    // Before: every treatment is offered.
    await user.click(screen.getByLabelText('Male root blend type'))
    const before = optionsOf('Male root blend type')
    expect(before.length).toBeGreaterThan(1)
    expect(before.filter((o) => o.getAttribute('aria-disabled') === 'true')).toHaveLength(0)
    await user.keyboard('{Escape}')

    await pickProfile(/^Ellipse/)
    await settleValidation()

    await user.click(screen.getByLabelText('Male root blend type'))
    const options = optionsOf('Male root blend type')
    expect(options).toHaveLength(before.length)
    const off = options.filter((o) => o.getAttribute('aria-disabled') === 'true')
    expect(off).toHaveLength(options.length - 1)
    expect(off[0]).toHaveTextContent(/not available on an ellipse/i)
    expect(options.find((o) => o.getAttribute('aria-disabled') !== 'true')).toHaveTextContent(/none/i)
  })

  it('applies to a restored design too, not only to a click', async () => {
    // A shared link can carry any pair; it must not open into a broken state.
    const ellipse = structuredClone(REF_PARAMS) as any
    ellipse.tray.profile = { kind: 'ellipse', length: 175, width: 105 }
    ellipse.mold.male_root_blend = { kind: 'circular_fillet', radius: 1.2 }
    window.localStorage.setItem('traymold.design.v1', JSON.stringify(ellipse))

    await boot()
    await settleValidation()
    expect(screen.getByLabelText('Male root blend type')).toHaveTextContent(/none/i)
    expect(screen.queryByTestId('blocking-error')).not.toBeInTheDocument()
  })
})

describe('unsupported and experimental parameters', () => {
  it('offers the outer datum but disables it, with the reason visible', async () => {
    await boot()
    await userEvent.setup().click(
      screen.getByRole('button', { name: /advanced/i }),
    )
    const datum = screen.getByLabelText('Datum') as HTMLSelectElement
    const outer = within(datum).getByRole('option', { name: /outer/i }) as HTMLOptionElement
    expect(outer).toBeDisabled()
    expect(screen.getByText(/planned but not implemented/i)).toBeInTheDocument()
  })

  it('gates draft behind the experimental switch', async () => {
    const user = userEvent.setup()
    await boot()
    await user.click(screen.getByRole('button', { name: /advanced/i }))

    expect(screen.getByTestId('experimental-tray.draft_angle')).toHaveTextContent(/experimental/i)
    expect(screen.getByTestId('experimental-tray.draft_angle')).toHaveTextContent(/cos\(draft angle\)/i)
    expect(screen.getByLabelText('Draft Angle')).toBeDisabled()

    await user.click(screen.getByLabelText('Enable experimental parameters'))
    expect(screen.getByLabelText('Draft Angle')).toBeEnabled()
  })
})

describe('usage counter', () => {
  it('shows the public number when the endpoint returns one', async () => {
    backend.stats = { custom_molds_generated: 1284, unique_designs_downloaded: 900,
                      total_artifact_downloads: 2100 }
    await boot()
    await waitFor(() => expect(screen.getByTestId('usage-counter')).toBeInTheDocument())
    // Formatted, and worded for what the metric actually measures.
    expect(screen.getByTestId('usage-counter')).toHaveTextContent('1,284 custom molds generated')
  })

  it('says "mold" rather than "molds" when there is exactly one', async () => {
    backend.stats = { custom_molds_generated: 1, unique_designs_downloaded: 1,
                      total_artifact_downloads: 3 }
    await boot()
    await waitFor(() => expect(screen.getByTestId('usage-counter')).toBeInTheDocument())
    expect(screen.getByTestId('usage-counter')).toHaveTextContent('1 custom mold generated')
  })

  it('hides itself when the stats endpoint fails', async () => {
    backend.statsError = true
    await boot()
    await act(async () => { await new Promise((r) => setTimeout(r, 150)) })
    // Absent, not an error message and not a zero.
    expect(screen.queryByTestId('usage-counter')).not.toBeInTheDocument()
    expect(screen.queryByText(/custom molds/i)).not.toBeInTheDocument()
  })

  it('hides itself when the count is zero', async () => {
    backend.stats = { custom_molds_generated: 0, unique_designs_downloaded: 0,
                      total_artifact_downloads: 0 }
    await boot()
    await act(async () => { await new Promise((r) => setTimeout(r, 150)) })
    expect(screen.queryByTestId('usage-counter')).not.toBeInTheDocument()
  })
})
