/**
 * dayView — the pure arithmetic behind the Day form.
 *
 * The whole endpoint is untrusted input: every field is checked before a
 * screen reads it, and a malformed summary throws with the field that was
 * wrong rather than drawing a plausible-looking lie.  The drawing helpers
 * keep missing minutes missing: a gap splits a run, a lone reading stays a
 * dot, and a bin with no readings produces no point at all.
 *
 * Nothing here imports React or the DOM, so the rules that decide what the
 * chart draws can be checked directly.
 */

export type DayVerdict =
  | 'as_expected'
  | 'slightly_higher'
  | 'slightly_lower'
  | 'higher'
  | 'lower'
  | 'too_few'

export type DaySdSource = 'fitted' | 'this day' | 'default'

export interface DayPair {
  label: string
  unit: string
  measured: (number | null)[]
  modelled: (number | null)[]
}

export interface DayRate {
  attribute: string
  label: string
  unit: string
  values: (number | null)[]
}

export interface DayEvent {
  indicator: string
  group: string
  label: string
}

export interface DaySession {
  start: number
  end: number
  minutes: number
  label: string
  group: string
  group_label: string
  mean_measured: number | null
  peak_measured: number | null
  mean_modelled: number | null
  n_paired: number
  difference: number | null
  rate_totals: Record<string, number | null>
  verdict: DayVerdict
}

export interface DayKpi {
  key: string
  label: string
  value: number | null
  unit: string
  note: string
}

export interface DayModel {
  sd: number
  sd_source: DaySdSource
  fitted: boolean
  applies_to: string | null
}

export interface DaySummary {
  lamina: string
  subject: string
  /** The name to show for the subject; the id itself when the server sends none. */
  subject_label: string
  date: string
  timezone: string
  synthetic: boolean
  n_minutes: number
  pair: DayPair
  rates: DayRate[]
  events: DayEvent[]
  gaps: [number, number][]
  sessions: DaySession[]
  kpis: DayKpi[]
  summary: string
  model: DayModel
}

export interface DayPoint {
  m: number
  v: number
}

export type VerdictTone = 'ok' | 'slight' | 'off' | 'none'

const VERDICTS: readonly DayVerdict[] = [
  'as_expected',
  'slightly_higher',
  'slightly_lower',
  'higher',
  'lower',
  'too_few',
]

const SD_SOURCES: readonly DaySdSource[] = ['fitted', 'this day', 'default']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function bad(field: string, expected: string): never {
  throw new Error(`day summary: ${field} ${expected}`)
}

function fieldPath(path: string, key: string): string {
  return path ? `${path}.${key}` : key
}

function readString(
  source: Record<string, unknown>,
  key: string,
  path: string,
): string {
  const value = source[key]
  if (typeof value !== 'string') bad(fieldPath(path, key), 'must be a string')
  return value
}

function readBoolean(
  source: Record<string, unknown>,
  key: string,
  path: string,
): boolean {
  const value = source[key]
  if (typeof value !== 'boolean') bad(fieldPath(path, key), 'must be a boolean')
  return value
}

function readNumber(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    bad(fieldPath(path, key), 'must be a finite number')
  }
  return value
}

function readInteger(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number {
  const value = source[key]
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    !Number.isInteger(value) ||
    value < 0
  ) {
    bad(fieldPath(path, key), 'must be a non-negative integer')
  }
  return value
}

function readNullableNumber(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number | null {
  const value = source[key]
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    bad(fieldPath(path, key), 'must be a finite number or null')
  }
  return value
}

function readNullableString(
  source: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  const value = source[key]
  if (value === null) return null
  if (typeof value !== 'string') {
    bad(fieldPath(path, key), 'must be a string or null')
  }
  return value
}

function readNullableNumbers(
  source: Record<string, unknown>,
  key: string,
  path: string,
  length: number,
): (number | null)[] {
  const value = source[key]
  const name = fieldPath(path, key)
  if (!Array.isArray(value)) bad(name, 'must be an array')
  if (value.length !== length) bad(name, `must have ${length} entries`)

  return value.map((entry, index) => {
    if (entry === null) return null
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      bad(`${name}[${index}]`, 'must be a finite number or null')
    }
    return entry
  })
}

function readVerdict(value: unknown, path: string): DayVerdict {
  if (
    typeof value !== 'string' ||
    !(VERDICTS as readonly string[]).includes(value)
  ) {
    bad(path, `must be one of ${VERDICTS.join(', ')}`)
  }
  return value as DayVerdict
}

function readSdSource(value: unknown, path: string): DaySdSource {
  if (
    typeof value !== 'string' ||
    !(SD_SOURCES as readonly string[]).includes(value)
  ) {
    bad(path, `must be one of ${SD_SOURCES.join(', ')}`)
  }
  return value as DaySdSource
}

function readPair(value: unknown, length: number): DayPair {
  if (!isRecord(value)) bad('pair', 'must be an object')
  return {
    label: readString(value, 'label', 'pair'),
    unit: readString(value, 'unit', 'pair'),
    measured: readNullableNumbers(value, 'measured', 'pair', length),
    modelled: readNullableNumbers(value, 'modelled', 'pair', length),
  }
}

function readRates(value: unknown, length: number): DayRate[] {
  if (!Array.isArray(value)) bad('rates', 'must be an array')
  return value.map((entry, index) => {
    if (!isRecord(entry)) bad(`rates[${index}]`, 'must be an object')
    return {
      attribute: readString(entry, 'attribute', `rates[${index}]`),
      label: readString(entry, 'label', `rates[${index}]`),
      unit: readString(entry, 'unit', `rates[${index}]`),
      values: readNullableNumbers(entry, 'values', `rates[${index}]`, length),
    }
  })
}

function readEvents(value: unknown): DayEvent[] {
  if (!Array.isArray(value)) bad('events', 'must be an array')
  return value.map((entry, index) => {
    if (!isRecord(entry)) bad(`events[${index}]`, 'must be an object')
    return {
      indicator: readString(entry, 'indicator', `events[${index}]`),
      group: readString(entry, 'group', `events[${index}]`),
      label: readString(entry, 'label', `events[${index}]`),
    }
  })
}

function readGaps(value: unknown): [number, number][] {
  if (!Array.isArray(value)) bad('gaps', 'must be an array')
  return value.map((entry, index) => {
    if (!Array.isArray(entry) || entry.length !== 2) {
      bad(`gaps[${index}]`, 'must be a [start, end] pair')
    }
    const [start, end] = entry
    if (typeof start !== 'number' || !Number.isFinite(start)) {
      bad(`gaps[${index}][0]`, 'must be a finite number')
    }
    if (typeof end !== 'number' || !Number.isFinite(end)) {
      bad(`gaps[${index}][1]`, 'must be a finite number')
    }
    return [start, end]
  })
}

function readRateTotals(value: unknown, path: string): Record<string, number | null> {
  if (!isRecord(value)) bad(path, 'must be an object')
  const totals: Record<string, number | null> = {}
  for (const [key, raw] of Object.entries(value)) {
    if (raw !== null && (typeof raw !== 'number' || !Number.isFinite(raw))) {
      bad(`${path}.${key}`, 'must be a finite number or null')
    }
    totals[key] = raw === null ? null : (raw as number)
  }
  return totals
}

function readSessions(value: unknown): DaySession[] {
  if (!Array.isArray(value)) bad('sessions', 'must be an array')
  return value.map((entry, index) => {
    const path = `sessions[${index}]`
    if (!isRecord(entry)) bad(path, 'must be an object')
    return {
      start: readInteger(entry, 'start', path),
      end: readInteger(entry, 'end', path),
      minutes: readInteger(entry, 'minutes', path),
      label: readString(entry, 'label', path),
      group: readString(entry, 'group', path),
      group_label: readString(entry, 'group_label', path),
      mean_measured: readNullableNumber(entry, 'mean_measured', path),
      peak_measured: readNullableNumber(entry, 'peak_measured', path),
      mean_modelled: readNullableNumber(entry, 'mean_modelled', path),
      n_paired: readInteger(entry, 'n_paired', path),
      difference: readNullableNumber(entry, 'difference', path),
      rate_totals: readRateTotals(entry.rate_totals, `${path}.rate_totals`),
      verdict: readVerdict(entry.verdict, `${path}.verdict`),
    }
  })
}

function readKpis(value: unknown): DayKpi[] {
  if (!Array.isArray(value)) bad('kpis', 'must be an array')
  return value.map((entry, index) => {
    const path = `kpis[${index}]`
    if (!isRecord(entry)) bad(path, 'must be an object')
    return {
      key: readString(entry, 'key', path),
      label: readString(entry, 'label', path),
      value: readNullableNumber(entry, 'value', path),
      unit: readString(entry, 'unit', path),
      note: readString(entry, 'note', path),
    }
  })
}

function readModel(value: unknown): DayModel {
  if (!isRecord(value)) bad('model', 'must be an object')
  const sd = readNumber(value, 'sd', 'model')
  if (sd < 0) bad('model.sd', 'must not be negative')
  return {
    sd,
    sd_source: readSdSource(value.sd_source, 'model.sd_source'),
    fitted: readBoolean(value, 'fitted', 'model'),
    applies_to: readNullableString(value, 'applies_to', 'model'),
  }
}

/**
 * A day summary with every field checked.  Throws naming the first field
 * that is missing, wrongly typed, or the wrong length.
 */
export function parseDaySummary(raw: unknown): DaySummary {
  if (!isRecord(raw)) bad('the response', 'must be an object')
  const nMinutes = readInteger(raw, 'n_minutes', '')

  const subject = readString(raw, 'subject', '')
  const label = raw.subject_label
  return {
    lamina: readString(raw, 'lamina', ''),
    subject,
    subject_label: typeof label === 'string' && label.trim() !== '' ? label.trim() : subject,
    date: readString(raw, 'date', ''),
    timezone: readString(raw, 'timezone', ''),
    synthetic: readBoolean(raw, 'synthetic', ''),
    n_minutes: nMinutes,
    pair: readPair(raw.pair, nMinutes),
    rates: readRates(raw.rates, nMinutes),
    events: readEvents(raw.events),
    gaps: readGaps(raw.gaps),
    sessions: readSessions(raw.sessions),
    kpis: readKpis(raw.kpis),
    summary: readString(raw, 'summary', ''),
    model: readModel(raw.model),
  }
}

/**
 * Consecutive minutes joined, a gap splits, an isolated reading is a run of
 * one.  A non-number or non-finite value is missing, never a point.
 */
export function measuredRuns(
  values: readonly (number | null)[],
): DayPoint[][] {
  if (!Array.isArray(values)) return []

  const runs: DayPoint[][] = []
  let run: DayPoint[] = []

  for (let m = 0; m < values.length; m += 1) {
    const value = values[m]
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      if (run.length > 0) {
        runs.push(run)
        run = []
      }
      continue
    }
    run.push({ m, v: value })
  }

  if (run.length > 0) runs.push(run)
  return runs
}

/**
 * Per-minute inside every session and `margin` minutes either side; elsewhere
 * one point per `bin`-minute bin at the bin's centre holding the mean of its
 * non-null minutes.  An all-null bin produces no point, and every missing
 * stretch splits the run.
 */
export function modelledDisplay(
  modelled: readonly (number | null)[],
  sessions: readonly { start: number; end: number }[],
  margin = 30,
  bin = 10,
): DayPoint[][] {
  if (!Array.isArray(modelled)) return []

  const length = modelled.length
  const safeBin =
    typeof bin === 'number' && Number.isFinite(bin) && bin > 0
      ? Math.floor(bin)
      : 10
  const safeMargin =
    typeof margin === 'number' && Number.isFinite(margin) && margin >= 0
      ? margin
      : 0

  const windows = Array.isArray(sessions)
    ? sessions
        .filter(
          (session) =>
            session != null &&
            typeof session.start === 'number' &&
            Number.isFinite(session.start) &&
            typeof session.end === 'number' &&
            Number.isFinite(session.end),
        )
        .map(
          (session) =>
            [session.start - safeMargin, session.end + safeMargin] as const,
        )
    : []

  const inMinuteWindow = (minute: number) =>
    windows.some(([start, end]) => minute >= start && minute < end)

  const slots: { m: number; v: number | null }[] = []

  for (let minute = 0; minute < length; minute += 1) {
    if (!inMinuteWindow(minute)) continue
    const value = modelled[minute]
    slots.push({
      m: minute,
      v: typeof value === 'number' && Number.isFinite(value) ? value : null,
    })
  }

  for (let start = 0; start < length; start += safeBin) {
    const end = Math.min(start + safeBin, length)

    let overlaps = false
    for (let minute = start; minute < end; minute += 1) {
      if (inMinuteWindow(minute)) {
        overlaps = true
        break
      }
    }
    if (overlaps) continue

    let total = 0
    let count = 0
    for (let minute = start; minute < end; minute += 1) {
      const value = modelled[minute]
      if (typeof value === 'number' && Number.isFinite(value)) {
        total += value
        count += 1
      }
    }

    slots.push({
      m: start + (end - start) / 2,
      v: count > 0 ? total / count : null,
    })
  }

  slots.sort((a, b) => a.m - b.m)

  const runs: DayPoint[][] = []
  let run: DayPoint[] = []
  for (const slot of slots) {
    if (slot.v === null) {
      if (run.length > 0) {
        runs.push(run)
        run = []
      }
      continue
    }
    run.push({ m: slot.m, v: slot.v })
  }

  if (run.length > 0) runs.push(run)
  return runs
}

/**
 * The sum of each `bin` minutes of a per-minute series.  A bin with no
 * readings at all is null, never zero: zero would claim the person did
 * nothing where in truth the watch said nothing.
 */
export function binSums(
  values: readonly (number | null)[],
  bin = 10,
): (number | null)[] {
  if (!Array.isArray(values)) return []

  const safeBin =
    typeof bin === 'number' && Number.isFinite(bin) && bin > 0
      ? Math.floor(bin)
      : 10

  const sums: (number | null)[] = []
  for (let start = 0; start < values.length; start += safeBin) {
    const end = Math.min(start + safeBin, values.length)
    let total = 0
    let count = 0
    for (let minute = start; minute < end; minute += 1) {
      const value = values[minute]
      if (typeof value === 'number' && Number.isFinite(value)) {
        total += value
        count += 1
      }
    }
    sums.push(count > 0 ? total : null)
  }

  return sums
}

/**
 * HH:MM from minutes since local midnight.  1440 is "24:00"; anything
 * negative, past the day, or not a finite number is empty.
 */
export function clock(minute: number): string {
  if (typeof minute !== 'number' || !Number.isFinite(minute)) return ''
  const rounded = Math.round(minute)
  if (rounded < 0 || rounded > 1440) return ''

  const hours = Math.floor(rounded / 60)
  const minutes = rounded % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export interface VerdictSubject {
  verdict?: DayVerdict
  difference?: number | null
  n_paired?: number
}

/**
 * The verdict as a number, coloured at the three levels of DAY_VIEW_PLAN.md
 * section 3: "+7.4 bpm · 0.7 SD", or "n < 3" with too few paired minutes.
 * The backend's own level is trusted when present; otherwise it is derived
 * from the difference, the pair count and the model's usual error.
 */
export function verdictText(
  session: VerdictSubject,
  sd: number,
  unit: string,
): { tone: VerdictTone; text: string } {
  const difference =
    typeof session.difference === 'number' && Number.isFinite(session.difference)
      ? session.difference
      : null
  const nPaired =
    typeof session.n_paired === 'number' && Number.isFinite(session.n_paired)
      ? session.n_paired
      : 0

  const declared =
    session.verdict !== undefined &&
    (VERDICTS as readonly string[]).includes(session.verdict)
      ? session.verdict
      : null

  let level: DayVerdict
  if (declared !== null) {
    level = declared
  } else if (difference === null || nPaired < 3) {
    level = 'too_few'
  } else {
    const magnitude = Math.abs(difference)
    const usual =
      typeof sd === 'number' && Number.isFinite(sd) && sd > 0 ? sd : 0
    if (magnitude === 0 || magnitude < usual / 2) {
      level = 'as_expected'
    } else if (magnitude <= usual) {
      level = difference > 0 ? 'slightly_higher' : 'slightly_lower'
    } else {
      level = difference > 0 ? 'higher' : 'lower'
    }
  }

  if (level === 'too_few' || difference === null) {
    return { tone: 'none', text: 'n < 3' }
  }

  // Measured minus modelled, signed, then the same distance in model SDs.
  const sign = difference > 0 ? '+' : difference < 0 ? '−' : '±'
  const suffix = unit ? ` ${unit}` : ''
  const usual = typeof sd === 'number' && Number.isFinite(sd) && sd > 0 ? sd : 0
  const inSd = usual > 0 ? ` · ${(Math.abs(difference) / usual).toFixed(1)} SD` : ''
  const text = `${sign}${Math.abs(difference).toFixed(1)}${suffix}${inSd}`

  if (level === 'as_expected') return { tone: 'ok', text }
  const slightly = level === 'slightly_higher' || level === 'slightly_lower'
  return { tone: slightly ? 'slight' : 'off', text }
}

/**
 * The colour slot for a session group: its index in the day's declared
 * events, or -1 for "other" and anything the day does not declare.
 */
export function groupColourIndex(
  day: Pick<DaySummary, 'events'>,
  group: string,
): number {
  if (group === 'other' || !day || !Array.isArray(day.events)) return -1
  return day.events.findIndex(
    (event) => event != null && event.group === group,
  )
}

// ── Playback ─────────────────────────────────────────────────────────────────
// The whole day is already on the page; playing it only moves a cursor across
// it, so nothing here asks the server for anything.

/** Playback speeds, as on a replay: ×60 is one minute of the day a second. */
export const PLAY_SPEEDS = [60, 600, 3600] as const

/**
 * The cursor `dtMs` later at `speed`, held inside [0, n].  A non-finite or
 * negative input leaves the cursor where it was.
 */
export function advanceMinute(
  minute: number,
  speed: number,
  dtMs: number,
  n: number,
): number {
  const end = Number.isFinite(n) && n > 0 ? n : 0
  const start = Number.isFinite(minute) ? Math.min(end, Math.max(0, minute)) : 0
  if (!Number.isFinite(speed) || speed <= 0) return start
  if (!Number.isFinite(dtMs) || dtMs <= 0) return start
  return Math.min(end, start + (speed / 60) * (dtMs / 1000))
}

/**
 * The latest value at or before `minute`, looking back at most `lookback`
 * minutes, so a reading a moment old still shows while an hour-old one
 * does not.  Null when there is none.
 */
export function valueAt(
  values: readonly (number | null)[],
  minute: number,
  lookback = 5,
): number | null {
  if (!Array.isArray(values) || !Number.isFinite(minute)) return null
  const at = Math.min(values.length - 1, Math.floor(minute))
  const stop = Math.max(0, at - Math.max(0, Math.floor(lookback)))
  for (let index = at; index >= stop; index -= 1) {
    const value = values[index]
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return null
}

/** The running total of `values` up to and including `minute`; null if none. */
export function totalTo(
  values: readonly (number | null)[],
  minute: number,
): number | null {
  if (!Array.isArray(values) || !Number.isFinite(minute) || minute < 0) return null
  const at = Math.min(values.length - 1, Math.floor(minute))
  let total = 0
  let seen = false
  for (let index = 0; index <= at; index += 1) {
    const value = values[index]
    if (typeof value === 'number' && Number.isFinite(value)) {
      total += value
      seen = true
    }
  }
  return seen ? total : null
}

/**
 * The session the cursor is in, else the last one it has passed, else -1:
 * what the enlarged chart follows while the day plays.
 */
export function sessionAt(
  sessions: readonly Pick<DaySession, 'start' | 'end'>[],
  minute: number,
): number {
  if (!Array.isArray(sessions) || !Number.isFinite(minute)) return -1
  let passed = -1
  for (let index = 0; index < sessions.length; index += 1) {
    const session = sessions[index]
    if (minute >= session.start && minute < session.end) return index
    if (session.start <= minute) passed = index
  }
  return passed
}
