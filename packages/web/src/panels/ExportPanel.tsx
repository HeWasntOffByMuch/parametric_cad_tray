import { Fragment, useCallback, useRef, useState } from 'react'
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
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {ledger.options.map((row) => (
            <Fragment key={row.option}>
              <tr className={row.selected ? 'selected' : row.reference ? 'reference' : undefined}>
                <th scope="row">
                  {row.option}
                  {row.selected && <span className="badge">in this file</span>}
                </th>
                <td>{row.grams === null ? '—' : `${row.grams} g`}</td>
                <td>
                  {row.vs_reference_pct === null
                    ? '—'
                    : `${row.vs_reference_pct > 0 ? '+' : ''}${row.vs_reference_pct}%`}
                </td>
              </tr>
              {/* Prose does not belong in a numeric column: the note is why a
                  row has no number, so it goes under the row rather than in the
                  cell where a percentage would have been. */}
              {row.note && (
                <tr className="note">
                  <td colSpan={3}>{row.note}</td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="hint">Change is against {ledger.assumptions.reference}.</p>
      {ledger.global_settings?.length > 0 && (
        <div className="ledger-globals" data-testid="ledger-globals">
          <p className="hint">
            Set these in your slicer — the file reinforces the clamps and lightens the plug core,
            and leaves everything else to your own profile.
          </p>
          <ul>
            {ledger.global_settings.map((row) => (
              <li key={row.label}>
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}
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
/** The formats on offer, in the order they are shown.
 *
 *  3MF is marked rather than hidden. It is the newest of the three and the only
 *  one whose content depends on anything but the geometry, so it is worth
 *  saying so next to the checkbox - but a format nobody can find is a format
 *  nobody reports a problem with. */
const FORMATS: { name: string; label: string; experimental?: boolean }[] = [
  { name: 'step', label: 'STEP' },
  { name: 'stl', label: 'STL' },
  { name: '3mf', label: '3MF', experimental: true },
]

export function ExportPanel({
  params,
  disabled,
  allowExperimental,
}: {
  params: Json
  disabled: boolean
  allowExperimental: boolean
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
            {FORMATS.map((format) => (
              <label key={format.name} className="checkbox">
                <input
                  type="checkbox"
                  aria-label={format.label}
                  checked={formats.includes(format.name)}
                  onChange={() => toggleFormat(format.name)}
                />
                <span>
                  {format.label}
                  {format.experimental && <span className="badge warn">experimental</span>}
                </span>
              </label>
            ))}
          </div>
          {formats.includes('3mf') && (
            <p className="hint warn" data-testid="format-3mf-note">
              3MF puts each half on its own plate and marks where to reinforce. New — open it and
              look before you trust it.
            </p>
          )}
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
