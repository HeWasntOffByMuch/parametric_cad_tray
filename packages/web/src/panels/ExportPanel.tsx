import { useCallback, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import { followJob } from '../api/jobStream'
import { apiUrl } from '../config'
import type { Job, Json } from '../api/types'

type Parts = 'both' | 'male' | 'female'

/** "male.stl" is a filename; "Male STL" is what someone is downloading. The
 *  artifact already carries both facts, so neither is parsed out of the name. */
function artifactLabel(part: string, format: string): string {
  const half = part === 'male' ? 'Male' : part === 'female' ? 'Female' : 'Assembly'
  return `${half} ${format.toUpperCase()}`
}

/** kB below a megabyte, MB above: 5838 kB is a number to decode, 5.8 MB is a size. */
function fileSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} kB`
}

/**
 * Export uses the same asynchronous job model as preview, and is completely
 * independent of it: requesting an export never regenerates the preview, and a
 * preview in flight does not block an export. Artifacts appear only once the
 * job completes.
 */
export function ExportPanel({ params, disabled, allowExperimental }: { params: Json; disabled: boolean; allowExperimental: boolean }) {
  const [parts, setParts] = useState<Parts>('both')
  const [formats, setFormats] = useState<string[]>(['step', 'stl'])
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const stop = useRef<null | (() => void)>(null)

  const run = useCallback(async () => {
    stop.current?.()
    setBusy(true)
    setError(null)
    setJob(null)
    try {
      const started = await api.export(
        params,
        {
          parts: { male: parts !== 'female', female: parts !== 'male' },
          formats,
        },
        allowExperimental,
      )
      setJob(started)
      if (started.state === 'complete') {
        setBusy(false)
        return
      }
      stop.current = followJob(started.id, {
        onUpdate: setJob,
        onDone: (finished) => {
          setJob(finished)
          setBusy(false)
          if (finished.state === 'failed') setError(finished.error?.message ?? 'export failed')
        },
        onError: (e) => setError(e.message),
      })
    } catch (e) {
      setBusy(false)
      setError((e as ApiError).message)
    }
  }, [params, parts, formats, allowExperimental])

  const toggleFormat = (name: string) =>
    setFormats((current) => (current.includes(name) ? current.filter((f) => f !== name) : [...current, name]))

  const artifacts = job?.state === 'complete' ? Object.values(job.artifacts) : []

  return (
    <section className="export" data-testid="export-panel">
      <h2>Export</h2>
      <div className="row">
        <label>
          <span className="label" aria-hidden="true">Parts</span>
          <select aria-label="Export parts" value={parts} onChange={(e) => setParts(e.target.value as Parts)}>
            <option value="both">Both halves</option>
            <option value="male">Male only</option>
            <option value="female">Female only</option>
          </select>
        </label>
        <fieldset className="formats">
          <legend>Formats</legend>
          <div className="format-options">
            {['step', 'stl'].map((name) => (
              <label key={name} className="checkbox">
                <input
                  type="checkbox"
                  aria-label={name.toUpperCase()}
                  checked={formats.includes(name)}
                  onChange={() => toggleFormat(name)}
                />
                <span>{name.toUpperCase()}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <button
        type="button"
        className="primary block lg"
        onClick={run}
        disabled={disabled || busy || formats.length === 0}
        data-testid="export-button"
      >
        {busy ? 'Exporting…' : 'Export'}
      </button>
      {busy && <p className="hint" role="status">{job?.status ?? 'queued'}</p>}
      {error && (
        <p className="diag error" data-testid="export-error">
          {error}
        </p>
      )}
      {artifacts.length > 0 && (
        <ul className="artifacts" data-testid="export-artifacts">
          {artifacts.map((artifact) => (
            <li key={artifact.name}>
              <a href={apiUrl(artifact.url)} download={artifact.name}>
                <span>{artifactLabel(artifact.part, artifact.format)}</span>
                <span className="artifact-size">{fileSize(artifact.bytes)}</span>
              </a>
            </li>
          ))}
          {job?.bundle_url && (
            <li>
              <a href={apiUrl(job.bundle_url)} download="tray-mold.zip">
                <span>Complete bundle</span>
                <span className="artifact-size">ZIP</span>
              </a>
            </li>
          )}
        </ul>
      )}
      {job?.cached && job.state === 'complete' && <p className="hint">served from cache</p>}
    </section>
  )
}
