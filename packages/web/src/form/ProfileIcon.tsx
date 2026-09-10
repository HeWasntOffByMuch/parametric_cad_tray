import { PROFILE_SHAPES, PROFILE_VIEWBOX } from './profileShapes'

/**
 * The plan curve of one profile family, at icon size.
 *
 * The path is generated from the real geometry (see `profileShapes.ts`), so
 * this draws the shape the mold will actually have rather than an impression
 * of it. `vectorEffect` keeps the stroke a hairline at any rendered size, which
 * matters because the same icon is used at 24px in a row and in the closed
 * control.
 */
export function ProfileIcon({ kind }: { kind: string }) {
  const path = PROFILE_SHAPES[kind]
  if (!path) return null
  return (
    <svg className="profile-icon" viewBox={PROFILE_VIEWBOX} aria-hidden="true" focusable="false">
      <path
        d={path}
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
