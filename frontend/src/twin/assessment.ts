/**
 * assessment — the pure arithmetic behind the assessment form.
 *
 * The options endpoint and the assessed answer are untrusted input: every
 * field this module reads is checked, and a malformed response throws naming
 * the field rather than drawing a plausible-looking risk.  The form's editing
 * helpers never mutate their input; the one thing a person types is parsed
 * without throwing, and a value the form cannot accept leaves the entries
 * exactly as they were and returns the sentence to show under the field.
 *
 * Nothing here imports React, the DOM or axios, so the parsing, the entry
 * checks and the display text are checked directly by
 * scripts/assessment-check.ts.  The module names no attribute id, unit,
 * disease or model: everything comes from the options and the answer.
 */
import { isRecord, unitText } from './planDay.ts'

export interface AssessmentChoice {
  value: number
  label: string
}

export type EntryKind = 'number' | 'yesno' | 'choice'

export interface AssessmentEntry {
  attribute: string
  label: string
  unit: string
  kind: EntryKind
  why: string
  min: number
  max: number
  options: AssessmentChoice[] | null
}

export interface AssessmentGroup {
  id: string
  label: string
  entries: AssessmentEntry[]
}

export interface AssessmentLink {
  attribute: string
  label: string
  unit: string
}

export interface AssessmentRange {
  label: string
  unit: string
  low: number
  high: number
}

export interface AssessmentModel {
  id: string
  name: string
  status: string
  source: string
  reviewed_by: string
}

export interface AssessmentOptionResult {
  id: string
  label: string
  period: string
  unit: string
  status: string | null
  models: AssessmentModel[]
  entries: string[]
  links: string[]
}

export interface AssessmentOptionFlag {
  attribute: string
  topic: string
  label: string
  text: string
  status: string | null
  entries: string[]
  links: string[]
}

export interface AssessmentExample {
  label: string
  values: Record<string, number>
}

export interface AssessmentExampleProfile {
  id: string
  label: string
  values: Entries
}

export interface AssessmentMeasured {
  key: string
  attribute: string
  label: string
  unit: string
}

export interface AssessmentHorizons {
  attribute: string
  unit: string
  values: number[]
  settled: number
  settled_label: string
}

export interface AssessmentSeriesPoint {
  weeks: number
  value: number | null
}

export interface AssessmentMediatorOption {
  now: string
  at: string
  label: string
  unit: string
  source: 'entered' | 'measured'
  key: string | null
  still: string | null
  status: string | null
  models: AssessmentModel[]
}

export interface AssessmentOptions {
  lamina: string
  name: string
  groups: AssessmentGroup[]
  links: Record<string, AssessmentLink>
  range: AssessmentRange | null
  results: AssessmentOptionResult[]
  flags: AssessmentOptionFlag[]
  example: AssessmentExample | null
  examples: AssessmentExampleProfile[]
  measured: AssessmentMeasured[]
  horizons: AssessmentHorizons | null
  mediators: AssessmentMediatorOption[]
  notice: string | null
}

export interface AssessmentDoseCurrent {
  p10: number
  p50: number
  p90: number
  weeks: number
  rule: string
}

export interface AssessmentDosePlanned {
  value: number
  from_sessions: number
  from_everyday: number
  days_per_week: number
  session_day: number
}

export interface AssessmentDose {
  unit: string
  fitness: Record<string, number>
  current: AssessmentDoseCurrent | null
  planned: AssessmentDosePlanned | null
  reason: string | null
}

export type AssessmentNeed =
  | { attribute: string; label: string }
  | { link: string; label: string }
  | { measured: string; label: string }

export interface AssessmentChange {
  points: number
  relative_pct: number
}

export interface AssessmentResult {
  id: string
  label: string
  period: string
  unit: string
  status: string | null
  models: AssessmentModel[]
  now: number | null
  planned: number | null
  change: AssessmentChange | null
  not_applicable: string | null
  needs: { now: AssessmentNeed[]; planned: AssessmentNeed[] }
  series: AssessmentSeriesPoint[]
  settled: number | null
  reason: string | null
}

export interface AssessmentMediatorOutcome {
  now: string
  label: string
  unit: string
  source: 'entered' | 'measured'
  key: string | null
  still: string | null
  status: string | null
  value_now: number | null
  series: AssessmentSeriesPoint[]
  settled: number | null
  moves: boolean
  needs: AssessmentNeed[]
}

export type AssessmentFlagState = 'raised' | 'clear' | 'not_answered'

export interface AssessmentFlag {
  attribute: string
  topic: string
  label: string
  text: string
  status: string | null
  state: AssessmentFlagState
  needs: AssessmentNeed[]
}

export interface AssessmentOutcome {
  entered: { given: number; of: number }
  links: Record<string, number | null>
  range: AssessmentRange | null
  results: AssessmentResult[]
  flags: AssessmentFlag[]
  horizons: AssessmentHorizons | null
  mediators: AssessmentMediatorOutcome[]
  notice: string | null
}

export interface AssessmentAnswer {
  subject: string
  subject_label: string
  dose: AssessmentDose
  assessment: AssessmentOutcome
}

/** What the form holds: an absent key means the person has not entered it. */
export type Entries = Record<string, number>

export interface GroupProgress {
  id: string
  label: string
  given: number
  of: number
}

export type StatusTone = 'placeholder' | 'draft' | 'reviewed' | 'none'

export const DAYS_PER_WEEK_RANGE: readonly [number, number] = [0, 7]

/** The typical number of session days the link opens with. */
export const DEFAULT_DAYS_PER_WEEK = 3

/** The link's `days` parameter: an integer 0..7, or the typical 3. */
export function readDaysParam(search: string): number {
  const raw = new URLSearchParams(search).get('days')
  if (raw === null || !/^\d+$/.test(raw)) return DEFAULT_DAYS_PER_WEEK
  const value = Number(raw)
  if (
    !Number.isInteger(value) ||
    value < DAYS_PER_WEEK_RANGE[0] ||
    value > DAYS_PER_WEEK_RANGE[1]
  ) {
    return DEFAULT_DAYS_PER_WEEK
  }
  return value
}

/** The same query with `days` written as a clamped whole number. */
export function writeDaysParam(search: string, days: number): string {
  const query = new URLSearchParams(search)
  query.set('days', String(clampDays(days)))
  return query.toString()
}

// ── Reading untrusted JSON ───────────────────────────────────────────────────

type Bad = (field: string, expected: string) => never

interface ValueReader {
  bad: Bad
  record(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): Record<string, unknown>
  string(source: Record<string, unknown>, key: string, path: string): string
  nullableString(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): string | null
  number(source: Record<string, unknown>, key: string, path: string): number
  nullableNumber(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): number | null
  integer(source: Record<string, unknown>, key: string, path: string): number
  boolean(source: Record<string, unknown>, key: string, path: string): boolean
  stringArray(value: unknown, field: string): string[]
}

function fieldPath(path: string, key: string): string {
  return path ? `${path}.${key}` : key
}

function makeReader(prefix: string): ValueReader {
  const bad: Bad = (field, expected) => {
    throw new Error(`${prefix}: ${field} ${expected}`)
  }

  function record(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): Record<string, unknown> {
    const value = source[key]
    if (!isRecord(value)) bad(fieldPath(path, key), 'must be an object')
    return value
  }

  function string(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): string {
    const value = source[key]
    if (typeof value !== 'string') bad(fieldPath(path, key), 'must be a string')
    return value
  }

  function nullableString(
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

  function number(
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

  function nullableNumber(
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

  function integer(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): number {
    const value = number(source, key, path)
    if (!Number.isInteger(value)) bad(fieldPath(path, key), 'must be an integer')
    return value
  }

  function boolean(
    source: Record<string, unknown>,
    key: string,
    path: string,
  ): boolean {
    const value = source[key]
    if (typeof value !== 'boolean') {
      bad(fieldPath(path, key), 'must be a boolean')
    }
    return value
  }

  function stringArray(value: unknown, field: string): string[] {
    if (!Array.isArray(value)) bad(field, 'must be an array')
    return value.map((entry, index) => {
      if (typeof entry !== 'string') bad(`${field}[${index}]`, 'must be a string')
      return entry
    })
  }

  return {
    bad,
    record,
    string,
    nullableString,
    number,
    nullableNumber,
    integer,
    boolean,
    stringArray,
  }
}

const optionsReader = makeReader('assessment options')
const answerReader = makeReader('assessment answer')

// ── Parsing the options endpoint ─────────────────────────────────────────────

function readChoice(
  r: ValueReader,
  raw: unknown,
  field: string,
): AssessmentChoice {
  if (!isRecord(raw)) r.bad(field, 'must be an object')
  return {
    value: r.number(raw, 'value', field),
    label: r.string(raw, 'label', field),
  }
}

function readChoices(
  r: ValueReader,
  raw: unknown,
  field: string,
): AssessmentChoice[] | null {
  if (raw === null) return null
  if (!Array.isArray(raw)) r.bad(field, 'must be an array or null')
  return raw.map((entry, index) => readChoice(r, entry, `${field}[${index}]`))
}

function readKind(
  r: ValueReader,
  source: Record<string, unknown>,
  path: string,
): EntryKind {
  const kind = r.string(source, 'kind', path)
  if (kind === 'number' || kind === 'yesno' || kind === 'choice') return kind
  return r.bad(
    fieldPath(path, 'kind'),
    'must be number, yesno or choice',
  )
}

function readEntry(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentEntry {
  if (!isRecord(raw)) r.bad(path, 'must be an object')
  const min = r.number(raw, 'min', path)
  const max = r.number(raw, 'max', path)
  if (min > max) r.bad(path, 'must have min <= max')
  return {
    attribute: r.string(raw, 'attribute', path),
    label: r.string(raw, 'label', path),
    unit: r.string(raw, 'unit', path),
    kind: readKind(r, raw, path),
    why: r.string(raw, 'why', path),
    min,
    max,
    options: readChoices(r, raw.options, fieldPath(path, 'options')),
  }
}

function readEntries(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentEntry[] {
  const field = fieldPath(path, 'entries')
  if (!Array.isArray(raw)) r.bad(field, 'must be an array')
  return raw.map((entry, index) => readEntry(r, entry, `${field}[${index}]`))
}

function readGroups(r: ValueReader, raw: unknown): AssessmentGroup[] {
  if (!Array.isArray(raw)) r.bad('groups', 'must be an array')
  return raw.map((entry, index) => {
    const path = `groups[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      id: r.string(entry, 'id', path),
      label: r.string(entry, 'label', path),
      entries: readEntries(r, entry.entries, path),
    }
  })
}

function readLinks(
  r: ValueReader,
  raw: unknown,
): Record<string, AssessmentLink> {
  if (!isRecord(raw)) r.bad('links', 'must be an object')
  const links: Record<string, AssessmentLink> = {}
  for (const [key, value] of Object.entries(raw)) {
    const path = `links.${key}`
    if (!isRecord(value)) r.bad(path, 'must be an object')
    links[key] = {
      attribute: r.string(value, 'attribute', path),
      label: r.string(value, 'label', path),
      unit: r.string(value, 'unit', path),
    }
  }
  return links
}

function readRange(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentRange | null {
  if (raw === null) return null
  if (!isRecord(raw)) r.bad(path, 'must be an object or null')
  const low = r.number(raw, 'low', path)
  const high = r.number(raw, 'high', path)
  if (low > high) r.bad(path, 'must have low <= high')
  return {
    label: r.string(raw, 'label', path),
    unit: r.string(raw, 'unit', path),
    low,
    high,
  }
}

function readModel(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentModel {
  if (!isRecord(raw)) r.bad(path, 'must be an object')
  return {
    id: r.string(raw, 'id', path),
    name: r.string(raw, 'name', path),
    status: r.string(raw, 'status', path),
    source: r.string(raw, 'source', path),
    reviewed_by: r.string(raw, 'reviewed_by', path),
  }
}

function readModels(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentModel[] {
  const field = fieldPath(path, 'models')
  if (!Array.isArray(raw)) r.bad(field, 'must be an array')
  return raw.map((entry, index) => readModel(r, entry, `${field}[${index}]`))
}

function readOptionResults(
  r: ValueReader,
  raw: unknown,
): AssessmentOptionResult[] {
  if (!Array.isArray(raw)) r.bad('results', 'must be an array')
  return raw.map((entry, index) => {
    const path = `results[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      id: r.string(entry, 'id', path),
      label: r.string(entry, 'label', path),
      period: r.string(entry, 'period', path),
      unit: r.string(entry, 'unit', path),
      status: r.nullableString(entry, 'status', path),
      models: readModels(r, entry.models, path),
      entries: r.stringArray(entry.entries, fieldPath(path, 'entries')),
      links: r.stringArray(entry.links, fieldPath(path, 'links')),
    }
  })
}

function readOptionFlags(
  r: ValueReader,
  raw: unknown,
): AssessmentOptionFlag[] {
  if (!Array.isArray(raw)) r.bad('flags', 'must be an array')
  return raw.map((entry, index) => {
    const path = `flags[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      attribute: r.string(entry, 'attribute', path),
      topic: r.string(entry, 'topic', path),
      label: r.string(entry, 'label', path),
      text: r.string(entry, 'text', path),
      status: r.nullableString(entry, 'status', path),
      entries: r.stringArray(entry.entries, fieldPath(path, 'entries')),
      links: r.stringArray(entry.links, fieldPath(path, 'links')),
    }
  })
}

function readEntryValues(
  r: ValueReader,
  raw: unknown,
  field: string,
): Entries {
  if (!isRecord(raw)) r.bad(field, 'must be an object')
  const values: Entries = {}
  for (const key of Object.keys(raw)) {
    values[key] = r.number(raw, key, field)
  }
  return values
}

function readExample(
  r: ValueReader,
  raw: unknown,
): AssessmentExample | null {
  if (raw === null) return null
  if (!isRecord(raw)) r.bad('example', 'must be an object or null')
  return {
    label: r.string(raw, 'label', 'example'),
    values: readEntryValues(r, raw.values, 'example.values'),
  }
}

function readExamples(
  r: ValueReader,
  raw: unknown,
): AssessmentExampleProfile[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw)) r.bad('examples', 'must be an array')
  if (raw.length === 0) r.bad('examples', 'must not be empty')
  const seen = new Set<string>()
  return raw.map((entry, index) => {
    const path = `examples[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    const id = r.string(entry, 'id', path)
    if (id === '') r.bad(fieldPath(path, 'id'), 'must not be empty')
    if (seen.has(id)) r.bad(fieldPath(path, 'id'), 'must be unique')
    seen.add(id)
    return {
      id,
      label: r.string(entry, 'label', path),
      values: readEntryValues(r, entry.values, fieldPath(path, 'values')),
    }
  })
}

function readMeasured(
  r: ValueReader,
  raw: unknown,
): AssessmentMeasured[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw)) r.bad('measured', 'must be an array')
  return raw.map((entry, index) => {
    const path = `measured[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      key: r.string(entry, 'key', path),
      attribute: r.string(entry, 'attribute', path),
      label: r.string(entry, 'label', path),
      unit: r.string(entry, 'unit', path),
    }
  })
}

function readHorizons(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentHorizons | null {
  if (raw === undefined || raw === null) return null
  if (!isRecord(raw)) r.bad(path, 'must be an object or null')
  const valuesField = fieldPath(path, 'values')
  if (!Array.isArray(raw.values)) r.bad(valuesField, 'must be an array')
  const values = raw.values.map((entry, index) => {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) {
      r.bad(`${valuesField}[${index}]`, 'must be a finite number')
    }
    return entry
  })
  return {
    attribute: r.string(raw, 'attribute', path),
    unit: r.string(raw, 'unit', path),
    values,
    settled: r.number(raw, 'settled', path),
    settled_label: r.string(raw, 'settled_label', path),
  }
}

function readMediatorSource(
  r: ValueReader,
  raw: Record<string, unknown>,
  path: string,
): 'entered' | 'measured' {
  const source = r.string(raw, 'source', path)
  if (source === 'entered' || source === 'measured') return source
  return r.bad(
    fieldPath(path, 'source'),
    "must be 'entered' or 'measured'",
  )
}

function readMediatorOptions(
  r: ValueReader,
  raw: unknown,
): AssessmentMediatorOption[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw)) r.bad('mediators', 'must be an array')
  return raw.map((entry, index) => {
    const path = `mediators[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      now: r.string(entry, 'now', path),
      at: r.string(entry, 'at', path),
      label: r.string(entry, 'label', path),
      unit: r.string(entry, 'unit', path),
      source: readMediatorSource(r, entry, path),
      key: r.nullableString(entry, 'key', path),
      still: r.nullableString(entry, 'still', path),
      status: r.nullableString(entry, 'status', path),
      models: readModels(r, entry.models, path),
    }
  })
}

/**
 * The options endpoint with every field the form reads checked.  Throws naming
 * the first field that is missing, wrongly typed, or the wrong shape.
 */
export function parseAssessmentOptions(raw: unknown): AssessmentOptions {
  const r = optionsReader
  if (!isRecord(raw)) {
    return r.bad('the response', 'must be an object')
  }

  return {
    lamina: r.string(raw, 'lamina', ''),
    name: r.string(raw, 'name', ''),
    groups: readGroups(r, raw.groups),
    links: readLinks(r, raw.links),
    range: readRange(r, raw.range, 'range'),
    results: readOptionResults(r, raw.results),
    flags: readOptionFlags(r, raw.flags),
    example: readExample(r, raw.example),
    examples: readExamples(r, raw.examples),
    measured: readMeasured(r, raw.measured),
    horizons: readHorizons(r, raw.horizons, 'horizons'),
    mediators: readMediatorOptions(r, raw.mediators),
    notice: r.nullableString(raw, 'notice', ''),
  }
}

// ── Parsing the assessed answer ──────────────────────────────────────────────

function readDoseCurrent(
  r: ValueReader,
  raw: unknown,
): AssessmentDoseCurrent | null {
  if (raw === null) return null
  const path = 'dose.current'
  if (!isRecord(raw)) r.bad(path, 'must be an object or null')
  const p10 = r.number(raw, 'p10', path)
  const p50 = r.number(raw, 'p50', path)
  const p90 = r.number(raw, 'p90', path)
  if (!(p10 <= p50 && p50 <= p90)) {
    r.bad(path, 'must have p10 <= p50 <= p90')
  }
  const weeks = r.integer(raw, 'weeks', path)
  if (weeks < 0) r.bad(fieldPath(path, 'weeks'), 'must not be negative')
  return {
    p10,
    p50,
    p90,
    weeks,
    rule: r.string(raw, 'rule', path),
  }
}

function readDosePlanned(
  r: ValueReader,
  raw: unknown,
): AssessmentDosePlanned | null {
  if (raw === null) return null
  const path = 'dose.planned'
  if (!isRecord(raw)) r.bad(path, 'must be an object or null')
  const days = r.integer(raw, 'days_per_week', path)
  if (days < DAYS_PER_WEEK_RANGE[0] || days > DAYS_PER_WEEK_RANGE[1]) {
    r.bad(fieldPath(path, 'days_per_week'), 'must be from 0 to 7')
  }
  return {
    value: r.number(raw, 'value', path),
    from_sessions: r.number(raw, 'from_sessions', path),
    from_everyday: r.number(raw, 'from_everyday', path),
    days_per_week: days,
    session_day: r.number(raw, 'session_day', path),
  }
}

function readFitness(
  r: ValueReader,
  raw: unknown,
): Record<string, number> {
  if (raw === undefined) return {}
  if (!isRecord(raw)) r.bad('dose.fitness', 'must be an object')
  const fitness: Record<string, number> = {}
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      r.bad(`dose.fitness.${key}`, 'must be a finite number')
    }
    fitness[key] = value
  }
  return fitness
}

function readDose(r: ValueReader, raw: unknown): AssessmentDose {
  if (!isRecord(raw)) r.bad('dose', 'must be an object')
  return {
    unit: r.string(raw, 'unit', 'dose'),
    fitness: readFitness(r, raw.fitness),
    current: readDoseCurrent(r, raw.current),
    planned: readDosePlanned(r, raw.planned),
    reason: r.nullableString(raw, 'reason', 'dose'),
  }
}

function readFlagState(
  r: ValueReader,
  raw: Record<string, unknown>,
  path: string,
): AssessmentFlagState {
  const state = r.string(raw, 'state', path)
  if (state === 'raised' || state === 'clear' || state === 'not_answered') {
    return state
  }
  return r.bad(
    fieldPath(path, 'state'),
    "must be 'raised', 'clear' or 'not_answered'",
  )
}

function readNeeds(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentNeed[] {
  if (!Array.isArray(raw)) r.bad(path, 'must be an array')
  return raw.map((entry, index) => {
    const at = `${path}[${index}]`
    if (!isRecord(entry)) r.bad(at, 'must be an object')
    const label = r.string(entry, 'label', at)
    if ('attribute' in entry) {
      const attribute = entry.attribute
      if (typeof attribute !== 'string') {
        r.bad(fieldPath(at, 'attribute'), 'must be a string')
      }
      return { attribute, label }
    }
    if ('link' in entry) {
      const link = entry.link
      if (typeof link !== 'string') {
        r.bad(fieldPath(at, 'link'), 'must be a string')
      }
      return { link, label }
    }
    if ('measured' in entry) {
      const measured = entry.measured
      if (typeof measured !== 'string') {
        r.bad(fieldPath(at, 'measured'), 'must be a string')
      }
      return { measured, label }
    }
    return r.bad(at, 'must name an attribute, a link or a measured value')
  })
}

function readSeries(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentSeriesPoint[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw)) r.bad(path, 'must be an array')
  return raw.map((entry, index) => {
    const at = `${path}[${index}]`
    if (!isRecord(entry)) r.bad(at, 'must be an object')
    return {
      weeks: r.number(entry, 'weeks', at),
      value: r.nullableNumber(entry, 'value', at),
    }
  })
}

function readOptionalNullableNumber(
  r: ValueReader,
  source: Record<string, unknown>,
  key: string,
  path: string,
): number | null {
  if (source[key] === undefined) return null
  return r.nullableNumber(source, key, path)
}

function readChange(
  r: ValueReader,
  raw: unknown,
  path: string,
): AssessmentChange | null {
  if (raw === null) return null
  if (!isRecord(raw)) r.bad(path, 'must be an object or null')
  return {
    points: r.number(raw, 'points', path),
    relative_pct: r.number(raw, 'relative_pct', path),
  }
}

function readResults(
  r: ValueReader,
  raw: unknown,
  horizons: AssessmentHorizons | null,
): AssessmentResult[] {
  if (!Array.isArray(raw)) r.bad('assessment.results', 'must be an array')
  return raw.map((entry, index) => {
    const path = `assessment.results[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    const needs = r.record(entry, 'needs', path)
    const series = readSeries(r, entry.series, fieldPath(path, 'series'))
    if (
      entry.series !== undefined &&
      horizons !== null &&
      series.length !== horizons.values.length
    ) {
      r.bad(
        fieldPath(path, 'series'),
        'must have as many entries as the horizons',
      )
    }
    return {
      id: r.string(entry, 'id', path),
      label: r.string(entry, 'label', path),
      period: r.string(entry, 'period', path),
      unit: r.string(entry, 'unit', path),
      status: r.nullableString(entry, 'status', path),
      models: readModels(r, entry.models, path),
      now: r.nullableNumber(entry, 'now', path),
      planned: r.nullableNumber(entry, 'planned', path),
      change: readChange(r, entry.change, fieldPath(path, 'change')),
      not_applicable: r.nullableString(entry, 'not_applicable', path),
      needs: {
        now: readNeeds(r, needs.now, fieldPath(fieldPath(path, 'needs'), 'now')),
        planned: readNeeds(
          r,
          needs.planned,
          fieldPath(fieldPath(path, 'needs'), 'planned'),
        ),
      },
      series,
      settled: readOptionalNullableNumber(r, entry, 'settled', path),
      reason: r.nullableString(entry, 'reason', path),
    }
  })
}

function readFlags(r: ValueReader, raw: unknown): AssessmentFlag[] {
  if (!Array.isArray(raw)) r.bad('assessment.flags', 'must be an array')
  return raw.map((entry, index) => {
    const path = `assessment.flags[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      attribute: r.string(entry, 'attribute', path),
      topic: r.string(entry, 'topic', path),
      label: r.string(entry, 'label', path),
      text: r.string(entry, 'text', path),
      status: r.nullableString(entry, 'status', path),
      state: readFlagState(r, entry, path),
      needs: readNeeds(r, entry.needs, fieldPath(path, 'needs')),
    }
  })
}

function readMediatorOutcomes(
  r: ValueReader,
  raw: unknown,
): AssessmentMediatorOutcome[] {
  if (raw === undefined) return []
  if (!Array.isArray(raw)) r.bad('assessment.mediators', 'must be an array')
  return raw.map((entry, index) => {
    const path = `assessment.mediators[${index}]`
    if (!isRecord(entry)) r.bad(path, 'must be an object')
    return {
      now: r.string(entry, 'now', path),
      label: r.string(entry, 'label', path),
      unit: r.string(entry, 'unit', path),
      source: readMediatorSource(r, entry, path),
      key: r.nullableString(entry, 'key', path),
      still: r.nullableString(entry, 'still', path),
      status: r.nullableString(entry, 'status', path),
      value_now: r.nullableNumber(entry, 'value_now', path),
      series: readSeries(r, entry.series, fieldPath(path, 'series')),
      settled: readOptionalNullableNumber(r, entry, 'settled', path),
      moves: r.boolean(entry, 'moves', path),
      needs: readNeeds(r, entry.needs, fieldPath(path, 'needs')),
    }
  })
}

function readAnswerLinks(
  r: ValueReader,
  raw: unknown,
): Record<string, number | null> {
  if (!isRecord(raw)) r.bad('assessment.links', 'must be an object')
  const links: Record<string, number | null> = {}
  for (const [key, value] of Object.entries(raw)) {
    const path = `assessment.links.${key}`
    if (value === null) {
      links[key] = null
      continue
    }
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      r.bad(path, 'must be a finite number or null')
    }
    links[key] = value
  }
  return links
}

function readOutcome(r: ValueReader, raw: unknown): AssessmentOutcome {
  if (!isRecord(raw)) r.bad('assessment', 'must be an object')
  const entered = r.record(raw, 'entered', 'assessment')
  const given = r.integer(entered, 'given', 'assessment.entered')
  const of = r.integer(entered, 'of', 'assessment.entered')
  if (given < 0 || of < 0) {
    r.bad('assessment.entered', 'must not be negative')
  }
  if (given > of) r.bad('assessment.entered', 'must have given <= of')
  const horizons = readHorizons(r, raw.horizons, 'assessment.horizons')
  return {
    entered: { given, of },
    links: readAnswerLinks(r, raw.links),
    range: readRange(r, raw.range, 'assessment.range'),
    results: readResults(r, raw.results, horizons),
    flags: readFlags(r, raw.flags),
    horizons,
    mediators: readMediatorOutcomes(r, raw.mediators),
    notice: r.nullableString(raw, 'notice', 'assessment'),
  }
}

/**
 * The answer to an assessment with every field the screen reads checked, plus
 * the planned day passed through untouched for `parsePlannedDay`.  Throws
 * naming the first field that is missing or wrongly typed.
 */
export function parseAssessmentAnswer(raw: unknown): {
  answer: AssessmentAnswer
  day: unknown
} {
  const r = answerReader
  if (!isRecord(raw)) {
    return r.bad('the response', 'must be an object')
  }
  if (!('day' in raw)) {
    return r.bad('day', 'must be present')
  }
  const day = raw.day
  if (day !== null && !isRecord(day)) {
    return r.bad('day', 'must be an object or null')
  }

  return {
    answer: {
      subject: r.string(raw, 'subject', ''),
      subject_label: r.string(raw, 'subject_label', ''),
      dose: readDose(r, raw.dose),
      assessment: readOutcome(r, raw.assessment),
    },
    day,
  }
}

// ── Horizons, profiles and factor movement ──────────────────────────────────

/** One selectable column: a listed horizon or the settled value. */
export type HorizonChoice = {
  index: number
  weeks: number | null
  label: string
  settled: boolean
}

/** One choice per listed horizon, then the settled column; [] for null. */
export function horizonChoices(h: AssessmentHorizons | null): HorizonChoice[] {
  if (h === null) return []
  const choices: HorizonChoice[] = h.values.map((weeks, index) => ({
    index,
    weeks,
    label: weeks === 0 ? 'Now' : `${weeks} weeks`,
    settled: false,
  }))
  choices.push({
    index: h.values.length,
    weeks: null,
    label: h.settled_label,
    settled: true,
  })
  return choices
}

/** The value a series holds at the choice, or the settled value for the last. */
export function valueAtHorizon(
  item: { series: AssessmentSeriesPoint[]; settled: number | null },
  choice: HorizonChoice,
): number | null {
  if (choice.settled) return item.settled
  const point = item.series[choice.index]
  return point === undefined ? null : point.value
}

/** The compact label a risk card's horizon row prints. */
export function horizonShort(choice: HorizonChoice): string {
  if (choice.settled) return choice.label
  if (choice.weeks === null || choice.weeks === 0) return 'Now'
  return `${choice.weeks} wk`
}

/**
 * The largest relative move any moving mediator makes, shared by every factor
 * so one that barely moves is drawn as barely moving; at least 0.02.
 */
export function mediatorScale(
  mediators: AssessmentMediatorOutcome[],
  choices: HorizonChoice[],
): number {
  let scale = 0
  for (const mediator of mediators) {
    if (!mediator.moves) continue
    const now = mediator.value_now
    if (now === null || now === 0 || !Number.isFinite(now)) continue
    for (const choice of choices) {
      const value = valueAtHorizon(mediator, choice)
      if (value === null || !Number.isFinite(value)) continue
      const ratio = Math.abs(value - now) / Math.abs(now)
      if (ratio > scale) scale = ratio
    }
  }
  return Math.max(0.02, scale)
}

/** A factor's move from its value now, on the shared scale, clamped to [-1, 1]. */
export function mediatorPoint(
  value: number | null,
  valueNow: number | null,
  scale: number,
): number {
  if (
    value === null ||
    valueNow === null ||
    valueNow === 0 ||
    !Number.isFinite(value) ||
    !Number.isFinite(valueNow) ||
    !Number.isFinite(scale) ||
    scale <= 0
  ) {
    return 0
  }
  const point = (value - valueNow) / Math.abs(valueNow) / scale
  return Math.min(1, Math.max(-1, point))
}

/** How many decimals a factor's value is printed with. */
export function decimalsFor(value: number): number {
  return Math.abs(value) < 10 ? 2 : 1
}

/** The id of the example whose values equal the entries exactly, else null. */
export function profileOf(
  options: AssessmentOptions,
  entries: Entries,
): string | null {
  const entryKeys = Object.keys(entries)
  for (const profile of options.examples) {
    const keys = Object.keys(profile.values)
    if (keys.length !== entryKeys.length) continue
    let same = true
    for (const key of keys) {
      const value = entries[key]
      if (value === undefined || value !== profile.values[key]) {
        same = false
        break
      }
    }
    if (same) return profile.id
  }
  return null
}

/** A fresh copy of the named example's values; throws naming an unknown id. */
export function fillProfile(options: AssessmentOptions, id: string): Entries {
  const profile = options.examples.find((example) => example.id === id)
  if (profile === undefined) {
    throw new Error(
      `assessment options: examples.${id} is not a declared example`,
    )
  }
  const entries: Entries = {}
  for (const key of Object.keys(profile.values)) {
    const value = profile.values[key]
    if (!Number.isFinite(value)) {
      throw new Error(
        `assessment options: examples.${id}.values.${key} must be a finite number`,
      )
    }
    entries[key] = value
  }
  return entries
}

/** The label of any kind of need. */
export function needText(need: AssessmentNeed): string {
  return need.label
}

/**
 * How much a value moved from now, printed with two decimals; a move under
 * 0.005 counts as the same.
 */
export function deltaText(
  value: number,
  now: number,
): { text: string; direction: 'down' | 'up' | 'same' } {
  const delta = value - now
  const direction =
    Math.abs(delta) < 0.005 ? 'same' : delta < 0 ? 'down' : 'up'
  const magnitude = Math.abs(delta).toFixed(2)
  if (direction === 'down') {
    return { text: `\u2212${magnitude} points`, direction }
  }
  if (direction === 'up') {
    return { text: `+${magnitude} points`, direction }
  }
  return { text: `${magnitude} points`, direction }
}

// ── Entries the person types ─────────────────────────────────────────────────

const USER_NUMBER_RE = /^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$/

function parseUserNumber(text: string): number | null {
  if (!USER_NUMBER_RE.test(text)) return null
  const value = Number(text.replace(',', '.'))
  return Number.isFinite(value) ? value : null
}

function findEntry(
  options: AssessmentOptions,
  attribute: string,
): AssessmentEntry | undefined {
  for (const group of options.groups) {
    for (const entry of group.entries) {
      if (entry.attribute === attribute) return entry
    }
  }
  return undefined
}

function numberText(value: number): string {
  return String(value)
}

function betweenText(entry: AssessmentEntry): string {
  const unit = displayUnit(entry.unit)
  return `${entry.label} must be between ${numberText(entry.min)} and ${numberText(entry.max)}${
    unit ? ` ${unit}` : ''
  }`
}

/** The text a field shows for the current value, or '' when not entered. */
export function entryText(entry: AssessmentEntry, entries: Entries): string {
  const value = entries[entry.attribute]
  if (value === undefined) return ''
  if (!Number.isFinite(value)) {
    throw new Error(`entries.${entry.attribute} must be a finite number`)
  }
  return numberText(value)
}

/**
 * What a person typed, read against the entry's own rules.  '' removes the
 * entry; an unreadable number, a value outside its range, or a yes/no or
 * choice value that is not offered leaves `entries` unchanged and returns the
 * sentence to show.  This never throws on the typed text.
 */
export function setEntry(
  options: AssessmentOptions,
  entries: Entries,
  attribute: string,
  text: string,
): { entries: Entries; message: string } {
  const entry = findEntry(options, attribute)
  if (!entry) {
    throw new Error(
      `assessment options: entries.${attribute} is not a declared entry`,
    )
  }

  if (typeof text !== 'string') {
    return { entries, message: `${entry.label} must be a number` }
  }

  const trimmed = text.trim()
  if (trimmed === '') {
    const next = { ...entries }
    delete next[attribute]
    return { entries: next, message: '' }
  }

  const value = parseUserNumber(trimmed)
  if (value === null) {
    return { entries, message: `${entry.label} must be a number` }
  }

  if (value < entry.min || value > entry.max) {
    return { entries, message: betweenText(entry) }
  }

  if (entry.kind === 'yesno' && value !== 0 && value !== 1) {
    return { entries, message: `${entry.label} must be 0 or 1` }
  }

  if (entry.kind === 'choice') {
    const choices = entry.options ?? []
    const allowed = choices.some((choice) => choice.value === value)
    if (!allowed) {
      const listing =
        choices.length > 0
          ? choices
              .map((choice) => `${numberText(choice.value)} (${choice.label})`)
              .join(', ')
          : 'the offered values'
      return { entries, message: `${entry.label} must be one of: ${listing}` }
    }
  }

  const next = { ...entries }
  next[attribute] = value
  return { entries: next, message: '' }
}

/** How many of each group's entries have a finite value. */
export function groupProgress(
  options: AssessmentOptions,
  entries: Entries,
): GroupProgress[] {
  return options.groups.map((group) => {
    let given = 0
    for (const entry of group.entries) {
      const value = entries[entry.attribute]
      if (value !== undefined && Number.isFinite(value)) given += 1
    }
    return {
      id: group.id,
      label: group.label,
      given,
      of: group.entries.length,
    }
  })
}

/** How many entries in the whole form have a finite value. */
export function totalProgress(
  options: AssessmentOptions,
  entries: Entries,
): { given: number; of: number } {
  let given = 0
  let of = 0
  for (const group of groupProgress(options, entries)) {
    given += group.given
    of += group.of
  }
  return { given, of }
}

/** The invented example as a fresh set of entries, or {} when there is none. */
export function fillExample(options: AssessmentOptions): Entries {
  const example = options.example
  if (example === null) return {}
  const entries: Entries = {}
  for (const key of Object.keys(example.values)) {
    const value = example.values[key]
    if (!Number.isFinite(value)) {
      throw new Error(
        `assessment options: example.values.${key} must be a finite number`,
      )
    }
    entries[key] = value
  }
  return entries
}

export function clearEntries(): Entries {
  return {}
}

/**
 * The JSON body's entries: only the declared attributes, only finite numbers.
 * Unknown keys and absent values are dropped rather than sent.
 */
export function entriesBody(
  options: AssessmentOptions,
  entries: Entries,
): Record<string, number> {
  const body: Record<string, number> = {}
  for (const group of options.groups) {
    for (const entry of group.entries) {
      const value = entries[entry.attribute]
      if (value !== undefined && Number.isFinite(value)) {
        body[entry.attribute] = value
      }
    }
  }
  return body
}

/**
 * The entry a refused server field belongs under, or null when it maps to
 * nothing the form draws.  Never throws: an unknown field is shown above the
 * action row.
 */
export function controlForEntryField(field: string): string | null {
  if (typeof field !== 'string') return null
  const match = /^entries\.([A-Za-z_][A-Za-z0-9_]*)$/.exec(field)
  return match ? match[1] : null
}

// ── Display text ─────────────────────────────────────────────────────────────

/** The model's review state, and the tone the screen draws it in. */
export function statusText(status: string | null): {
  text: string
  tone: StatusTone
} {
  if (status === 'placeholder') {
    return { text: 'Placeholder model · not validated', tone: 'placeholder' }
  }
  if (status === 'draft') {
    return { text: 'Draft model · not yet reviewed', tone: 'draft' }
  }
  if (status === 'reviewed') {
    return { text: 'Reviewed model', tone: 'reviewed' }
  }
  return { text: '', tone: 'none' }
}

function signed(value: number, places: number): string {
  const text = Math.abs(value).toFixed(places)
  return value < 0 ? `\u2212${text}` : text
}

/**
 * A change between the two outcomes as the result row prints it, and whether
 * it went down, up or stayed the same.  A missing change is an empty sentence.
 */
export function changeText(
  change: AssessmentChange | null,
): { text: string; direction: 'down' | 'up' | 'same' } {
  if (change === null) return { text: '', direction: 'same' }
  if (!isRecord(change)) {
    throw new Error('assessment answer: change must be an object or null')
  }
  const points = change.points
  const relative = change.relative_pct
  if (typeof points !== 'number' || !Number.isFinite(points)) {
    throw new Error('assessment answer: change.points must be a finite number')
  }
  if (typeof relative !== 'number' || !Number.isFinite(relative)) {
    throw new Error(
      'assessment answer: change.relative_pct must be a finite number',
    )
  }

  const direction = points < 0 ? 'down' : points > 0 ? 'up' : 'same'
  return {
    text: `${signed(points, 2)} points · ${signed(relative, 1)}%`,
    direction,
  }
}

/**
 * The top of the weekly-activity axis: at least 25, in steps of 5, high enough
 * for the current 90th percentile, the planned value, and the guideline high
 * with a little headroom.
 */
export function scaleTop(
  dose: {
    current: { p90: number } | null
    planned: { value: number } | null
  },
  range: { high: number } | null,
): number {
  let needed = 0

  if (dose.current !== null) {
    const p90 = dose.current.p90
    if (!Number.isFinite(p90)) {
      throw new Error('dose.current.p90 must be a finite number')
    }
    needed = Math.max(needed, p90)
  }

  if (dose.planned !== null) {
    const value = dose.planned.value
    if (!Number.isFinite(value)) {
      throw new Error('dose.planned.value must be a finite number')
    }
    needed = Math.max(needed, value)
  }

  if (range !== null) {
    const high = range.high
    if (!Number.isFinite(high)) {
      throw new Error('range.high must be a finite number')
    }
    needed = Math.max(needed, high * 1.15)
  }

  return Math.max(25, Math.ceil(needed / 5) * 5)
}

/** A unit written for display; the unit "1" is a pure number and prints '' . */
export function displayUnit(unit: string): string {
  return unitText(unit)
}

/**
 * A figure as the screen prints it, one decimal place by default.  A missing
 * or non-finite value is the en dash the results use for "not known".
 */
export function figureText(
  value: number | null | undefined,
  places = 1,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '\u2013'
  }
  return value.toFixed(places)
}

/** A whole number of session days, clamped to one week. */
export function clampDays(n: number): number {
  if (typeof n !== 'number' || !Number.isFinite(n)) {
    throw new Error('days_per_week must be a finite number')
  }
  return Math.min(
    DAYS_PER_WEEK_RANGE[1],
    Math.max(DAYS_PER_WEEK_RANGE[0], Math.round(n)),
  )
}
