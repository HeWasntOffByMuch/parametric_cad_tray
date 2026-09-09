import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, api } from '../api/client'
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
  previewUrl: string | null
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
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewedFingerprint, setPreviewedFingerprint] = useState<string | null>(null)
  const [previewState, setPreviewState] = useState<PreviewState>('empty')
  const [transportError, setTransportError] = useState<string | null>(null)
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
  const previewUrlRef = useRef<string | null>(null)
  previewUrlRef.current = previewUrl
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
        setTransportError(null)
      } catch (error) {
        if ((error as any)?.name === 'AbortError') return
        setTransportError((error as ApiError).message)
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
      return previewUrl ? 'dirty' : state
    })
  }, [fingerprint, previewedFingerprint, previewUrl])

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
    if (requested === previewedRef.current && previewUrlRef.current) {
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
      setPreviewState(previewUrl ? 'dirty' : 'failed')
      setTransportError((error as ApiError).message)
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
        const artifact = finished.artifacts['preview.glb']
        if (artifact && !stale) {
          setPreviewUrl(artifact.url)
          setPreviewedFingerprint(requested)
          setPreviewState('clean')
        } else if (artifact && stale) {
          setPreviewState(previewUrl ? 'dirty' : 'empty')
        }
      } else if (finished.state === 'failed') {
        if (!stale) setPreviewState('failed')
      } else if (finished.state === 'cancelled') {
        setPreviewState(previewUrl ? 'dirty' : 'empty')
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
  }, [allowExperimental, previewUrl])

  const cancelPreview = useCallback(() => {
    const id = runningJobId.current
    stopFollowing.current?.()
    runningJobId.current = null
    inFlight.current = null
    if (id) void api.cancel(id).catch(() => {})
    setPreviewState(previewUrl ? 'dirty' : 'empty')
  }, [previewUrl])

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
      setPreviewUrl(null)
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

  const diagnostics = validation?.diagnostics ?? []
  const state: DesignState = useMemo(
    () => ({
      params,
      validation,
      validating,
      diagnostics,
      errors: diagnostics.filter((d) => d.severity === 'error'),
      valid: validation?.valid ?? false,
      previewState,
      previewJob,
      previewUrl,
      previewedFingerprint,
      currentHash,
      transportError,
      allowExperimental,
    }),
    [params, validation, validating, previewState, previewJob, previewUrl, previewedFingerprint, currentHash, transportError, allowExperimental],
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
