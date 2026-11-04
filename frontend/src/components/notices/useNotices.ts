/**
 * Notice queue state for the dashboard.
 *
 * A notice is keyed rather than merely appended: pushing the same key again
 * replaces that notice in place and lifts it to the front, so repeated events
 * ("paused", "reconnecting") never stack into a wall of duplicate cards.
 * Non-sticky notices dismiss themselves after a short ttl; sticky ones stay
 * until they are dismissed or replaced.  The queue is capped, and pressure is
 * taken off old transient notices before a sticky one is ever dropped.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

export type NoticeTone = 'info' | 'success' | 'warning' | 'error'

export interface NoticeAction {
  label: string
  onAction: () => void
}

export interface Notice {
  /** One notice per key; pushing the same key replaces it in place. */
  key: string
  tone: NoticeTone
  title: string
  body?: string
  action?: NoticeAction
  /** Stays until dismissed or replaced; default true for 'error', false otherwise. */
  sticky?: boolean
  /** Auto-dismiss delay for non-sticky notices; default 6000. */
  ttlMs?: number
  /** Default true. */
  dismissible?: boolean
}

export interface NoticeApi {
  /** Newest first. */
  notices: Notice[]
  push: (n: Notice) => void
  dismiss: (key: string) => void
  has: (key: string) => boolean
}

// ── Context ───────────────────────────────────────────────────────────────────

export const NoticeContext = createContext<NoticeApi | null>(null)

export function useNoticeApi(): NoticeApi {
  const api = useContext(NoticeContext)
  if (!api) {
    throw new Error('useNoticeApi must be used inside a NoticeContext provider')
  }
  return api
}

// ── Queue ─────────────────────────────────────────────────────────────────────

const DEFAULT_TTL_MS = 6000

/** Errors are failures the screen cannot recover from on its own — sticky. */
function isSticky(notice: Notice) {
  return notice.sticky ?? (notice.tone === 'error')
}

export function useNotices(max = 4): NoticeApi {
  const [notices, setNotices] = useState<Notice[]>([])

  // The ref is the source of truth for add/remove.  Reading it instead of the
  // state closure keeps push/dismiss/has referentially stable across renders.
  const noticesRef = useRef<Notice[]>([])
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  const maxRef = useRef(max)

  useEffect(() => {
    maxRef.current = max
  }, [max])

  const clearTimer = useCallback((key: string) => {
    const id = timersRef.current.get(key)
    if (id !== undefined) {
      clearTimeout(id)
      timersRef.current.delete(key)
    }
  }, [])

  const commit = useCallback((next: Notice[]) => {
    noticesRef.current = next
    setNotices(next)
  }, [])

  const remove = useCallback(
    (key: string) => {
      clearTimer(key)
      // Dismissing what is not showing is routine (effects clear a state that
      // has already ended), and must not cost a render.
      if (!noticesRef.current.some((notice) => notice.key === key)) return
      commit(noticesRef.current.filter((notice) => notice.key !== key))
    },
    [clearTimer, commit],
  )

  const dismiss = useCallback(
    (key: string) => {
      remove(key)
    },
    [remove],
  )

  const schedule = useCallback(
    (notice: Notice) => {
      clearTimer(notice.key)
      if (isSticky(notice)) return

      const id = setTimeout(() => {
        timersRef.current.delete(notice.key)
        commit(noticesRef.current.filter((entry) => entry.key !== notice.key))
      }, notice.ttlMs ?? DEFAULT_TTL_MS)
      timersRef.current.set(notice.key, id)
    },
    [clearTimer, commit],
  )

  const push = useCallback(
    (input: Notice) => {
      const key = input.key.trim()
      const title = input.title.trim()

      if (!key || !title) {
        if (!key) console.warn('[notices] push ignored: notice key is empty')
        if (!title) console.warn('[notices] push ignored: notice title is empty')
        return
      }

      const notice: Notice = { ...input, key, title }
      const next: Notice[] = [
        notice,
        ...noticesRef.current.filter((entry) => entry.key !== key),
      ]

      // Drop from the tail — the oldest — but spare sticky notices while any
      // transient notice is still expendable.
      const limit = Math.max(0, maxRef.current)
      while (next.length > limit) {
        let dropAt = next.length - 1
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (!isSticky(next[i])) {
            dropAt = i
            break
          }
        }
        const [dropped] = next.splice(dropAt, 1)
        clearTimer(dropped.key)
      }

      commit(next)
      if (next.some((entry) => entry.key === key)) schedule(notice)
    },
    [clearTimer, commit, schedule],
  )

  const has = useCallback(
    (key: string) => noticesRef.current.some((notice) => notice.key === key),
    [],
  )

  useEffect(() => {
    const timers = timersRef.current
    return () => {
      timers.forEach((id) => clearTimeout(id))
      timers.clear()
    }
  }, [])

  return { notices, push, dismiss, has }
}
