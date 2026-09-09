import '@testing-library/jest-dom/vitest'
import { createElement } from 'react'
import { vi } from 'vitest'

// jsdom has no WebGL, so the R3F canvas is replaced everywhere. The viewer's own
// rules are pure functions and are tested directly in viewer.test.ts.
vi.mock('../src/viewer/Viewer', async () => {
  const actual = await vi.importActual<any>('../src/viewer/Viewer')
  return {
    ...actual,
    Viewer: (props: any) =>
      createElement('div', {
        'data-testid': 'viewer-canvas',
        'data-url': props.url,
        'data-part-mode': props.partMode,
        'data-view-mode': props.viewMode,
        'data-stale': String(props.stale),
      }),
  }
})

if (!('structuredClone' in globalThis)) {
  ;(globalThis as any).structuredClone = (value: unknown) => JSON.parse(JSON.stringify(value))
}
