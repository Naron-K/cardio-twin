/**
 * useWakeLock — keep the display awake while someone is using it.
 *
 * A touch board dims and sleeps on its own timer, which does not know that
 * a person is reading a chart without touching it. The Screen Wake Lock API
 * holds it awake while `active`; the lock is released when the dashboard goes
 * idle, so the board's own power settings take over again.
 *
 * The browser drops the lock whenever the page is hidden, so it is asked for
 * again when the page comes back. Browsers without the API, or that refuse
 * (it needs a secure origin), simply leave the screen to its own timer.
 */
import { useEffect } from 'react'

interface WakeLockSentinelLike {
  release: () => Promise<void>
  released?: boolean
}

interface WakeLockNavigator {
  wakeLock?: { request: (type: 'screen') => Promise<WakeLockSentinelLike> }
}

export function useWakeLock(active: boolean): void {
  useEffect(() => {
    const api = (navigator as Navigator & WakeLockNavigator).wakeLock
    if (!active || !api) return

    let sentinel: WakeLockSentinelLike | null = null
    let cancelled = false

    const acquire = async () => {
      if (document.visibilityState !== 'visible' || (sentinel && !sentinel.released)) return
      try {
        const lock = await api.request('screen')
        if (cancelled) void lock.release()
        else sentinel = lock
      } catch {
        /* refused or unsupported — the screen keeps its own timer */
      }
    }
    const onVisibility = () => void acquire()

    void acquire()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisibility)
      if (sentinel && !sentinel.released) void sentinel.release().catch(() => {})
    }
  }, [active])
}
