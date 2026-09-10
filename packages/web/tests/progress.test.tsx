import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PreviewStatus } from '../src/panels/PreviewStatus'
import type { Job } from '../src/api/types'

const job = (overrides: Partial<Job> = {}): Job =>
  ({
    id: 'j1', state: 'running', kind: 'preview', progress: null, stage: null,
    status: null, params_hash: null, cache_key: 'k', cached: false, artifacts: {},
    bundle_url: null, diagnostics: [], derived: {}, volumes_cm3: {}, timings: {},
    error: null, ...overrides,
  }) as Job

const show = (props: Partial<Parameters<typeof PreviewStatus>[0]>) =>
  render(
    <PreviewStatus
      state="generating"
      job={null}
      validating={false}
      transportError={null}
      errors={[]}
      onReveal={() => {}}
      onGenerate={() => {}}
      onCancel={() => {}}
      canGenerate={false}
      {...props}
    />,
  )

describe('build progress', () => {
  it('draws nothing until the worker has reported a stage', () => {
    show({ job: job({ progress: null }) })
    // A bar at zero is a promise; an animating one is a lie. Neither is drawn.
    expect(screen.queryByTestId('progress-bar')).not.toBeInTheDocument()
    expect(screen.queryByTestId('progress-percent')).not.toBeInTheDocument()
  })

  it('shows the real fraction and stage label once one lands', () => {
    show({ job: job({ progress: 0.6348, stage: 'male_floor_blend', status: 'blending the tray floor' }) })
    const bar = screen.getByTestId('progress-bar')
    expect(bar).toHaveAttribute('aria-valuenow', '63')
    expect(screen.getByTestId('progress-percent')).toHaveTextContent('63%')
    expect(screen.getByTestId('preview-status')).toHaveTextContent('blending the tray floor')
  })

  it('scales the fill by the fraction, not by a width that would reflow the row', () => {
    show({ job: job({ progress: 0.25, stage: 'male_root_blend' }) })
    const fill = screen.getByTestId('progress-bar').firstElementChild as HTMLElement
    expect(fill.style.transform).toBe('scaleX(0.25)')
  })

  it('disappears when the build is no longer running', () => {
    show({ state: 'clean', job: job({ state: 'complete', progress: 1.0, stage: 'write' }) })
    expect(screen.queryByTestId('progress-bar')).not.toBeInTheDocument()
  })

  it('is a real progressbar to assistive technology', () => {
    show({ job: job({ progress: 0.5, stage: 'female_solid' }) })
    const bar = screen.getByRole('progressbar', { name: /build progress/i })
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })
})
