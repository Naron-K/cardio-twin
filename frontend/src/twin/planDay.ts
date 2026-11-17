/**
 * planDay — the pure arithmetic behind the Plan a day editor.
 *
 * The options endpoint and the plan in the URL are untrusted input: every
 * field this module reads is checked, and a malformed response throws naming
 * the field rather than drawing a plausible-looking plan.  The editing
 * functions never mutate their input and never let a value make the plan
 * invalid: a move that would overlap another session or leave the waking
 * hours stops short and returns the sentence to show under its control.
 *
 * Nothing here imports React or the DOM, so the linking of Level and Target,
 * the overlap rules and the URL encoding are checked directly by
 * scripts/plan-check.ts.
 */
import { parseDaySummary } from './dayView.ts'
import type { DaySummary } from './dayView.ts'

export interface PlanKindSettle {
  hours: number[]
  intensities: number[]
  values: number[][]
}

export interface PlanKindIntensity {
  p10: number
  p50: number
  p90: number
  unit: string
}

export interface PlanKind {
  id: string
  label: string
  sessions: number
  minutes: number
  intensity: PlanKindIntensity
  steps_per_min: number
  settle: PlanKindSettle
}

export interface PlanRole {
  attribute: string
  label: string
  unit: string
}

export interface PlanRoles {
  intensity: PlanRole
  settles: PlanRole
  count: PlanRole
  ambient: PlanRole
  level: PlanRole
  clock: PlanRole
}

export interface PlanAwake {
  start: number
  end: number
}

export interface PlanOptionRange {
  min: number
  max: number
  default: number
  unit: string
}

export interface PlanCountRange extends PlanOptionRange {
  p10: number
  p90: number
}

export interface PlanLevelRange extends PlanOptionRange {
  recorded: [number, number] | null
}

export interface PlanDay {
  awake: PlanAwake
  ambient: PlanOptionRange
  level: PlanLevelRange
  count_outside: PlanCountRange
  settle_at: { level: number; ambient: number }
}

export interface PlanDefaultSession {
  kind: string
  start: number
  minutes: number
  intensity: number
  count: number
  target?: number
}

export interface PlanDefault {
  awake: [number, number]
  ambient: number
  level: number
  count_outside: number
  sessions: PlanDefaultSession[]
}

export interface PlanLimits {
  max_sessions: number
  session_minutes: [number, number]
  step_minutes: number
}

export interface PlanOptions {
  lamina: string
  subject: string
  subject_label: string
  applies_to: string | null
  fitted: boolean
  coefficients_applies_to: string | null
  roles: PlanRoles
  kinds: PlanKind[]
  day: PlanDay
  default_plan: PlanDefault
  projection_error: Record<string, unknown> | null
  limits: PlanLimits
  limits_text: string[]
}

export interface PlannedSessionExtras {
  start: number
  target_set: number | null
  intensity_set: number
  count_set: number
  peak_modelled: number | null
}

export interface PlannedExtras {
  projection_error: Record<string, unknown> | null
  limits_text: string[]
  sessions: PlannedSessionExtras[]
}

export interface PlanSession {
  kind: string
  start: number
  minutes: number
  intensity: number
  count: number
  countTouched: boolean
}

export interface Plan {
  awake: [number, number]
  ambient: number
  level: number
  count_outside: number
  sessions: PlanSession[]
}

/** The result of an edit: the next plan and the sentence to show under it. */
export interface PlanEdit {
  plan: Plan
  message: string
}

/** The clock hours the Day column's awake sliders offer. */
export const AWAKE_START_RANGE: readonly [number, number] = [240, 720]
export const AWAKE_END_RANGE: readonly [number, number] = [1080, 1435]
const MINUTE_STEP = 5
const OVERLAP_MESSAGE = 'Overlaps Session'
const NO_ROOM_MESSAGE = 'No free 30 min'

// ── Parsing the options endpoint ──────────────────────────────────────────────

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function bad(field: string, expected: string): never {
  throw new Error(`plan options: ${field} ${expected}`)
}

function fieldPath(path: string, key: string): string {
  return path ? `${path}.${key}` : key
}

function readRecord(
  source: Record<string, unknown>,
  key: string,
  path: string,
): Record<string, unknown> {
  const value = source[key]
  if (!isRecord(value)) bad(fieldPath(path, key), 'must be an object')
  return value
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

function readNullableString(
  source: Record<string, unknown>,
  key: string,
  path: string,
): string | null {
  const value = source[key]
  if (value === null || value === undefined) return null
  if (typeof value !== 'string') {
    bad(fieldPath(path, key), 'must be a string or null')
  }
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
  const value = readNumber(source, key, path)
  if (!Number.isInteger(value)) bad(fieldPath(path, key), 'must be an integer')
  return value
}

function readStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value)) bad(field, 'must be an array')
  return value.map((entry, index) => {
    if (typeof entry !== 'string') {
      bad(`${field}[${index}]`, 'must be a string')
    }
    return entry
  })
}

function readNumberArray(value: unknown, field: string): number[] {
  if (!Array.isArray(value)) bad(field, 'must be an array')
  return value.map((entry, index) => {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      bad(`${field}[${index}]`, 'must be a finite number')
    }
    return entry
  })
}

function readPair(value: unknown, field: string): [number, number] {
  if (!Array.isArray(value) || value.length !== 2) {
    bad(field, 'must be a [start, end] pair')
  }
  const first = value[0]
  const second = value[1]
  if (typeof first !== 'number' || !Number.isFinite(first)) {
    bad(`${field}[0]`, 'must be a finite number')
  }
  if (typeof second !== 'number' || !Number.isFinite(second)) {
    bad(`${field}[1]`, 'must be a finite number')
  }
  return [first, second]
}

function readRole(
  source: Record<string, unknown>,
  key: string,
  path: string,
): PlanRole {
  const role = readRecord(source, key, path)
  return {
    attribute: readString(role, 'attribute', fieldPath(path, key)),
    label: readString(role, 'label', fieldPath(path, key)),
    unit: readString(role, 'unit', fieldPath(path, key)),
  }
}

function readRoles(raw: unknown): PlanRoles {
  if (!isRecord(raw)) bad('roles', 'must be an object')
  return {
    intensity: readRole(raw, 'intensity', 'roles'),
    settles: readRole(raw, 'settles', 'roles'),
    count: readRole(raw, 'count', 'roles'),
    ambient: readRole(raw, 'ambient', 'roles'),
    level: readRole(raw, 'level', 'roles'),
    clock: readRole(raw, 'clock', 'roles'),
  }
}

function readSettle(raw: unknown, path: string): PlanKindSettle {
  if (!isRecord(raw)) bad(path, 'must be an object')
  const hours = readNumberArray(raw.hours, `${path}.hours`)
  if (hours.length !== 24) bad(`${path}.hours`, 'must have 24 entries')

  const intensities = readNumberArray(raw.intensities, `${path}.intensities`)
  if (intensities.length === 0) {
    bad(`${path}.intensities`, 'must have at least one entry')
  }
  for (let i = 1; i < intensities.length; i += 1) {
    if (!(intensities[i] > intensities[i - 1])) {
      bad(`${path}.intensities`, 'must be strictly increasing')
    }
  }

  if (!Array.isArray(raw.values)) bad(`${path}.values`, 'must be an array')
  if (raw.values.length !== 24) bad(`${path}.values`, 'must have 24 rows')
  const values = raw.values.map((row, index) => {
    const numbers = readNumberArray(row, `${path}.values[${index}]`)
    if (numbers.length !== intensities.length) {
      bad(
        `${path}.values[${index}]`,
        `must have ${intensities.length} entries`,
      )
    }
    return numbers
  })

  return { hours, intensities, values }
}

function readKind(raw: unknown, index: number): PlanKind {
  const path = `kinds[${index}]`
  if (!isRecord(raw)) bad(path, 'must be an object')

  const intensity = readRecord(raw, 'intensity', path)
  const p10 = readNumber(intensity, 'p10', `${path}.intensity`)
  const p50 = readNumber(intensity, 'p50', `${path}.intensity`)
  const p90 = readNumber(intensity, 'p90', `${path}.intensity`)

  return {
    id: readString(raw, 'id', path),
    label: readString(raw, 'label', path),
    sessions: readInteger(raw, 'sessions', path),
    minutes: readInteger(raw, 'minutes', path),
    intensity: {
      p10,
      p50,
      p90,
      unit: readString(intensity, 'unit', `${path}.intensity`),
    },
    steps_per_min: readNumber(raw, 'steps_per_min', path),
    settle: readSettle(raw.settle, `${path}.settle`),
  }
}

function readRange(
  source: Record<string, unknown>,
  key: string,
  path: string,
): PlanOptionRange {
  const node = readRecord(source, key, path)
  const range = {
    min: readNumber(node, 'min', fieldPath(path, key)),
    max: readNumber(node, 'max', fieldPath(path, key)),
    default: readNumber(node, 'default', fieldPath(path, key)),
    unit: readString(node, 'unit', fieldPath(path, key)),
  }
  if (range.min > range.max) {
    bad(fieldPath(path, key), 'must have min <= max')
  }
  return range
}

function readDay(raw: unknown): PlanDay {
  if (!isRecord(raw)) bad('day', 'must be an object')

  const awake = readRecord(raw, 'awake', 'day')
  const ambient = readRange(raw, 'ambient', 'day')

  const levelNode = readRecord(raw, 'level', 'day')
  const levelRange = readRange(raw, 'level', 'day')
  let recorded: [number, number] | null = null
  if (levelNode.recorded !== null && levelNode.recorded !== undefined) {
    recorded = readPair(levelNode.recorded, 'day.level.recorded')
  }

  const countNode = readRecord(raw, 'count_outside', 'day')
  const countRange = readRange(raw, 'count_outside', 'day')

  const settleAt = readRecord(raw, 'settle_at', 'day')

  return {
    awake: {
      start: readNumber(awake, 'start', 'day.awake'),
      end: readNumber(awake, 'end', 'day.awake'),
    },
    ambient,
    level: { ...levelRange, recorded },
    count_outside: {
      ...countRange,
      p10: readNumber(countNode, 'p10', 'day.count_outside'),
      p90: readNumber(countNode, 'p90', 'day.count_outside'),
    },
    settle_at: {
      level: readNumber(settleAt, 'level', 'day.settle_at'),
      ambient: readNumber(settleAt, 'ambient', 'day.settle_at'),
    },
  }
}

function readDefaultPlan(raw: unknown, kindIds: Set<string>): PlanDefault {
  if (!isRecord(raw)) bad('default_plan', 'must be an object')
  const awake = readPair(raw.awake, 'default_plan.awake')

  if (!Array.isArray(raw.sessions)) {
    bad('default_plan.sessions', 'must be an array')
  }
  const sessions = raw.sessions.map((entry, index) => {
    const path = `default_plan.sessions[${index}]`
    if (!isRecord(entry)) bad(path, 'must be an object')
    const kind = readString(entry, 'kind', path)
    if (!kindIds.has(kind)) {
      bad(`${path}.kind`, 'must name one of the offered kinds')
    }
    return {
      kind,
      start: readNumber(entry, 'start', path),
      minutes: readNumber(entry, 'minutes', path),
      intensity: readNumber(entry, 'intensity', path),
      count: readNumber(entry, 'count', path),
    }
  })

  return {
    awake,
    ambient: readNumber(raw, 'ambient', 'default_plan'),
    level: readNumber(raw, 'level', 'default_plan'),
    count_outside: readNumber(raw, 'count_outside', 'default_plan'),
    sessions,
  }
}

function readLimits(raw: unknown): PlanLimits {
  if (!isRecord(raw)) bad('limits', 'must be an object')
  const minutes = readPair(raw.session_minutes, 'limits.session_minutes')
  if (!Number.isInteger(minutes[0]) || !Number.isInteger(minutes[1])) {
    bad('limits.session_minutes', 'must be integer minutes')
  }
  const maxSessions = readInteger(raw, 'max_sessions', 'limits')
  const step = readInteger(raw, 'step_minutes', 'limits')
  if (maxSessions < 0) bad('limits.max_sessions', 'must not be negative')
  if (step <= 0) bad('limits.step_minutes', 'must be positive')
  return { max_sessions: maxSessions, session_minutes: minutes, step_minutes: step }
}

/**
 * The options endpoint with every field the editor reads checked.  Throws
 * naming the first field that is missing, wrongly typed, or the wrong shape.
 */
export function parsePlanOptions(raw: unknown): PlanOptions {
  if (!isRecord(raw)) bad('the response', 'must be an object')

  if (!Array.isArray(raw.kinds)) bad('kinds', 'must be an array')
  const kinds = raw.kinds.map((entry, index) => readKind(entry, index))
  const kindIds = new Set(kinds.map((kind) => kind.id))

  const projection = raw.projection_error
  const projectionError =
    projection === null || projection === undefined
      ? null
      : isRecord(projection)
        ? projection
        : bad('projection_error', 'must be an object or null')

  return {
    lamina: readString(raw, 'lamina', ''),
    subject: readString(raw, 'subject', ''),
    subject_label: readString(raw, 'subject_label', ''),
    applies_to: readNullableString(raw, 'applies_to', ''),
    fitted: readBoolean(raw, 'fitted', ''),
    coefficients_applies_to: readNullableString(
      raw,
      'coefficients_applies_to',
      '',
    ),
    roles: readRoles(raw.roles),
    kinds,
    day: readDay(raw.day),
    default_plan: readDefaultPlan(raw.default_plan, kindIds),
    projection_error: projectionError,
    limits: readLimits(raw.limits),
    limits_text: readStringArray(raw.limits_text, 'limits_text'),
  }
}

// ── Running a plan ───────────────────────────────────────────────────────────

/**
 * A unit written for display.  The lamina's own spelling is kept everywhere
 * else; only the one it is least readable in changes.
 */
export function unitText(unit: string): string {
  if (unit === 'degC') return '°C'
  if (unit === '1') return ''
  return unit
}

function plannedBad(field: string, expected: string): never {
  throw new Error(`planned day: ${field} ${expected}`)
}

function plannedPath(path: string, key: string): string {
  return path ? `${path}.${key}` : key
}

function plannedNumber(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    plannedBad(plannedPath(path, key), 'must be a finite number')
  }
  return value
}

function plannedNullableNumber(
  source: Record<string, unknown>,
  key: string,
  path: string,
): number | null {
  const field = plannedPath(path, key)
  if (!(key in source)) {
    plannedBad(field, 'must be a finite number or null')
  }
  const value = source[key]
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    plannedBad(field, 'must be a finite number or null')
  }
  return value
}

function plannedStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value)) plannedBad(field, 'must be an array of strings')
  return value.map((entry, index) => {
    if (typeof entry !== 'string') {
      plannedBad(`${field}[${index}]`, 'must be a string')
    }
    return entry
  })
}

/**
 * The answer to a run: the ordinary day summary plus the plan's extra fields.
 *
 * A planned day has no measured line, so its summary and every verdict are
 * null on the wire.  The copy given to `parseDaySummary` carries the empty
 * sentence and `too_few` instead; the summary's own parser still checks every
 * other field.  The extras are read here, naming the field that was wrong.
 */
export function parsePlannedDay(raw: unknown): {
  day: DaySummary
  extras: PlannedExtras
} {
  if (!isRecord(raw)) plannedBad('the response', 'must be an object')
  if (raw.planned !== true) plannedBad('planned', 'must be true')
  if (!Array.isArray(raw.sessions)) {
    plannedBad('sessions', 'must be an array')
  }

  const copy: Record<string, unknown> = { ...raw }
  if (copy.summary === null) copy.summary = ''
  copy.sessions = raw.sessions.map((entry, index) => {
    if (!isRecord(entry)) plannedBad(`sessions[${index}]`, 'must be an object')
    return entry.verdict === null ? { ...entry, verdict: 'too_few' } : entry
  })

  const day = parseDaySummary(copy)

  const projection = raw.projection_error
  let projectionError: Record<string, unknown> | null = null
  if (projection !== null && projection !== undefined) {
    if (!isRecord(projection)) {
      plannedBad('projection_error', 'must be an object or null')
    }
    projectionError = projection
  }

  const limits = plannedStringArray(raw.limits_text, 'limits_text')

  const sessions = raw.sessions.map((entry, index) => {
    const path = `sessions[${index}]`
    if (!isRecord(entry)) plannedBad(path, 'must be an object')
    const start = plannedNumber(entry, 'start', path)
    if (!Number.isInteger(start) || start < 0) {
      plannedBad(`${path}.start`, 'must be a non-negative integer')
    }
    return {
      start,
      target_set: plannedNullableNumber(entry, 'target_set', path),
      intensity_set: plannedNumber(entry, 'intensity_set', path),
      count_set: plannedNumber(entry, 'count_set', path),
      peak_modelled: plannedNullableNumber(entry, 'peak_modelled', path),
    }
  })

  return {
    day,
    extras: {
      projection_error: projectionError,
      limits_text: limits,
      sessions,
    },
  }
}

const SESSION_CONTROL: Record<string, string> = {
  start: 'start',
  minutes: 'len',
  intensity: 'level',
  count: 'steps',
  kind: 'kind',
  target: 'target',
}

/**
 * The editor control a refused server field belongs under, or null when it
 * maps to nothing the editor draws.  Never throws: a field is untrusted input
 * and an unknown one is shown under the action row.
 */
export function controlForField(field: string): string | null {
  if (typeof field !== 'string') return null
  if (field === 'awake' || field === 'awake[0]') return 'awake-start'
  if (field === 'awake[1]') return 'awake-end'
  if (field === 'ambient' || field === 'level' || field === 'count_outside') {
    return field
  }
  if (field === 'sessions') return 'add'

  const match = /^sessions\[(\d+)\](?:\.([A-Za-z_][A-Za-z0-9_]*))?$/.exec(field)
  if (!match) return null
  const index = Number(match[1])
  const name = match[2]
  if (name === undefined) return `s${index}`
  const control = SESSION_CONTROL[name]
  return control ? `s${index}-${control}` : null
}

/** The plan the editor opens on, from the options' own default. */
export function planFromOptions(options: PlanOptions): Plan {
  const plan = options.default_plan
  return {
    awake: [plan.awake[0], plan.awake[1]],
    ambient: plan.ambient,
    level: plan.level,
    count_outside: plan.count_outside,
    sessions: plan.sessions.map((session) => ({
      kind: session.kind,
      start: session.start,
      minutes: session.minutes,
      intensity: session.intensity,
      count: session.count,
      countTouched: false,
    })),
  }
}

// ── The settle table ─────────────────────────────────────────────────────────

function rowIndex(hour: number): number {
  if (!Number.isFinite(hour)) return 0
  return Math.min(23, Math.max(0, Math.floor(hour)))
}

function rowAt(kind: PlanKind, hour: number): number[] {
  return kind.settle.values[rowIndex(hour)]
}

/** The hour a session settles in: the middle of it, on the clock. */
export function sessionHour(
  session: Pick<PlanSession, 'start' | 'minutes'>,
): number {
  return Math.floor((session.start + session.minutes / 2) / 60) % 24
}

/**
 * The settle value at `intensity`, interpolated between the table's points
 * and clamped to its ends.
 */
export function settleAt(
  kind: PlanKind,
  intensity: number,
  hour: number,
): number {
  const points = kind.settle.intensities
  const row = rowAt(kind, hour)
  const last = points.length - 1

  let value = intensity
  if (Number.isNaN(value)) value = points[0]
  if (value <= points[0]) return row[0]
  if (value >= points[last]) return row[last]

  for (let index = 0; index < last; index += 1) {
    if (value <= points[index + 1]) {
      const span = points[index + 1] - points[index]
      const fraction = span === 0 ? 0 : (value - points[index]) / span
      return row[index] + (row[index + 1] - row[index]) * fraction
    }
  }
  return row[last]
}

/**
 * The intensity whose settle value is `target`, clamped to the kind's p10 and
 * p90.  The inverse of `settleAt` when the row rises with intensity.
 */
export function intensityFor(
  kind: PlanKind,
  target: number,
  hour: number,
): number {
  const points = kind.settle.intensities
  const row = rowAt(kind, hour)
  const last = points.length - 1

  let value = target
  if (Number.isNaN(value)) value = row[0]
  if (value <= row[0]) return clamp(points[0], kind.intensity.p10, kind.intensity.p90)
  if (value >= row[last]) {
    return clamp(points[last], kind.intensity.p10, kind.intensity.p90)
  }

  for (let index = 0; index < last; index += 1) {
    if (value <= row[index + 1]) {
      const span = row[index + 1] - row[index]
      if (span <= 0) return clamp(points[index + 1], kind.intensity.p10, kind.intensity.p90)
      const fraction = (value - row[index]) / span
      const intensity = points[index] + (points[index + 1] - points[index]) * fraction
      return clamp(intensity, kind.intensity.p10, kind.intensity.p90)
    }
  }
  return clamp(points[last], kind.intensity.p10, kind.intensity.p90)
}

/** The Target slider's range at `hour`: the row's rounded ends. */
export function targetRange(kind: PlanKind, hour: number): [number, number] {
  const row = rowAt(kind, hour)
  return [Math.round(row[0]), Math.round(row[row.length - 1])]
}

/** The target a session's current Level settles near. */
export function targetOf(plan: Plan, index: number, options: PlanOptions): number {
  const session = plan.sessions[index]
  if (!session) return 0
  const kind = findKind(options, session.kind)
  if (!kind) return 0
  return Math.round(settleAt(kind, session.intensity, sessionHour(session)))
}

// ── Editing ──────────────────────────────────────────────────────────────────

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

function snap(value: number): number | null {
  if (!Number.isFinite(value)) return null
  return Math.round(value / MINUTE_STEP) * MINUTE_STEP
}

function floorStep(value: number): number {
  return Math.floor(value / MINUTE_STEP) * MINUTE_STEP
}

function ceilStep(value: number): number {
  return Math.ceil(value / MINUTE_STEP) * MINUTE_STEP
}

function clock(minute: number): string {
  const rounded = Math.round(minute)
  const hours = Math.floor(rounded / 60) % 24
  const minutes = ((rounded % 60) + 60) % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function copyPlan(plan: Plan): Plan {
  return {
    awake: [plan.awake[0], plan.awake[1]],
    ambient: plan.ambient,
    level: plan.level,
    count_outside: plan.count_outside,
    sessions: plan.sessions.map((session) => ({ ...session })),
  }
}

function findKind(options: PlanOptions, id: string): PlanKind | undefined {
  return options.kinds.find((kind) => kind.id === id)
}

function earliestSession(sessions: PlanSession[]): number {
  let found = -1
  for (let index = 0; index < sessions.length; index += 1) {
    if (found < 0 || sessions[index].start < sessions[found].start) found = index
  }
  return found
}

function latestSession(sessions: PlanSession[]): number {
  let found = -1
  for (let index = 0; index < sessions.length; index += 1) {
    const end = sessions[index].start + sessions[index].minutes
    if (found < 0) {
      found = index
      continue
    }
    const best = sessions[found].start + sessions[found].minutes
    if (end > best) found = index
  }
  return found
}

/** The first other session a [start, start + minutes) band would overlap. */
function overlapIndex(
  sessions: PlanSession[],
  index: number,
  start: number,
  minutes: number,
): number {
  let found = -1
  let earliest = Infinity
  for (let other = 0; other < sessions.length; other += 1) {
    if (other === index) continue
    const session = sessions[other]
    const end = start + minutes
    if (start < session.start + session.minutes && session.start < end) {
      if (session.start < earliest) {
        earliest = session.start
        found = other
      }
    }
  }
  return found
}

/** The first 5-minute start that fits `minutes` inside the waking hours. */
function firstFit(
  sessions: PlanSession[],
  minutes: number,
  awakeStart: number,
  awakeEnd: number,
): number | null {
  const end = awakeEnd - minutes
  for (let start = awakeStart; start <= end; start += MINUTE_STEP) {
    if (overlapIndex(sessions, -1, start, minutes) < 0) return start
  }
  return null
}

/** The awake start, stopped at the earliest session's start. */
export function setAwakeStart(plan: Plan, minutes: number): PlanEdit {
  const next = copyPlan(plan)
  const wanted = snap(minutes)
  if (wanted === null) return { plan: next, message: '' }

  let value = clamp(wanted, AWAKE_START_RANGE[0], AWAKE_START_RANGE[1])
  let message = ''

  const first = earliestSession(next.sessions)
  if (first >= 0) {
    const start = next.sessions[first].start
    if (value > start) {
      value = clamp(
        floorStep(start),
        AWAKE_START_RANGE[0],
        AWAKE_START_RANGE[1],
      )
      message = `Session ${first + 1} starts ${clock(start)}`
    }
  }

  next.awake[0] = value
  return { plan: next, message }
}

/** The awake end, stopped at the latest session's end. */
export function setAwakeEnd(plan: Plan, minutes: number): PlanEdit {
  const next = copyPlan(plan)
  const wanted = snap(minutes)
  if (wanted === null) return { plan: next, message: '' }

  let value = clamp(wanted, AWAKE_END_RANGE[0], AWAKE_END_RANGE[1])
  let message = ''

  const last = latestSession(next.sessions)
  if (last >= 0) {
    const end = next.sessions[last].start + next.sessions[last].minutes
    if (value < end) {
      value = clamp(ceilStep(end), AWAKE_END_RANGE[0], AWAKE_END_RANGE[1])
      message = `Session ${last + 1} ends ${clock(end)}`
    }
  }

  next.awake[1] = value
  return { plan: next, message }
}

/**
 * A session's start, moved towards `minutes` in 5-minute steps and stopped
 * just before the first overlap.
 */
export function setStart(plan: Plan, index: number, minutes: number): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  if (!session) return { plan: next, message: '' }

  const wanted = snap(minutes)
  if (wanted === null) return { plan: next, message: '' }

  const lowest = next.awake[0]
  const highest = next.awake[1] - session.minutes
  if (highest < lowest) return { plan: next, message: '' }

  const target = clamp(wanted, lowest, highest)
  let position = session.start
  let hit = -1

  while (position !== target) {
    const direction = target > position ? 1 : -1
    const step =
      direction > 0
        ? Math.min(MINUTE_STEP, target - position)
        : Math.max(-MINUTE_STEP, target - position)
    const candidate = position + step
    const other = overlapIndex(next.sessions, index, candidate, session.minutes)
    if (other >= 0) {
      hit = other
      break
    }
    position = candidate
  }

  session.start = position
  return {
    plan: next,
    message: hit >= 0 ? `${OVERLAP_MESSAGE} ${hit + 1}` : '',
  }
}

/**
 * A session's length, in 5-minute steps, stopped just before an overlap;
 * while the reader has not touched the count, it follows the length.
 */
export function setLength(
  plan: Plan,
  index: number,
  minutes: number,
  options?: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  if (!session) return { plan: next, message: '' }

  const wanted = snap(minutes)
  if (wanted === null) return { plan: next, message: '' }

  const limits = options?.limits.session_minutes ?? [5, 180]
  const room = next.awake[1] - session.start
  const lowest = limits[0]
  const highest = Math.max(lowest, Math.min(limits[1], room))
  const target = clamp(wanted, lowest, highest)

  let position = session.minutes
  let hit = -1

  while (position !== target) {
    const direction = target > position ? 1 : -1
    const step =
      direction > 0
        ? Math.min(MINUTE_STEP, target - position)
        : Math.max(-MINUTE_STEP, target - position)
    const candidate = position + step
    const other = overlapIndex(next.sessions, index, session.start, candidate)
    if (other >= 0) {
      hit = other
      break
    }
    position = candidate
  }

  session.minutes = position
  if (!session.countTouched) {
    const kind = options ? findKind(options, session.kind) : undefined
    if (kind) session.count = Math.round(kind.steps_per_min * position)
  }

  return {
    plan: next,
    message: hit >= 0 ? `${OVERLAP_MESSAGE} ${hit + 1}` : '',
  }
}

/** Another kind: its typical Level and count, and the count follows length again. */
export function setKind(
  plan: Plan,
  index: number,
  kindId: string,
  options: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  const kind = findKind(options, kindId)
  if (!session || !kind) return { plan: next, message: '' }

  session.kind = kind.id
  session.intensity = kind.intensity.p50
  session.count = Math.round(kind.steps_per_min * session.minutes)
  session.countTouched = false
  return { plan: next, message: '' }
}

/** A Level, clamped to the kind's light and hard ends. */
export function setIntensity(
  plan: Plan,
  index: number,
  value: number,
  options: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  if (!session || !Number.isFinite(value)) return { plan: next, message: '' }
  const kind = findKind(options, session.kind)
  if (!kind) return { plan: next, message: '' }

  session.intensity = clamp(value, kind.intensity.p10, kind.intensity.p90)
  return { plan: next, message: '' }
}

/** A Target: Level follows it through the settle table. */
export function setTarget(
  plan: Plan,
  index: number,
  bpm: number,
  options: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  if (!session || !Number.isFinite(bpm)) return { plan: next, message: '' }
  const kind = findKind(options, session.kind)
  if (!kind) return { plan: next, message: '' }

  session.intensity = intensityFor(kind, bpm, sessionHour(session))
  return { plan: next, message: '' }
}

/** The session's steps, clamped to what 180 minutes of the kind can hold. */
export function setCount(
  plan: Plan,
  index: number,
  value: number,
  options: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  const session = next.sessions[index]
  if (!session || !Number.isFinite(value)) return { plan: next, message: '' }
  const kind = findKind(options, session.kind)
  if (!kind) return { plan: next, message: '' }

  const highest = Math.round(kind.steps_per_min * 180 * 1.5)
  session.count = clamp(value, 0, Math.max(0, highest))
  session.countTouched = true
  return { plan: next, message: '' }
}

/** A new typical session at the first free 30 minutes, or the sentence why not. */
export function addSession(plan: Plan, options: PlanOptions): PlanEdit {
  const next = copyPlan(plan)
  if (next.sessions.length >= options.limits.max_sessions) {
    return { plan: next, message: NO_ROOM_MESSAGE }
  }

  const kind = options.kinds[0]
  if (!kind) return { plan: next, message: NO_ROOM_MESSAGE }

  const start = firstFit(next.sessions, 30, next.awake[0], next.awake[1])
  if (start === null) return { plan: next, message: NO_ROOM_MESSAGE }

  next.sessions.push({
    kind: kind.id,
    start,
    minutes: 30,
    intensity: kind.intensity.p50,
    count: Math.round(kind.steps_per_min * 30),
    countTouched: false,
  })
  return { plan: next, message: '' }
}

export function removeSession(plan: Plan, index: number): PlanEdit {
  const next = copyPlan(plan)
  if (index >= 0 && index < next.sessions.length) next.sessions.splice(index, 1)
  return { plan: next, message: '' }
}

/** A Day value, clamped to the range the options offer for it. */
export function setDay(
  plan: Plan,
  key: 'ambient' | 'level' | 'count_outside',
  value: number,
  options: PlanOptions,
): PlanEdit {
  const next = copyPlan(plan)
  if (!Number.isFinite(value)) return { plan: next, message: '' }
  const range = options.day[key]
  next[key] = clamp(value, range.min, range.max)
  return { plan: next, message: '' }
}

// ── The link ─────────────────────────────────────────────────────────────────

/**
 * A compact, URL-safe plan: version 1, the day's five fields, then one
 * positional group per session.  Only finite values from a valid plan are
 * encoded; a number keeps its shortest exact decimal spelling.
 */
export function encodePlan(plan: Plan): string {
  const header = [
    '1',
    plan.awake[0],
    plan.awake[1],
    plan.ambient,
    plan.level,
    plan.count_outside,
  ]
    .map((value) => String(value))
    .join('_')

  const sessions = plan.sessions.map((session) =>
    [
      session.kind,
      session.start,
      session.minutes,
      session.intensity,
      session.count,
      session.countTouched ? 1 : 0,
    ].join('_'),
  )

  return [header, ...sessions].join('~')
}

const NUMBER_RE = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/

function parseNumber(text: string): number | null {
  if (!NUMBER_RE.test(text)) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/**
 * A plan from `text`, or null for anything malformed, an unknown kind, or a
 * value outside the options' ranges.  This never throws: a link is untrusted
 * input and an unreadable one opens the typical day instead.
 */
export function decodePlan(text: string, options: PlanOptions): Plan | null {
  try {
    if (typeof text !== 'string' || text === '') return null

    const parts = text.split('~')
    const header = parts[0].split('_')
    if (header.length !== 6 || header[0] !== '1') return null

    const awakeStart = parseNumber(header[1])
    const awakeEnd = parseNumber(header[2])
    const ambient = parseNumber(header[3])
    const level = parseNumber(header[4])
    const countOutside = parseNumber(header[5])
    if (
      awakeStart === null ||
      awakeEnd === null ||
      ambient === null ||
      level === null ||
      countOutside === null
    ) {
      return null
    }

    if (!Number.isInteger(awakeStart) || !Number.isInteger(awakeEnd)) return null
    if (
      awakeStart < AWAKE_START_RANGE[0] ||
      awakeStart > AWAKE_START_RANGE[1] ||
      awakeEnd < AWAKE_END_RANGE[0] ||
      awakeEnd > AWAKE_END_RANGE[1] ||
      awakeStart >= awakeEnd
    ) {
      return null
    }

    if (
      ambient < options.day.ambient.min ||
      ambient > options.day.ambient.max ||
      level < options.day.level.min ||
      level > options.day.level.max ||
      countOutside < options.day.count_outside.min ||
      countOutside > options.day.count_outside.max
    ) {
      return null
    }

    const sessions: PlanSession[] = []
    for (let index = 1; index < parts.length; index += 1) {
      const fields = parts[index].split('_')
      if (fields.length !== 6) return null

      const kind = findKind(options, fields[0])
      if (!kind) return null

      const start = parseNumber(fields[1])
      const minutes = parseNumber(fields[2])
      const intensity = parseNumber(fields[3])
      const count = parseNumber(fields[4])
      const touched = fields[5]
      if (
        start === null ||
        minutes === null ||
        intensity === null ||
        count === null ||
        (touched !== '0' && touched !== '1')
      ) {
        return null
      }

      if (!Number.isInteger(start) || !Number.isInteger(minutes)) return null
      if (
        minutes < options.limits.session_minutes[0] ||
        minutes > options.limits.session_minutes[1]
      ) {
        return null
      }
      if (start < awakeStart || start + minutes > awakeEnd) return null
      if (
        intensity < kind.intensity.p10 ||
        intensity > kind.intensity.p90
      ) {
        return null
      }

      const highest = Math.round(kind.steps_per_min * 180 * 1.5)
      if (count < 0 || count > Math.max(0, highest)) return null

      for (const other of sessions) {
        if (
          start < other.start + other.minutes &&
          other.start < start + minutes
        ) {
          return null
        }
      }

      sessions.push({
        kind: kind.id,
        start,
        minutes,
        intensity,
        count,
        countTouched: touched === '1',
      })
    }

    return {
      awake: [awakeStart, awakeEnd],
      ambient,
      level,
      count_outside: countOutside,
      sessions,
    }
  } catch {
    return null
  }
}

/** The JSON body of `POST /api/day/plan`, each session's target included. */
export function planBody(
  plan: Plan,
  subject: string,
  options: PlanOptions,
): {
  subject: string
  awake: [number, number]
  ambient: number
  level: number
  count_outside: number
  sessions: {
    kind: string
    start: number
    minutes: number
    intensity: number
    count: number
    target: number
  }[]
} {
  return {
    subject,
    awake: [plan.awake[0], plan.awake[1]],
    ambient: plan.ambient,
    level: plan.level,
    count_outside: plan.count_outside,
    sessions: plan.sessions.map((session, index) => ({
      kind: session.kind,
      start: session.start,
      minutes: session.minutes,
      intensity: session.intensity,
      count: session.count,
      target: targetOf(plan, index, options),
    })),
  }
}
