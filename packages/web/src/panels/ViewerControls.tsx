import type { PartMode, ViewMode } from '../viewer/Viewer'

export function ViewerControls({
  partMode,
  setPartMode,
  viewMode,
  setViewMode,
  showMale,
  setShowMale,
  showFemale,
  setShowFemale,
  onReset,
}: {
  partMode: PartMode
  setPartMode: (v: PartMode) => void
  viewMode: ViewMode
  setViewMode: (v: ViewMode) => void
  showMale: boolean
  setShowMale: (v: boolean) => void
  showFemale: boolean
  setShowFemale: (v: boolean) => void
  onReset: () => void
}) {
  return (
    <div className="viewer-controls" data-testid="viewer-controls">
      <div className="segmented" role="group" aria-label="Parts shown">
        {(['both', 'male', 'female'] as PartMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={partMode === mode}
            className={partMode === mode ? 'active' : undefined}
            onClick={() => setPartMode(mode)}
          >
            {mode}
          </button>
        ))}
      </div>
      <div className="segmented" role="group" aria-label="View mode">
        {(['assembled', 'exploded'] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            aria-pressed={viewMode === mode}
            className={viewMode === mode ? 'active' : undefined}
            onClick={() => setViewMode(mode)}
          >
            {mode}
          </button>
        ))}
      </div>
      <label className="checkbox">
        <input type="checkbox" aria-label="Show male" checked={showMale} onChange={(e) => setShowMale(e.target.checked)} />
        <span>male</span>
      </label>
      <label className="checkbox">
        <input type="checkbox" aria-label="Show female" checked={showFemale} onChange={(e) => setShowFemale(e.target.checked)} />
        <span>female</span>
      </label>
      <button type="button" onClick={onReset}>
        Reset view
      </button>
    </div>
  )
}
