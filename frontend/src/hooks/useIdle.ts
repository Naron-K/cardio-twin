/**
 * useIdle — has anyone touched this screen lately?
 *
 * The dashboard is left open on a wall display. A stream nobody is watching
 * still costs the server a session and about 70 KB/s before compression, which
 * the host meters against its monthly bandwidth. So after a
 * stretch with no touch, key or wheel, the dashboard closes its stream and
 * says so, the way a video service asks whether you are still watching; the
 * next touch opens it again.
 *
 * The stretch is 15 minutes unless the page URL says otherwise: `?idle=30`
 * for half an hour, `?idle=0` for a display that should never let go.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export const DEFAULT_IDLE_MINUTES = 15

/** The idle limit the URL asks for, in minutes; 0 means never. */
export function idleMinutesFromUrl(fallback = DEFAULT_IDLE_MINUTES): number {
  try {
    const raw = new URLSearchParams(window.location.search).get('idle')
    if (raw === null || raw.trim() === '') return fallback
    const minutes = Number(raw)
    return Number.isFinite(minutes) && minutes >= 0 ? minutes : fallback
  } catch {
    return fallback
  }
}

const ACTIVITY = ['pointerdown', 'keydown', 'wheel'] as const

export function useIdle(minutes: number): { idle: boolean; wake: () => void } {
  const [idle, setIdle] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const arm = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    if (minutes > 0) timer.current = setTimeout(() => setIdle(true), minutes * 60_000)
  }, [minutes])

  const wake = useCallback(() => {
    setIdle(false)
    arm()
  }, [arm])

  useEffect(() => {
    arm()
    const onActivity = () => wake()
    for (const type of ACTIVITY) window.addEventListener(type, onActivity, { passive: true })
    return () => {
      if (timer.current) clearTimeout(timer.current)
      for (const type of ACTIVITY) window.removeEventListener(type, onActivity)
    }
  }, [arm, wake])

  return { idle, wake }
}
