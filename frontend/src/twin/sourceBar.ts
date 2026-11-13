/**
 * sourceBar — the pure half of the data-source bar.
 *
 * `/api/sources` and every replay tick are untrusted input: a value is used
 * only after its type has been checked, and a malformed payload reads as an
 * offer with nothing in it rather than throwing while a screen is drawn.
 *
 * Nothing here imports React or the DOM, so the rules that decide which day a
 * replay opens on, and what the status line says, can be checked directly.
 */
import type { FeedRequest, FeedStatus } from '../hooks/useCardioStream'
import { formatClock } from './trendWindow.ts'

/** One subject's available days, newest first, and whether they are fitted. */
export interface ReplaySources {
  subjects: Record<string, string[]>
  speeds: number[]
  default_speed: number
  fitted: Record<string, boolean>
}

/** `GET /api/sources?lamina=<id>`, after every field has been checked. */
export interface SourcesResponse {
  lamina: string
  modes: string[]
  replay: ReplaySources | null
  presets: unknown[]
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const SUBJECT_RE = /^[a-z0-9_]{1,32}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function positiveInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null
}

/**
 * The recorded days, newest first, with anything that is not a date dropped.
 * Sorting is lexicographic because the format is fixed-width YYYY-MM-DD.
 */
export function datesNewestFirst(dates: unknown): string[] {
  if (!Array.isArray(dates)) return []

  const seen = new Set<string>()
  const clean: string[] = []
  for (const date of dates) {
    if (typeof date !== 'string' || !DATE_RE.test(date) || seen.has(date)) continue
    seen.add(date)
    clean.push(date)
  }
  return clean.sort((a, b) => b.localeCompare(a))
}

function parseReplay(raw: unknown): ReplaySources | null {
  if (!isRecord(raw)) return null

  const subjects: Record<string, string[]> = {}
  if (isRecord(raw.subjects)) {
    for (const [subject, dates] of Object.entries(raw.subjects)) {
      if (!SUBJECT_RE.test(subject)) continue
      const clean = datesNewestFirst(dates)
      if (clean.length > 0) subjects[subject] = clean
    }
  }

  const fitted: Record<string, boolean> = {}
  if (isRecord(raw.fitted)) {
    for (const [subject, flag] of Object.entries(raw.fitted)) {
      if (typeof flag === 'boolean') fitted[subject] = flag
    }
  }

  const speeds: number[] = []
  if (Array.isArray(raw.speeds)) {
    for (const value of raw.speeds) {
      const speed = positiveInteger(value)
      if (speed !== null && !speeds.includes(speed)) speeds.push(speed)
    }
  }

  const declared = positiveInteger(raw.default_speed)
  const default_speed = declared ?? speeds[0] ?? 60

  return { subjects, speeds, default_speed, fitted }
}

/** A sources response with every usable field kept and every wrong type dropped. */
export function parseSources(raw: unknown): SourcesResponse {
  if (!isRecord(raw)) {
    return { lamina: '', modes: [], replay: null, presets: [] }
  }

  const modes = Array.isArray(raw.modes)
    ? raw.modes.filter((mode): mode is string => typeof mode === 'string')
    : []

  return {
    lamina: typeof raw.lamina === 'string' ? raw.lamina : '',
    modes,
    replay: parseReplay(raw.replay),
    presets: Array.isArray(raw.presets) ? raw.presets : [],
  }
}

/**
 * The feed the Replay choice should open.
 *
 * An existing replay is kept when the response still offers its subject and
 * date; otherwise the first subject's newest day is opened at the response's
 * default speed. `null` means the response offers no replay at all.
 */
export function defaultReplayFeed(
  sources: unknown,
  current?: FeedRequest | null,
): FeedRequest | null {
  const replay = parseSources(sources).replay
  if (!replay) return null

  if (current?.source === 'replay') {
    const offered = replay.subjects[current.subject]
    if (offered && offered.includes(current.date)) return current
  }

  const subject = Object.keys(replay.subjects)[0]
  if (!subject) return null

  const dates = replay.subjects[subject]
  if (!dates || dates.length === 0) return null

  return {
    source: 'replay',
    subject,
    date: dates[0],
    speed: replay.default_speed,
  }
}

/**
 * The line under the replay controls, built only from fields that arrived with
 * the type they need. The clock is the literal time part of `dataTime`; the
 * recorded day is never converted between time zones.
 */
export function statusLine(latest?: FeedStatus | null): string {
  if (!isRecord(latest)) return ''
  if (latest.ended === true) return 'Day finished'

  const parts: string[] = []

  const clock = formatClock(latest.dataTime as string | undefined)
  const position = latest.positionS
  const duration = latest.durationS
  const percent =
    typeof position === 'number' &&
    Number.isFinite(position) &&
    typeof duration === 'number' &&
    Number.isFinite(duration) &&
    duration > 0
      ? `${Math.round(Math.max(0, Math.min(100, (position / duration) * 100)))}% of the day`
      : null

  if (clock && percent) parts.push(`${clock} · ${percent}`)
  else if (clock) parts.push(clock)
  else if (percent) parts.push(percent)

  if (latest.coefficients === 'fitted') parts.push('fitted coefficients')
  else if (latest.coefficients === 'declared defaults') parts.push('declared defaults')

  if (latest.synthetic === true) parts.push('synthetic day')

  return parts.join(' · ')
}
