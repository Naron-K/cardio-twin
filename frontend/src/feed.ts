/**
 * The feed lives in the query string, so a link can name a recorded day as well
 * as a screen.  Parsing is kept here, apart from the hook and the app, because
 * a URL is untrusted input: every value is checked before it can reach the
 * WebSocket URL.
 *
 *   ?source=replay&subject=s2&date=2025-04-03&speed=600
 *
 * A simulated feed carries no parameters at all, which is exactly what the
 * dashboard used before replays existed.
 */
import type { FeedRequest } from './hooks/useCardioStream'

const REPLAY_KEYS = ['source', 'subject', 'date', 'speed'] as const

const SUBJECT_RE = /^[a-z0-9_]{1,32}$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/**
 * A speed only says how fast to play the day; it is not part of which day is
 * being played.  An absent or unreadable value therefore falls back to the
 * default instead of discarding an otherwise valid replay request.
 */
function speedFrom(raw: string | null): number {
  if (raw === null || raw.trim() === '') return 60
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return 60
  const speed = Number(text)
  return Number.isSafeInteger(speed) && speed > 0 ? speed : 60
}

/** The feed the URL asks for, or the simulated feed when anything is unusable. */
export function feedFromSearch(search: string): FeedRequest {
  try {
    const query = new URLSearchParams(search)
    if (query.get('source') !== 'replay') return { source: 'simulated' }

    const subject = query.get('subject') ?? ''
    const date = query.get('date') ?? ''
    if (!SUBJECT_RE.test(subject)) return { source: 'simulated' }
    if (!DATE_RE.test(date)) return { source: 'simulated' }

    return { source: 'replay', subject, date, speed: speedFrom(query.get('speed')) }
  } catch {
    // A malformed query string must not stop the dashboard from drawing.
    return { source: 'simulated' }
  }
}

/**
 * `search` with the feed parameters replaced, every other parameter left in
 * place.  Simulated removes them, so a link back to live data stays short.
 */
export function feedToSearch(feed: FeedRequest, search: string): string {
  let query: URLSearchParams
  try {
    query = new URLSearchParams(search)
  } catch {
    query = new URLSearchParams()
  }

  for (const key of REPLAY_KEYS) query.delete(key)

  if (feed.source === 'replay') {
    query.set('source', 'replay')
    query.set('subject', feed.subject)
    query.set('date', feed.date)
    query.set('speed', String(feed.speed))
  }

  const text = query.toString()
  return text ? `?${text}` : ''
}
