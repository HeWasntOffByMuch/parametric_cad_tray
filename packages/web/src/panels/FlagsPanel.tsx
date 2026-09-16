import { KNOWN_FLAGS, FLAG_FEATURE } from '../flags'

/**
 * The switch panel behind ctrl/cmd + shift + `.`.
 *
 * It shows the deployment's answer next to each switch on purpose. A flag the
 * server does not offer is not a broken flag - it is a capability this
 * deployment has turned off - and someone who has just found this panel should
 * be able to see that rather than turn a switch on and watch an export fail.
 */
export function FlagsPanel({
  flags,
  features,
  onToggle,
  onClose,
}: {
  flags: Set<string>
  features: Record<string, boolean> | undefined
  onToggle: (name: string, on: boolean) => void
  onClose: () => void
}) {
  return (
    <div className="flags-panel" role="dialog" aria-label="Hidden switches" data-testid="flags-panel">
      <header>
        <h2>Hidden switches</h2>
        <button type="button" aria-label="Close hidden switches" onClick={onClose}>
          ×
        </button>
      </header>
      <ul>
        {Object.entries(KNOWN_FLAGS).map(([name, description]) => {
          const offered = Boolean(features?.[FLAG_FEATURE[name]])
          return (
            <li key={name}>
              <label className="checkbox">
                <input
                  type="checkbox"
                  aria-label={name}
                  checked={flags.has(name)}
                  onChange={(e) => onToggle(name, e.target.checked)}
                />
                <span className="flag-name">{name}</span>
              </label>
              <p className="hint">{description}</p>
              <p className={`hint ${offered ? '' : 'warn'}`} data-testid={`flag-server-${name}`}>
                {offered ? 'This server offers it.' : 'This server has it turned off, so the switch will do nothing.'}
              </p>
            </li>
          )
        })}
      </ul>
      <p className="hint">
        Kept in this browser only. <code>?flags={Object.keys(KNOWN_FLAGS).join(',')}</code> sets them from a link;{' '}
        <code>?flags=</code> clears them.
      </p>
    </div>
  )
}
