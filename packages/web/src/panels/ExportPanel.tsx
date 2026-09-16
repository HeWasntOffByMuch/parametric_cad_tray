import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
import { followJob } from '../api/jobStream'
import { withSession } from '../analytics'
import { apiUrl } from '../config'
import type { Job, Json, PrintLedger } from '../api/types'

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

function hasLedger(value: Job['print_ledger']): value is PrintLedger {
  return Boolean(value && 'options' in value && (value as PrintLedger).options?.length)
}

/**
 * What each infill option costs, on this design.
 *
 * Every row is the *same geometry* priced differently - these options change
 * the print, never the part - which is why they can sit next to each other at
 * all. The option that writes no settings has no number, because what it costs
 * is whatever preset the reader has loaded.
 */
function PrintLedgerTable({ ledger }: { ledger: PrintLedger }) {
  return (
    <div className="ledger" data-testid="print-ledger">
      <table>
        <thead>
          <tr>
            <th>Infill plan</th>
            <th>Filament</th>
            <th>vs {ledger.assumptions.reference}</th>
          </tr>
        </thead>
        <tbody>
          {ledger.options.map((row) => (
            <tr key={row.option} className={row.selected ? 'selected' : row.reference ? 'reference' : undefined}>
              <th scope="row">
                {row.option}
                {row.selected && <span className="badge">in this file</span>}
              </th>
              <td>{row.grams === null ? '—' : `${row.grams} g`}</td>
              <td>{row.vs_reference_pct === null ? (row.note ?? '—') : `${row.vs_reference_pct > 0 ? '+' : ''}${row.vs_reference_pct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {ledger.regions.length > 0 && (
        <details>
          <summary>Where the density goes back in</summary>
          <ul>
            {ledger.regions.map((region) => (
              <li key={`${region.part}-${region.name}`}>
                <strong>
                  {region.part} {region.name}
                </strong>{' '}
                {region.cm3} cm³ at {Math.round(region.to_density * 100)}% instead of{' '}
                {Math.round(region.from_density * 100)}%, {region.delta_cm3 > 0 ? '+' : ''}
                {region.delta_cm3} cm³ — {region.why}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="hint">{ledger.assumptions.accuracy}.</p>
    </div>
  )
}

/**
 * Export uses the same asynchronous job model as preview, and is completely
 * independent of it: requesting an export never regenerates the preview, and a
 * preview in flight does not block an export. Artifacts appear only once the
 * job completes.
 */
export function ExportPanel({
  params,
  disabled,
  allowExperimental,
  offer3mf = false,
}: {
  params: Json
  disabled: boolean
  allowExperimental: boolean
  /** The 3MF export is gated per deployment and revealed by a hidden switch;
   *  see `flags.ts`. Offering it when either says no would only earn a 422. */
  offer3mf?: boolean
}) {
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

  // A switch turned back off, or a deployment that stopped offering the format,
  // must not leave it selected: the request would be refused and the user would
  // have no control to un-tick.
  useEffect(() => {
    if (!offer3mf) setFormats((current) => (current.includes('3mf') ? current.filter((f) => f !== '3mf') : current))
  }, [offer3mf])

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
            {(offer3mf ? ['step', 'stl', '3mf'] : ['step', 'stl']).map((name) => (
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
              <a href={withSession(apiUrl(artifact.url))} download={artifact.name}>
                <span>{artifactLabel(artifact.part, artifact.format)}</span>
                <span className="artifact-size">{fileSize(artifact.bytes)}</span>
              </a>
            </li>
          ))}
          {job?.bundle_url && (
            <li>
              <a href={withSession(apiUrl(job.bundle_url))} download="tray-mold.zip">
                <span>Complete bundle</span>
                <span className="artifact-size">ZIP</span>
              </a>
            </li>
          )}
        </ul>
      )}
      {/* Worth saying, because the viewer above shows the opposite: it has to
          show the halves closed, so the female is the other way up there. */}
      {artifacts.length > 0 && (
        <p className="hint" data-testid="export-orientation">
          Print-oriented: each half is already flat-side-down on the bed.
        </p>
      )}
      {job?.state === 'complete' && hasLedger(job.print_ledger) && (
        <PrintLedgerTable ledger={job.print_ledger} />
      )}
      {job?.cached && job.state === 'complete' && <p className="hint">served from cache</p>}
    </section>
  )
}
