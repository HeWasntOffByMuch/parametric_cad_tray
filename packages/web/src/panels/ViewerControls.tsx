import type { PartMode, ViewMode } from '../viewer/Viewer'

/**
 * Two segmented controls and one secondary action.
 *
 * There used to also be a male and a female checkbox. They did nothing the Part
 * selector could not: "both" with male unchecked is "female". Two ways to reach
 * one state is two things to read and one of them to distrust, so the checkboxes
 * are gone and `partVisibility` still receives the flags - it is the single rule
 * deciding what is drawn, and it is tested on its own.
 */
export function ViewerControls({
  partMode,
  setPartMode,
  viewMode,
  setViewMode,
  onReset,
}: {
  partMode: PartMode
  setPartMode: (v: PartMode) => void
  viewMode: ViewMode
  setViewMode: (v: ViewMode) => void
  onReset: () => void
}) {
  return (
    <div className="viewer-controls" data-testid="viewer-controls">
      <div className="control-group">
        <span className="caption" id="part-caption">
          Part
        </span>
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
      </div>

      <div className="control-group">
        <span className="caption">View</span>
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
      </div>

      <span className="control-divider" aria-hidden="true" />

      <button type="button" onClick={onReset}>
        Reset view
      </button>
    </div>
  )
}
