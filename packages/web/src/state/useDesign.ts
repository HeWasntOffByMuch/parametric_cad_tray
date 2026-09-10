import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api, diagnosticsOf } from '../api/client'
import { followJob } from '../api/jobStream'
import type { Diagnostic, Job, Json, ValidateResponse } from '../api/types'
import { saveLocal, writeHash } from './urlState'

/** Key order is stable in these documents (they come from one schema), but the
 *  fingerprint must not depend on that, so sort. */
function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, item) =>
    item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)))
      : item,
  )
}

/**
 * The preview state machine.
 *
 *   empty ──generate──► generating ──ok──► clean ──edit──► dirty ──generate──► generating
 *                            │                              ▲                      │
 *                            └──fail──► failed ─────────────┘◄─────────────────────┘
 *
 * `clean` and `dirty` both have a preview on screen. Editing never blanks the
 * viewer; it marks what is displayed as out of date.
 *
 * Staleness is decided by the parameters themselves, not by arrival order and
 * not by the server hash: a preview may only be displayed if the parameters it
 * was built from still equal the current ones. Using the server hash would tie
 * the guard to validation timing - a preview triggered before its validation
 * returned would look stale when it is not - and using arrival order would let a
 * slow older job overwrite a newer one.
 */
export type PreviewState = 'empty' | 'generating' | 'clean' | 'dirty' | 'failed'

/** Enough to stop a network request per keystroke, short enough to feel live. */
/**
 * The preview's two halves.
 *
 * A preview is built as two independent jobs on the server - the plug and the
 * cavity share no geometry downstream of the base profile - so each half has
 * its own cache entry and its own URL. Changing a cavity-only setting reuses
 * the plug's entry untouched, which is most of why an edit is fast.
 */
export interface PreviewUrls {
  male: string | null
  female: string | null
}

export const EMPTY_URLS: PreviewUrls = { male: null, female: null }

export function hasAny(urls: PreviewUrls): boolean {
  return Boolean(urls.male || urls.female)
}

/** Pull the per-half GLB URLs out of a finished job's artifacts.
 *
 *  Falls back to the single combined `preview.glb` an older API returns, so a
 *  frontend deployed ahead of its backend still shows a model. */
export function previewUrlsOf(job: Job): PreviewUrls {
  const out: PreviewUrls = { male: null, female: null }
  for (const artifact of Object.values(job.artifacts ?? {})) {
    if (artifact.format !== 'glb') continue
    if (artifact.part === 'male' || artifact.part === 'female') {
      out[artifact.part] = artifact.url
    } else {
      // A combined assembly GLB carries both halves in one file; handing the
      // same URL to both slots makes the viewer load it once and find each
      // named node in it.
      out.male = out.male ?? artifact.url
      out.female = out.female ?? artifact.url
    }
  }
  return out
}

export const VALIDATE_DEBOUNCE_MS = 250
/** A cache-miss preview costs ~3.4 s, so idle regeneration waits for a real pause. */
export const PREVIEW_IDLE_MS = 700

export interface DesignOptions {
  /** Regenerate the preview after an idle pause, as well as on demand. */
  autoPreview?: boolean
  validateDebounceMs?: number
  previewIdleMs?: number
}

export interface DesignState {
  params: Json
  validation: ValidateResponse | null
  validating: boolean
  diagnostics: Diagnostic[]
  errors: Diagnostic[]
  valid: boolean
  previewState: PreviewState
  previewJob: Job | null
  /** One GLB per half. The API builds them as separate cache entries, so a
   *  change that only touches the cavity leaves the plug's URL alone and the
   *  viewer keeps the mesh it already has. */
  previewUrls: PreviewUrls
  previewedFingerprint: string | null
  currentHash: string | null
  transportError: string | null
  allowExperimental: boolean
}

export interface DesignActions {
  setParams: (next: Json) => void
  replaceParams: (next: Json) => void
  commit: () => void
  generatePreview: () => void
  cancelPreview: () => void
  setAllowExperimental: (value: boolean) => void
}

export function useDesign(initial: Json | null, options: DesignOptions = {}): [DesignState, DesignActions] {
  const {
    autoPreview = true,
    validateDebounceMs = VALIDATE_DEBOUNCE_MS,
    previewIdleMs = PREVIEW_IDLE_MS,
  } = options
  const [params, setParamsState] = useState<Json>(initial ?? {})
  const [validation, setValidation] = useState<ValidateResponse | null>(null)
  const [validating, setValidating] = useState(false)
  const [previewJob, setPreviewJob] = useState<Job | null>(null)
  const [previewUrls, setPreviewUrls] = useState<PreviewUrls>(EMPTY_URLS)
  const [previewedFingerprint, setPreviewedFingerprint] = useState<string | null>(null)
  const [previewState, setPreviewState] = useState<PreviewState>('empty')
  const [transportError, setTransportError] = useState<string | null>(null)
  // Diagnostics from a document the server would not even parse. Kept apart
  // from `validation` because they describe the parameters as they are now,
  // while a validation result that predates the rejection describes older ones.
  const [rejected, setRejected] = useState<Diagnostic[]>([])
  const [allowExperimental, setAllowExperimental] = useState(false)

  const paramsRef = useRef(params)
  paramsRef.current = params
  const currentHash = validation?.params_hash ?? null
  /** Identity of a parameter document, independent of the backend. */
  const fingerprint = useMemo(() => stableStringify(params), [params])
  const fingerprintRef = useRef(fingerprint)
  fingerprintRef.current = fingerprint

  // What is on screen, and what is being built, as refs: `generatePreview` is
  // reached from a timer and from a click, and both must see the latest values
  // rather than whatever was closed over when the callback was made.
  const previewedRef = useRef<string | null>(null)
  previewedRef.current = previewedFingerprint
  const previewUrlRef = useRef<PreviewUrls>(EMPTY_URLS)
  previewUrlRef.current = previewUrls
  /** Is there a model on screen at all? The difference between 'this is now
   *  out of date' and 'there is nothing here yet'. */
  const onScreen = hasAny(previewUrls)
  /** Fingerprint of the build currently in flight, if any. */
  const inFlight = useRef<string | null>(null)

  const stopFollowing = useRef<null | (() => void)>(null)
  const runningJobId = useRef<string | null>(null)
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const validateAbort = useRef<AbortController | null>(null)

  useEffect(() => {
    if (initial) setParamsState(initial)
  }, [initial])

  // -- validation: cheap, on every meaningful change ------------------------
  useEffect(() => {
    if (!params || Object.keys(params).length === 0) return
    if (validateTimer.current) clearTimeout(validateTimer.current)
    validateTimer.current = setTimeout(async () => {
      validateAbort.current?.abort()
      const controller = new AbortController()
      validateAbort.current = controller
      setValidating(true)
      try {
        const result = await api.validate(params, allowExperimental, controller.signal)
        setValidation(result)
        setRejected([])
        setTransportError(null)
      } catch (error) {
        if ((error as any)?.name === 'AbortError') return
        // A rejected body is not a transport failure: the server answered, and
        // it said which field it could not accept. Show that on the field.
        const diagnostics = diagnosticsOf(error)
        setRejected(diagnostics)
        setTransportError(diagnostics.length ? null : (error as ApiError).message)
      } finally {
        setValidating(false)
      }
    }, validateDebounceMs)
  }, [params, allowExperimental, validateDebounceMs])

  // -- dirty tracking -------------------------------------------------------
  useEffect(() => {
    if (!previewedFingerprint) return
    setPreviewState((state) => {
      if (state === 'generating') return state
      if (fingerprint === previewedFingerprint) return 'clean'
      return onScreen ? 'dirty' : state
    })
  }, [fingerprint, previewedFingerprint, onScreen])

  // -- shareable state ------------------------------------------------------
  useEffect(() => {
    if (!params || Object.keys(params).length === 0) return
    saveLocal(params)
    void writeHash(params)
  }, [params])

  const generatePreview = useCallback(async () => {
    const snapshot = paramsRef.current
    if (!snapshot || Object.keys(snapshot).length === 0) return
    const requested = stableStringify(snapshot)

    // Two ways to ask for the same geometry twice, both of which used to send it.
    //
    // Clicking Update preview when nothing has changed: the answer is already on
    // screen, and rebuilding it produces a byte-identical GLB. The server would
    // serve it from cache in milliseconds, so it looks harmless, but it is still
    // a round trip, a rate-limit slot and a re-fetch of the model for nothing.
    if (requested === previewedRef.current && hasAny(previewUrlRef.current)) {
      setPreviewState('clean')
      return
    }
    // Clicking Update preview while the field still has focus: the click blurs
    // the input, which commits, which schedules an immediate build - and then the
    // button's own handler starts a second one. The first was cancelled mid-flight
    // and rebuilt from scratch. Measured: one click, two POST /api/preview.
    if (requested === inFlight.current) return

    inFlight.current = requested
    stopFollowing.current?.()
    // A superseded build is wasted CPU; cancel it rather than let it finish.
    if (runningJobId.current) void api.cancel(runningJobId.current).catch(() => {})
    setPreviewState('generating')
    setTransportError(null)
    let job: Job
    try {
      job = await api.preview(snapshot, allowExperimental)
    } catch (error) {
      runningJobId.current = null
      inFlight.current = null
      setPreviewState(onScreen ? 'dirty' : 'failed')
      const diagnostics = diagnosticsOf(error)
      if (diagnostics.length) setRejected(diagnostics)
      setTransportError(diagnostics.length ? null : (error as ApiError).message)
      return
    }
    runningJobId.current = job.state === 'complete' ? null : job.id
    setPreviewJob(job)

    const settle = (finished: Job) => {
      runningJobId.current = null
      if (inFlight.current === requested) inFlight.current = null
      setPreviewJob(finished)
      // The stale guard: this result is only allowed on screen if the parameters
      // it was built from are still the ones the user has.
      const stale = requested !== fingerprintRef.current
      if (finished.state === 'complete') {
        const found = previewUrlsOf(finished)
        if (hasAny(found) && !stale) {
          setPreviewUrls(found)
          setPreviewedFingerprint(requested)
          setPreviewState('clean')
        } else if (hasAny(found) && stale) {
          setPreviewState(onScreen ? 'dirty' : 'empty')
        }
      } else if (finished.state === 'failed') {
        if (!stale) setPreviewState('failed')
      } else if (finished.state === 'cancelled') {
        setPreviewState(onScreen ? 'dirty' : 'empty')
      }
    }

    if (job.state === 'complete') {
      settle(job) // cache hit: already done
      return
    }
    stopFollowing.current = followJob(job.id, {
      onUpdate: setPreviewJob,
      onDone: settle,
      onError: (e) => setTransportError(e.message),
    })
  }, [allowExperimental, onScreen])

  const cancelPreview = useCallback(() => {
    const id = runningJobId.current
    stopFollowing.current?.()
    runningJobId.current = null
    inFlight.current = null
    if (id) void api.cancel(id).catch(() => {})
    setPreviewState(onScreen ? 'dirty' : 'empty')
  }, [onScreen])

  const scheduleIdlePreview = useCallback(
    (delayMs = previewIdleMs) => {
      if (!autoPreview) return
      if (idleTimer.current) clearTimeout(idleTimer.current)
      idleTimer.current = setTimeout(() => {
        if (validation?.valid !== false) void generatePreview()
      }, delayMs)
    },
    [autoPreview, generatePreview, previewIdleMs, validation?.valid],
  )

  // -- the first preview ----------------------------------------------------
  // Someone who has just opened the page has not decided to preview anything;
  // they have arrived at a design - a preset, a shared link, or what they had
  // last time - and an empty viewport asking them to press Update preview makes
  // them confirm a choice they never made. So the design is on screen as soon as
  // it is known.
  //
  // Keyed on the parameters rather than on `initial` so that it cannot run
  // before paramsRef holds the design generatePreview is about to read, and
  // scheduled through the same idle timer as every other build, so a user who
  // starts editing within the first moment supersedes it rather than racing it.
  const built = useRef(false)
  useEffect(() => {
    if (built.current) return
    if (!params || Object.keys(params).length === 0) return
    built.current = true
    scheduleIdlePreview(0)
  }, [params, scheduleIdlePreview])

  const setParams = useCallback(
    (next: Json) => {
      setParamsState(next)
      // Typing schedules a regeneration after the idle pause; it never starts one
      // per keystroke. A commit (blur, Enter, slider release) short-circuits the
      // wait because the user has finished with that control.
      scheduleIdlePreview()
    },
    [scheduleIdlePreview],
  )

  const replaceParams = useCallback(
    (next: Json) => {
      setParamsState(next)
      setPreviewedFingerprint(null)
      setPreviewUrls(EMPTY_URLS)
      setPreviewState('empty')
      scheduleIdlePreview()
    },
    [scheduleIdlePreview],
  )

  useEffect(
    () => () => {
      stopFollowing.current?.()
      if (idleTimer.current) clearTimeout(idleTimer.current)
    },
    [],
  )

  // A rejection is about the current document; a stored validation may not be.
  const diagnostics = rejected.length ? rejected : validation?.diagnostics ?? []
  const state: DesignState = useMemo(
    () => ({
      params,
      validation,
      validating,
      diagnostics,
      errors: diagnostics.filter((d) => d.severity === 'error'),
      valid: rejected.length ? false : validation?.valid ?? false,
      previewState,
      previewJob,
      previewUrls,
      previewedFingerprint,
      currentHash,
      transportError,
      allowExperimental,
    }),
    [params, validation, validating, rejected, previewState, previewJob, previewUrls, previewedFingerprint, currentHash, transportError, allowExperimental],
  )

  return [
    state,
    {
      setParams,
      replaceParams,
      commit: () => scheduleIdlePreview(0),
      generatePreview,
      cancelPreview,
      setAllowExperimental,
    },
  ]
}
