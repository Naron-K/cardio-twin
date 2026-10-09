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
import { useCallback, useEffect, useState } from 'react'
import { useCardioStream } from './useCardioStream'
import type { StreamStatus, StreamTick } from './useCardioStream'
import { fetchLaminae, fetchSchema } from '../utils/api'
import type { LaminaOption } from '../utils/api'
import { indexLamina } from '../twin/schema'
import type { LaminaIndex } from '../twin/schema'
import { loadStage } from '../twin/stageTemplate'
import type { LoadedStage } from '../twin/stageTemplate'
import { artworkFor } from '../twin/stageRegistry'
import type { StageArtwork } from '../twin/stageRegistry'

interface Options {
  /** Lamina id to open, or null for whatever the backend defaults to. */
  lamina: string | null
  /** Called with the lamina the socket is really sending, on a mismatch. */
  onLamina: (id: string) => void
  /** Ring-buffer length; 300 ticks at 10 Hz is about 30 s of history. */
  bufferSize?: number
}

export interface LaminaTwin {
  /** The structure, or null while it loads or when it belongs to another lamina. */
  index: LaminaIndex | null
  schemaError: string | null
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
  artwork: StageArtwork | null
  /** The loaded stage template, or null when this lamina has no artwork. */
  stage: LoadedStage | null
  paused: boolean
  togglePause: () => void
  reset: () => void
  setSensor: (id: string, value: number) => void
}

export function useLaminaTwin({ lamina, onLamina, bufferSize = 300 }: Options): LaminaTwin {
  const { ticks, status, sendControl, lastTickAt, closeReason } = useCardioStream({
    tickMs: 100,
    bufferSize,
    lamina,
  })
  const newest: StreamTick | null = ticks.length > 0 ? ticks[ticks.length - 1] : null

  const [structure, setStructure] = useState<
    { lamina: string | null; index: LaminaIndex } | null
  >(null)
  const [failure, setFailure] = useState<{ lamina: string | null; message: string } | null>(null)
  const [laminae, setLaminae] = useState<LaminaOption[]>([])
  const [loaded, setLoaded] = useState<LoadedStage | null>(null)
  const [paused, setPaused] = useState(false)

  const index = structure && structure.lamina === lamina ? structure.index : null
  const schemaError = failure && failure.lamina === lamina ? failure.message : null

  useEffect(() => {
    let live = true
    fetchSchema(lamina)
      .then((raw) => live && setStructure({ lamina, index: indexLamina(raw) }))
      .catch((e) =>
        live &&
        setFailure({
          lamina,
          message:
            e?.response?.status === 404
              ? `No lamina with id "${lamina}" — the backend does not serve one.`
              : 'Schema failed to load — is the backend up on port 8000?',
        })
      )
    return () => {
      live = false
    }
  }, [lamina])

  useEffect(() => {
    let live = true
    fetchLaminae()
      .then((r) => live && setLaminae(r.laminae))
      .catch(() => live && setLaminae([]))
    return () => {
      live = false
    }
  }, [])

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
    laminae,
    ticks,
    latest,
    status,
    closeReason,
    mismatch,
    streamLamina,
    stale,
    staleAge,
    artwork,
    stage,
    paused,
    togglePause,
    reset,
    setSensor,
  }
}
