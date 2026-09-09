import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, api } from './api/client'
import type { Json, Preset, SchemaResponse } from './api/types'
import { SchemaForm } from './form/SchemaForm'
import { DerivedPanel } from './panels/DerivedPanel'
import { DiagnosticsPanel } from './panels/DiagnosticsPanel'
import { ExportPanel } from './panels/ExportPanel'
import { PreviewStatus } from './panels/PreviewStatus'
import { ViewerControls } from './panels/ViewerControls'
import { useDesign, type DesignOptions } from './state/useDesign'
import { restoreDesign, shareUrl } from './state/urlState'
import { Viewer, type PartMode, type ViewMode } from './viewer/Viewer'

/** The preset a first-time visitor lands on. */
const DEFAULT_PRESET = 'ref-4x7'

export function App({ options }: { options?: DesignOptions } = {}) {
  const [schema, setSchema] = useState<SchemaResponse | null>(null)
  const [presets, setPresets] = useState<Preset[]>([])
  const [bootError, setBootError] = useState<string | null>(null)
  const [initial, setInitial] = useState<Json | null>(null)
  const [source, setSource] = useState<'url' | 'local' | 'default'>('default')

  const [design, actions] = useDesign(initial, options)

  const [partMode, setPartMode] = useState<PartMode>('both')
  const [viewMode, setViewMode] = useState<ViewMode>('assembled')
  // Kept as the viewer's input, no longer as separate controls: the Part
  // selector already expresses every state these could reach.
  const [showMale] = useState(true)
  const [showFemale] = useState(true)
  const [resetToken, setResetToken] = useState(0)
  const [shared, setShared] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [schemaResponse, presetList] = await Promise.all([api.schema(), api.presets()])
        if (cancelled) return
        setSchema(schemaResponse)
        setPresets(presetList)
        const fallback =
          presetList.find((p) => p.name === DEFAULT_PRESET)?.params ?? schemaResponse.defaults
        const restored = await restoreDesign(fallback)
        if (cancelled) return
        setInitial(restored.params)
        setSource(restored.source)
      } catch (error) {
        if (!cancelled) setBootError((error as ApiError).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const applyPreset = useCallback(
    (name: string) => {
      const preset = presets.find((p) => p.name === name)
      if (preset) {
        actions.replaceParams(structuredClone(preset.params))
        setSource('default')
      }
    },
    [presets, actions],
  )

  const share = useCallback(async () => {
    const url = await shareUrl(design.params)
    setShared(url)
    try {
      await navigator.clipboard?.writeText(url)
    } catch {
      /* clipboard is unavailable outside a secure context */
    }
  }, [design.params])

  const stale = design.previewState === 'dirty'
  const blocked = design.errors.length > 0

  const presetOptions = useMemo(
    () => presets.filter((p) => p.name === DEFAULT_PRESET || p.name.startsWith('ref-')),
    [presets],
  )

  if (bootError) {
    return (
      <div className="boot-error" role="alert">
        <h1>Cannot reach the geometry service</h1>
        <p>{bootError}</p>
        <p className="hint">
          Set the backend with <code>?api=https://your-api</code>, or edit
          <code> window.__TRAYMOLD_API_BASE__</code> in the deployed index.html.
        </p>
      </div>
    )
  }

  if (!schema || !initial) {
    return (
      <div className="booting" role="status">
        Loading parameter schema…
      </div>
    )
  }

  return (
    <div className="app">
      <header>
        <div className="brand">
          <h1>Leather Tray Mold</h1>
          <span className="kicker">Generator</span>
        </div>
        <span className="header-rule" aria-hidden="true" />
        <label className="preset">
          <span className="label" aria-hidden="true">Preset</span>
          <select aria-label="Preset" defaultValue="" onChange={(e) => e.target.value && applyPreset(e.target.value)}>
            <option value="">{source === 'url' ? 'From link' : source === 'local' ? 'Your last design' : 'Choose…'}</option>
            {presetOptions.map((preset) => (
              <option key={preset.name} value={preset.name}>
                {preset.title}
              </option>
            ))}
          </select>
        </label>
        <span className="spacer" />
        <label className="checkbox experimental">
          <input
            type="checkbox"
            aria-label="Enable experimental parameters"
            checked={design.allowExperimental}
            onChange={(e) => actions.setAllowExperimental(e.target.checked)}
          />
          <span>Experimental parameters</span>
        </label>
        <button type="button" onClick={share}>
          Copy link
        </button>
      </header>

      {shared && (
        <p className="share-note" data-testid="share-url">
          {shared}
        </p>
      )}

      <aside className="params">
        <SchemaForm
          jsonSchema={schema.json_schema}
          hints={schema.ui_hints}
          value={design.params}
          diagnostics={design.diagnostics}
          allowExperimental={design.allowExperimental}
          onChange={(next) => actions.setParams(next)}
          onCommit={actions.commit}
        />
      </aside>

      {/* Status and controls float over the viewport rather than boxing it in
          above and below, so the model is the largest thing on the page. */}
      <main className="stage">
        <div className={`viewport ${stale ? 'stale' : ''}`} data-testid="viewport">
        <PreviewStatus
          state={design.previewState}
          job={design.previewJob}
          validating={design.validating}
          transportError={design.transportError}
          onGenerate={actions.generatePreview}
          onCancel={actions.cancelPreview}
          // Nothing to build when the preview already matches the parameters:
          // the click would be a no-op, so say so rather than letting it look
          // like a button that does nothing.
          canGenerate={!blocked && design.previewState !== 'clean'}
        />
          {design.previewUrl ? (
            <Viewer
              url={design.previewUrl}
              partMode={partMode}
              viewMode={viewMode}
              showMale={showMale}
              showFemale={showFemale}
              stale={stale}
              resetToken={resetToken}
            />
          ) : (
            <div className="placeholder" data-testid="viewer-placeholder">
              {design.previewState === 'generating' ? (
                <>
                  <span className="headline">Building geometry…</span>
                  <span className="sub">The mold is being solved from your parameters.</span>
                </>
              ) : design.previewState === 'failed' ? (
                <>
                  <span className="headline">The build failed</span>
                  <span className="sub">Adjust the parameters and try again.</span>
                </>
              ) : (
                <>
                  <span className="headline">No preview yet</span>
                  <span className="sub">Set the tray dimensions on the left, then press Update preview.</span>
                </>
              )}
            </div>
          )}
          {stale && <div className="stale-badge">Preview out of date</div>}
          <ViewerControls
            partMode={partMode}
            setPartMode={setPartMode}
            viewMode={viewMode}
            setViewMode={setViewMode}
            onReset={() => setResetToken((t) => t + 1)}
          />
        </div>
      </main>

      {/* Export first. Someone arriving to make a tray wants the files; the
          derived figures are how you check the design, not why you came. */}
      <aside className="info">
        <DiagnosticsPanel diagnostics={design.diagnostics} transportError={design.transportError} />
        <ExportPanel params={design.params} disabled={blocked} allowExperimental={design.allowExperimental} />
        <details className="details-block" open>
          <summary>
            <span className="chevron" aria-hidden="true">▾</span> Derived
          </summary>
          <DerivedPanel validation={design.validation} hints={schema.ui_hints} job={design.previewJob} />
        </details>
        <p className="version">
          schema {schema.schema_version} · model {schema.model_version}
        </p>
      </aside>
    </div>
  )
}
