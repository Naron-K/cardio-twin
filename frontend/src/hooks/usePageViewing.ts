/**
 * usePageViewing — is this page on anyone's screen?
 *
 * A dashboard in a background tab, or on a display whose screen has gone off,
 * still streams ten frames a second that nobody sees. useIdle only catches that
 * after 15 minutes without a touch, and a hidden tab's timers run late. So once
 * the page has been hidden for a short while the dashboard closes its stream,
 * and the moment it is visible again it reconnects and re-applies the inputs.
 *
 * The grace period is there so glancing at another tab does not restart the
 * session, which would also restart the feedback loop's learning.
 */
import { useEffect, useState } from 'react'

export const HIDDEN_GRACE_MS = 30_000

export function usePageViewing(graceMs = HIDDEN_GRACE_MS): boolean {
  const [viewing, setViewing] = useState(() => document.visibilityState !== 'hidden')

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const clear = () => {
      if (timer) clearTimeout(timer)
      timer = null
    }
    const leaveSoon = () => {
      clear()
      timer = setTimeout(() => setViewing(false), graceMs)
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        leaveSoon()
      } else {
        clear()
        setViewing(true)
      }
    }

    if (document.visibilityState === 'hidden') leaveSoon()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clear()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [graceMs])

  return viewing
}
