/**
 * Recorded days on offer, and which one the URL asks for.
 *
 * `/api/sources` and the query string are untrusted input: a value is used
 * only after its type has been checked, and a malformed payload reads as an
 * offer with nothing in it rather than throwing while the page is drawn.
 * Nothing here imports React or the DOM, so it is checked directly by
 * scripts/sources-check.ts.
 */

/**
 * Each subject's recorded days, newest first, whether it is fitted, and the
 * name to show for it.  A subject id is a folder name; the screen shows the
 * label and never the id.
 */
export interface ReplaySources {
  subjects: Record<string, string[]>
  fitted: Record<string, boolean>
  labels: Record<string, string>
}

/** `GET /api/sources?lamina=<id>`, after every field has been checked. */
export interface SourcesResponse {
  lamina: string
  replay: ReplaySources | null
}

/** One recorded day: whose, and which. */
export interface DayRoute {
  subject: string
  date: string
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const SUBJECT_RE = /^[a-z0-9_]{1,32}$/
/** The backend refuses a longer label; anything longer here is not one. */
const LABEL_MAX = 40

/** Parameters an older link may carry; they name nothing on this page. */
const ROUTE_KEYS = ['source', 'subject', 'date', 'speed', 'preset'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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

  // Days on which nothing observed was measured have nothing to draw, so
  // they are left out of the picker; a subject left with no day goes too.
  const empty = isRecord(raw.no_readings) ? raw.no_readings : {}

  const subjects: Record<string, string[]> = {}
  if (isRecord(raw.subjects)) {
    for (const [subject, dates] of Object.entries(raw.subjects)) {
      if (!SUBJECT_RE.test(subject)) continue
      const skip = new Set(datesNewestFirst(empty[subject]))
      const clean = datesNewestFirst(dates).filter((date) => !skip.has(date))
      if (clean.length > 0) subjects[subject] = clean
    }
  }

  const fitted: Record<string, boolean> = {}
  if (isRecord(raw.fitted)) {
    for (const [subject, flag] of Object.entries(raw.fitted)) {
      if (typeof flag === 'boolean') fitted[subject] = flag
    }
  }

  // Every offered subject gets a label: the server's when it is a usable
  // string, else the id, so a picker never shows an empty option.
  const given = isRecord(raw.labels) ? raw.labels : {}
  const labels: Record<string, string> = {}
  for (const subject of Object.keys(subjects)) {
    const label = given[subject]
    labels[subject] =
      typeof label === 'string' && label.trim() !== '' && label.length <= LABEL_MAX
        ? label.trim()
        : subject
  }

  return { subjects, fitted, labels }
}

/** The name to show for a subject: its label when one is on offer, else its id. */
export function subjectLabel(sources: SourcesResponse | null, subject: string): string {
  return sources?.replay?.labels[subject] ?? subject
}

/** A sources response with every usable field kept and every wrong type dropped. */
export function parseSources(raw: unknown): SourcesResponse {
  if (!isRecord(raw)) return { lamina: '', replay: null }
  return {
    lamina: typeof raw.lamina === 'string' ? raw.lamina : '',
    replay: parseReplay(raw.replay),
  }
}

/** The day the query string names, or null when it names none validly. */
export function routeFromSearch(search: string): DayRoute | null {
  try {
    const query = new URLSearchParams(search)
    const subject = query.get('subject') ?? ''
    const date = query.get('date') ?? ''
    if (!SUBJECT_RE.test(subject) || !DATE_RE.test(date)) return null
    return { subject, date }
  } catch {
    return null
  }
}

/**
 * `search` with the day written in and every older feed parameter removed;
 * anything unrelated (scale, for the display profile) stays.
 */
export function routeToSearch(route: DayRoute, search: string): string {
  let query: URLSearchParams
  try {
    query = new URLSearchParams(search)
  } catch {
    query = new URLSearchParams()
  }
  for (const key of ROUTE_KEYS) query.delete(key)
  query.set('subject', route.subject)
  query.set('date', route.date)
  return `?${query.toString()}`
}

/**
 * The day to open: the wanted one when it is on offer, else the same
 * subject's newest day, else the first subject's newest day.  Null when
 * nothing is on offer.
 */
export function pickDay(
  sources: SourcesResponse | null,
  wanted: DayRoute | null,
): DayRoute | null {
  const subjects = sources?.replay?.subjects ?? {}
  const names = Object.keys(subjects)
  if (names.length === 0) return null

  if (wanted && subjects[wanted.subject]) {
    const dates = subjects[wanted.subject]
    if (dates.includes(wanted.date)) return wanted
    return { subject: wanted.subject, date: dates[0] }
  }
  return { subject: names[0], date: subjects[names[0]][0] }
}

/** The recorded days either side of `date` in a newest-first list. */
export function neighbourDays(
  dates: string[],
  date: string,
): { older: string | null; newer: string | null } {
  const index = dates.indexOf(date)
  if (index < 0) return { older: null, newer: null }
  return {
    older: index + 1 < dates.length ? dates[index + 1] : null,
    newer: index > 0 ? dates[index - 1] : null,
  }
}
