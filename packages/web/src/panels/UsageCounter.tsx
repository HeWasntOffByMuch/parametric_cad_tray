import { useEffect, useState } from 'react'
import { api } from '../api/client'

/**
 * The public usage number.
 *
 * Shows nothing at all until there is a real number to show: zero, a failed
 * request or a backend without analytics enabled all render as absent rather
 * than as an error or a "0". A counter is only worth displaying when it is
 * true, and an empty space costs the page nothing.
 *
 * The wording is chosen for what the metric actually measures. Not "users",
 * because anonymous sessions are not people; not "prints", because nothing here
 * knows whether a file ever reached a printer. A mold is counted when a custom
 * configuration was built successfully and its files were taken away.
 */
export function UsageCounter() {
  const [count, setCount] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .stats()
      .then((stats) => {
        const value = Number(stats?.custom_molds_generated)
        if (!cancelled && Number.isFinite(value) && value > 0) setCount(value)
      })
      .catch(() => {
        /* the counter is decoration; its absence is the failure mode */
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (count === null) return null
  return (
    <span
      className="usage-counter"
      data-testid="usage-counter"
      title="Counts unique custom configurations that were generated and downloaded."
    >
      <strong>{count.toLocaleString()}</strong> custom {count === 1 ? 'mold' : 'molds'} generated
    </span>
  )
}
