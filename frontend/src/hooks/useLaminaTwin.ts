/**
 * useLaminaTwin — one lamina's structure and its live values, kept in step.
 *
 * Lifted out of TwinDashboard so that every screen drawing a lamina shares one
 * copy of the rules that make the drawing trustworthy, rather than each screen
 * carrying its own copy and the copies drifting apart:
 *
 *   • The structure is re-read on every lamina change and tagged with the
 *     lamina it describes. A structure whose tag does not match the lamina
 *     being asked for is not returned, so nothing renders one model's shape
 *     over another model's numbers.
 *   • Every tick is checked against that structure. A tick from a different
 *     lamina (a backend restarted onto another one behind an open tab) is held
 *     back, and the caller is told which lamina the socket is actually sending
 *     so it can re-read the structure for it.
 *   • A socket that is not open is reported as stale, with the age of the last
 *     tick, because a frozen number looks exactly like a live one that happens
 *     not to be moving.
 *
 * None of this knows what a lamina contains. There is no attribute id here.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useCardioStream } from './useCardioStream'
import type { ServerNotice, StreamStatus, StreamTick } from './useCardioStream'
import { fetchLaminae, fetchSchema } from '../utils/api'
import type { LaminaOption } from '../utils/api'
import { indexLamina } from '../twin/schema'
import type { LaminaIndex } from '../twin/schema'
import { loadStage } from '../twin/stageTemplate'
import type { LoadedStage } from '../twin/stageTemplate'
import { artworkFor } from '../twin/stageRegistry'
import type { StageArtwork } from '../twin/stageRegistry'

/**
 * The HTTP status on a rejection, or null when there is none.
 *
 * A failed request can reject with anything at all: an axios error with a
 * response, a bare network error with no `response` (the sleeping-host case),
 * or a value that is not even an Error.  The retry path must read the status
 * without ever throwing on the shape, so every step is checked rather than
 * assumed.
 */
function responseStatus(error: unknown): number | null {
  if (typeof error !== 'object' || error === null) return null
  const response = (error as { response?: unknown }).response
  if (typeof response !== 'object' || response === null) return null
  const status = (response as { status?: unknown }).status
  return typeof status === 'number' ? status : null
}

interface Options {
  /** Lamina id to open, or null for whatever the backend defaults to. */
  lamina: string | null
  /** Called with the lamina the socket is really sending, on a mismatch. */
  onLamina: (id: string) => void
  /** Ring-buffer length; 300 ticks at 10 Hz is about 30 s of history. */
  bufferSize?: number
  /** Whether the caller wants a stream at all (default true). */
  enabled?: boolean
  /** Every notice frame the backend sends, including refusals. */
  onNotice?: (n: ServerNotice) => void
  /** The socket opened again for this lamina; `restored` is how many controls were replayed. */
  onReconnect?: (restored: number) => void
}

export interface LaminaTwin {
  /** The structure, or null while it loads or when it belongs to another lamina. */
  index: LaminaIndex | null
  schemaError: string | null
  /** Epoch ms of the next schema fetch while the server is unreachable; null when none. */
  schemaRetryAt: number | null
  /** Failed schema fetches for this lamina; 0 after one succeeds. */
  schemaAttempts: number
  /** Cancel a pending schema retry and fetch now; a no-op when nothing failed. */
  retrySchema: () => void
  /** What the backend can serve, for a lamina picker. */
  laminae: LaminaOption[]
  ticks: StreamTick[]
  /** The newest tick, or null when there is none or it is from another lamina. */
  latest: StreamTick | null
  status: StreamStatus
  closeReason: string | null
  /** The socket is sending a lamina this structure was not read for. */
  mismatch: boolean
  streamLamina: string
  /** The socket is not open and the numbers on screen are a photograph. */
  stale: boolean
  /** Seconds since the last tick while stale, otherwise null. */
  staleAge: number | null
  /** Epoch ms of the next socket reconnect while closed; null otherwise. */
  retryAt: number | null
  /** Consecutive socket closes since the last successful open; 0 while open. */
  attempts: number
  /** Whether the socket has opened at least once for the current lamina. */
  everOpened: boolean
  /** Mirrors navigator.onLine, so the screen can blame the network instead of us. */
  online: boolean
  /** Skip the rest of the socket backoff and connect now; stable for a button. */
  retryNow: () => void
  artwork: StageArtwork | null
  /** The loaded stage template, or null when this lamina has no artwork. */
  stage: LoadedStage | null
  paused: boolean
  togglePause: () => void
  reset: () => void
  setSensor: (id: string, value: number) => void
}

export function useLaminaTwin({
  lamina,
  onLamina,
  bufferSize = 300,
  enabled = true,
  onNotice,
  onReconnect,
}: Options): LaminaTwin {
  const {
    ticks,
    status,
    sendControl,
    lastTickAt,
    closeReason,
    retryAt,
    attempts,
    everOpened,
    online,
    retryNow,
  } = useCardioStream({
    tickMs: 100,
    bufferSize,
    lamina,
    enabled,
    onNotice,
    onReconnect,
  })
  const newest: StreamTick | null = ticks.length > 0 ? ticks[ticks.length - 1] : null

  const [structure, setStructure] = useState<
    { lamina: string | null; index: LaminaIndex } | null
  >(null)
  const [failure, setFailure] = useState<{ lamina: string | null; message: string } | null>(null)
  // Retry bookkeeping is tagged with its lamina for the same reason `failure`
  // is: a lamina change must not show the previous model's attempts or
  // deadline, and the pair reads as zero/none until the new one fails.
  const [schemaRetry, setSchemaRetry] = useState<{
    lamina: string | null
    attempts: number
    retryAt: number | null
  }>({ lamina: null, attempts: 0, retryAt: null })
  const [retryToken, setRetryToken] = useState(0)
  const [laminae, setLaminae] = useState<LaminaOption[]>([])
  const [loaded, setLoaded] = useState<LoadedStage | null>(null)
  const [paused, setPaused] = useState(false)

  const retryRef = useRef<{ lamina: string | null; attempts: number }>({
    lamina: null,
    attempts: 0,
  })
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Kept alongside the rendered list so the schema success path can ask
  // whether the list is *still* empty without making the list a schema-effect
  // dependency (which would re-read the schema every time the picker loaded).
  const laminaeRef = useRef<LaminaOption[]>([])

  const index = structure && structure.lamina === lamina ? structure.index : null
  const schemaError = failure && failure.lamina === lamina ? failure.message : null
  const schemaAttempts = schemaRetry.lamina === lamina ? schemaRetry.attempts : 0
  const schemaRetryAt = schemaRetry.lamina === lamina ? schemaRetry.retryAt : null

  useEffect(() => {
    let live = true
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    // A different lamina starts its own retry ladder.  Re-runs caused by
    // `retryToken` keep the ladder, and its backoff, intact.
    if (retryRef.current.lamina !== lamina) {
      retryRef.current = { lamina, attempts: 0 }
    }

    fetchSchema(lamina)
      .then((raw) => {
        if (!live) return
        const recovered = retryRef.current.lamina === lamina && retryRef.current.attempts > 0
        setStructure({ lamina, index: indexLamina(raw) })
        setFailure(null)
        retryRef.current = { lamina, attempts: 0 }
        setSchemaRetry({ lamina, attempts: 0, retryAt: null })

        // The lamina list failed for the same reason the schema did.  When
        // the schema finally comes back after an outage, fill a still-empty
        // list too rather than leaving the picker blank until a reload.
        if (recovered && laminaeRef.current.length === 0) {
          fetchLaminae()
            .then((r) => {
              if (!live) return
              laminaeRef.current = r.laminae
              setLaminae(r.laminae)
            })
            .catch(() => {
              if (!live) return
              laminaeRef.current = []
              setLaminae([])
            })
        }
      })
      .catch((error: unknown) => {
        if (!live) return

        if (responseStatus(error) === 404) {
          // An unknown id cannot fix itself.  Retrying it would only keep a
          // wall display flickering between the same two failures, so a 404
          // is final and keeps the message it has always had.
          const attempts =
            (retryRef.current.lamina === lamina ? retryRef.current.attempts : 0) + 1
          retryRef.current = { lamina, attempts }
          setFailure({
            lamina,
            message: `No lamina with id "${lamina}" — the backend does not serve one.`,
          })
          setSchemaRetry({ lamina, attempts, retryAt: null })
          return
        }

        // Everything else is treated as a server that has not answered yet:
        // a free host asleep after its idle window (the first minute of
        // requests fail while it boots), a network error with no response, a
        // non-404 rejection, or a thrown non-Error.  Back off 2 s, 4 s, 8 s,
        // then 15 s, with no attempt limit: a wall display has nobody to
        // press reload, and the outage cannot fix itself in any other way.
        const attempts =
          (retryRef.current.lamina === lamina ? retryRef.current.attempts : 0) + 1
        retryRef.current = { lamina, attempts }
        const delay = Math.min(2_000 * 2 ** (attempts - 1), 15_000)
        setFailure({ lamina, message: "Can't reach the server." })
        setSchemaRetry({ lamina, attempts, retryAt: Date.now() + delay })

        retryTimer = setTimeout(() => {
          retryTimer = null
          retryTimerRef.current = null
          // No deadline while this attempt is in flight; a failure below will
          // schedule the next one, a success will clear it.
          setSchemaRetry({ lamina, attempts, retryAt: null })
          setRetryToken((n) => n + 1)
        }, delay)
        retryTimerRef.current = retryTimer
      })

    return () => {
      live = false
      if (retryTimer) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      retryTimerRef.current = null
    }
  }, [lamina, retryToken])

  useEffect(() => {
    let live = true
    fetchLaminae()
      .then((r) => {
        if (!live) return
        laminaeRef.current = r.laminae
        setLaminae(r.laminae)
      })
      .catch(() => {
        if (!live) return
        laminaeRef.current = []
        setLaminae([])
      })
    return () => {
      live = false
    }
  }, [])

  // Manual retry: only meaningful once this lamina has actually failed.  It
  // cancels the scheduled attempt (if any) and bumps the token to start a
  // fetch now, through the same effect that owns every other attempt.
  const retrySchema = useCallback(() => {
    const failureRef = retryRef.current
    if (failureRef.lamina !== lamina || failureRef.attempts === 0) return
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    setSchemaRetry({ lamina, attempts: failureRef.attempts, retryAt: null })
    setRetryToken((n) => n + 1)
  }, [lamina])

  const streamLamina = newest?.laminaId ?? ''
  const mismatch = Boolean(index && streamLamina && streamLamina !== index.schema.lamina_id)

  useEffect(() => {
    if (mismatch && streamLamina) onLamina(streamLamina)
  }, [mismatch, streamLamina, onLamina])

  const latest: StreamTick | null = mismatch ? null : newest

  const stale = status !== 'open' && latest !== null
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!stale) return
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [stale])
  const staleAge = stale && lastTickAt ? Math.max(0, Math.round((now - lastTickAt) / 1000)) : null

  const artwork = artworkFor(index?.schema.lamina_id)

  // The template is fetched at runtime, so bindings can change without a
  // rebuild. It is only ever read through `stage` below, which is gated on
  // there being artwork at all, so no clearing pass is needed.
  useEffect(() => {
    if (!artwork) return
    let live = true
    loadStage(artwork.dir)
      .then((s) => live && setLoaded(s))
      .catch(() => live && setLoaded(null))
    return () => {
      live = false
    }
  }, [artwork])
  const stage = artwork ? loaded : null

  const togglePause = useCallback(() => {
    setPaused((was) => {
      sendControl({ type: was ? 'resume' : 'pause' })
      return !was
    })
  }, [sendControl])

  const reset = useCallback(() => {
    sendControl({ type: 'reset' })
    if (paused) sendControl({ type: 'resume' })
    setPaused(false)
  }, [sendControl, paused])

  const setSensor = useCallback(
    (id: string, value: number) => sendControl({ type: 'set_sensor', id, value }),
    [sendControl]
  )

  return {
    index,
    schemaError,
    schemaRetryAt,
    schemaAttempts,
    retrySchema,
    laminae,
    ticks,
    latest,
    status,
    closeReason,
    mismatch,
    streamLamina,
    stale,
    staleAge,
    retryAt,
    attempts,
    everOpened,
    online,
    retryNow,
    artwork,
    stage,
    paused,
    togglePause,
    reset,
    setSensor,
  }
}
