/**
 * trendWindow — the pure arithmetic behind TrendGrid.
 *
 * Three questions, all answerable without React or the DOM: where a series
 * breaks into runs of real readings, which samples fall inside the chosen
 * replay window, and what clock time an ISO timestamp names locally.  Every
 * function treats malformed input as missing data rather than throwing, so a
 * bad tick can only leave a gap — never a point the model did not produce.
 */

/**
 * The windows a replay can show.  The two durations are fixed; `day` takes its
 * end from the feed's reported duration.
 */
export type WindowKind = '30m' | '3h' | 'day'

/** Inclusive x interval, in seconds of the recorded day. */
export interface WindowBounds {
  lo: number
  hi: number
}

/**
 * One plotted sample.  `x` is the tick index for a live feed and the feed's
 * position in seconds for a replay.  A missing, non-finite or stale `value`
 * is a gap, not zero.
 */
export interface TrendSample {
  x: number
  value?: number
  stale?: boolean
  /** The feed's ISO timestamp, kept verbatim so the label is its local time. */
  dataTime?: string
}

/** A replay with no declared duration still covers a nominal 24 hours. */
export const DAY_SECONDS = 86_400

const WINDOW_SECONDS: Record<'30m' | '3h', number> = {
  '30m': 30 * 60,
  '3h': 3 * 60 * 60,
}

/**
 * The interval a window covers.  `null` means there is no real x to anchor
 * it to, so nothing should be drawn rather than a window guessed from nothing.
 */
export function windowBounds(
  kind: WindowKind,
  latestX: number | undefined,
  durationS?: number,
): WindowBounds | null {
  if (kind === 'day') {
    const duration =
      typeof durationS === 'number' && Number.isFinite(durationS) && durationS > 0
        ? durationS
        : DAY_SECONDS
    return { lo: 0, hi: duration }
  }

  if (kind !== '30m' && kind !== '3h') return null
  if (typeof latestX !== 'number' || !Number.isFinite(latestX)) return null

  return { lo: latestX - WINDOW_SECONDS[kind], hi: latestX }
}

/**
 * A window edge as HH:MM, from seconds since local midnight: "00:00" to
 * "24:00".  An edge is a position, not a reading, so it has no ISO string of
 * its own to quote.  On the two daylight-saving days a year the clock after
 * the change is an hour off, because elapsed seconds are not wall time; the
 * points themselves are still placed by elapsed time and stay correct.
 * Negative or malformed input is "" so a window reaching back before
 * midnight shows no label rather than an invented one.
 */
export function clockOfSeconds(seconds: number | undefined | null): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return ''
  const minutes = Math.round(seconds / 60)
  const hh = Math.floor(minutes / 60)
  const mm = minutes % 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/**
 * Samples whose x lies inside the window, inclusive at both edges.  A sample
 * with a malformed x is dropped rather than placed at an edge.
 */
export function ticksInWindow<T extends { x: number }>(
  items: readonly T[],
  bounds: WindowBounds | null,
): T[] {
  if (!Array.isArray(items) || !bounds) return []
  const { lo, hi } = bounds
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return []

  // A caller that reversed the edges still described one interval.
  const low = Math.min(lo, hi)
  const high = Math.max(lo, hi)

  return items.filter(
    (item) =>
      item != null &&
      typeof item.x === 'number' &&
      Number.isFinite(item.x) &&
      item.x >= low &&
      item.x <= high,
  )
}

/**
 * Split a series wherever the attribute has no real reading.  Each returned
 * run is unbroken data: a run of one is a lone reading, not a line to
 * nowhere.
 */
export function splitRuns(samples: readonly TrendSample[]): TrendSample[][] {
  if (!Array.isArray(samples)) return []

  const runs: TrendSample[][] = []
  let run: TrendSample[] = []

  for (const sample of samples) {
    const real =
      sample != null &&
      typeof sample.x === 'number' &&
      Number.isFinite(sample.x) &&
      typeof sample.value === 'number' &&
      Number.isFinite(sample.value) &&
      !sample.stale

    if (!real) {
      if (run.length > 0) {
        runs.push(run)
        run = []
      }
      continue
    }

    run.push(sample)
  }

  if (run.length > 0) runs.push(run)
  return runs
}

/**
 * The local clock time an ISO timestamp names, as HH:MM.  This takes the
 * literal time part and never converts time zones, because the recorded day
 * was written in the recorder's local time.  Anything malformed is empty.
 */
export function formatClock(iso: string | undefined | null): string {
  if (typeof iso !== 'string') return ''

  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!match) return ''

  const [, , month, day, hours, minutes] = match
  const m = Number(month)
  const d = Number(day)
  const h = Number(hours)
  const min = Number(minutes)

  if (m < 1 || m > 12 || d < 1 || d > 31 || h > 23 || min > 59) return ''

  return `${hours}:${minutes}`
}
