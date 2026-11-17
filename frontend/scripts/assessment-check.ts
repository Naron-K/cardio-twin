/**
 * Checks for twin/assessment.ts (no DOM, no React, no axios).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/assessment-check.ts
 *
 * The fixtures are small copies of the real JSON the two endpoints return.
 * The checks are the executable evidence that both parsers accept that shape
 * and refuse a missing field, a wrong type, an unknown kind and an unknown
 * flag state; that a typed entry is read, comma and all, without ever letting
 * a bad value into the form; and that progress, the example, the refused
 * field, the change text, the axis top and the day clamp agree with it.
 */
import assert from 'node:assert/strict'
import {
  DAYS_PER_WEEK_RANGE,
  changeText,
  clampDays,
  clearEntries,
  controlForEntryField,
  displayUnit,
  entriesBody,
  entryText,
  fillExample,
  groupProgress,
  parseAssessmentAnswer,
  parseAssessmentOptions,
  scaleTop,
  setEntry,
  statusText,
  totalProgress,
} from '../src/twin/assessment.ts'
import type {
  AssessmentOptions,
  Entries,
} from '../src/twin/assessment.ts'

let checks = 0

function ok(value: unknown, label: string): void {
  assert.ok(value, label)
  checks += 1
}

function equal(actual: unknown, expected: unknown, label: string): void {
  assert.deepEqual(actual, expected, label)
  checks += 1
}

function throws(fn: () => unknown, pattern: RegExp, label: string): void {
  assert.throws(fn, pattern, label)
  checks += 1
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

// ── The options, as the endpoint returns them ────────────────────────────────

const OPTIONS_RAW = {
  lamina: 'lamina_health',
  name: 'Health Risk',
  groups: [
    {
      id: 'about',
      label: 'About you',
      entries: [
        {
          attribute: 'age',
          label: 'Age',
          unit: 'years',
          kind: 'number',
          why: 'Risk rises with age in every model.',
          min: 18,
          max: 100,
          options: null,
        },
        {
          attribute: 'sex_male',
          label: 'Sex',
          unit: '1',
          kind: 'choice',
          why: 'Risk models weigh the sexes differently.',
          min: 0,
          max: 1,
          options: [
            { value: 0, label: 'Female' },
            { value: 1, label: 'Male' },
          ],
        },
      ],
    },
    {
      id: 'tests',
      label: 'Test results',
      entries: [
        {
          attribute: 'sbp',
          label: 'Systolic blood pressure',
          unit: 'mmHg',
          kind: 'number',
          why: 'Resting blood pressure, from a recent reading.',
          min: 70,
          max: 260,
          options: null,
        },
        {
          attribute: 'smoker',
          label: 'Smokes now',
          unit: '1',
          kind: 'yesno',
          why: 'Smoking raises cardiovascular risk.',
          min: 0,
          max: 1,
          options: null,
        },
      ],
    },
  ],
  links: {
    current: {
      attribute: 'dose_current',
      label: 'Activity now',
      unit: 'MET-h/week',
    },
    planned: {
      attribute: 'dose_planned',
      label: 'Activity with this plan',
      unit: 'MET-h/week',
    },
  },
  range: {
    label: 'Guideline range',
    unit: 'MET-h/week',
    low: 7.5,
    high: 15,
  },
  results: [
    {
      id: 'cvd',
      label: 'Cardiovascular disease',
      period: 'over 10 years',
      unit: '%',
      status: 'placeholder',
      models: [
        {
          id: 'cvd_score',
          name: 'Cardiovascular score',
          status: 'placeholder',
          source: 'Invented coefficients. Not a published equation.',
          reviewed_by: '',
        },
      ],
      entries: ['age', 'sex_male', 'sbp', 'smoker'],
      links: ['current', 'planned'],
    },
  ],
  flags: [
    {
      attribute: 'flag_bp',
      topic: 'Resting blood pressure',
      label: 'Resting blood pressure is high',
      text: 'The blood pressure you entered is at or above the level at which guidance advises seeing a doctor.',
      status: 'placeholder',
      entries: ['sbp'],
      links: [],
    },
  ],
  example: {
    label: 'Invented example values, not a real person',
    values: { age: 52, sex_male: 0, sbp: 134, smoker: 0 },
  },
  notice:
    'Placeholder models: the figures below are not validated and are not medical advice.',
}

// ── The answer, as the endpoint returns it ───────────────────────────────────

const ANSWER_RAW = {
  subject: 'subject_demo',
  subject_label: 'Subject demo',
  dose: {
    unit: 'MET-h/week',
    current: {
      p10: 6.5943,
      p50: 21.074,
      p90: 27.0826,
      weeks: 13,
      rule: 'Days dated 2025-01-01 or later; an ISO week counts when all 7 of its days are recorded.',
    },
    planned: {
      value: 34.609,
      from_sessions: 27.98,
      from_everyday: 6.629,
      days_per_week: 5,
      session_day: 5.596,
    },
    reason: null,
  },
  assessment: {
    lamina: 'lamina_health',
    entered: { given: 4, of: 4 },
    links: { current: 21.074, planned: 34.609 },
    range: {
      label: 'Guideline range',
      unit: 'MET-h/week',
      low: 7.5,
      high: 15,
    },
    results: [
      {
        id: 'cvd',
        label: 'Cardiovascular disease',
        period: 'over 10 years',
        unit: '%',
        status: 'placeholder',
        models: [
          {
            id: 'cvd_score',
            name: 'Cardiovascular score',
            status: 'placeholder',
            source: 'Invented coefficients. Not a published equation.',
            reviewed_by: '',
          },
        ],
        now: 7.04,
        planned: 6.72,
        change: { points: -0.32, relative_pct: -4.5 },
        not_applicable: null,
        needs: {
          now: [],
          planned: [{ attribute: 'chol_hdl', label: 'HDL cholesterol' }],
        },
        reason: null,
      },
    ],
    flags: [
      {
        attribute: 'flag_bp',
        topic: 'Resting blood pressure',
        label: 'Resting blood pressure is high',
        text: 'The blood pressure you entered is high.',
        status: 'placeholder',
        state: 'clear',
        needs: [],
      },
      {
        attribute: 'flag_dose_jump',
        topic: 'Change in weekly activity',
        label: 'A large jump in weekly activity',
        text: 'This plan asks for much more weekly activity than your recordings show now.',
        status: 'placeholder',
        state: 'raised',
        needs: [{ link: 'planned', label: 'Activity with this plan' }],
      },
    ],
    notice:
      'Placeholder models: the figures below are not validated and are not medical advice.',
  },
  day: { lamina: 'lamina_wearable', planned: true },
}

// ── Both parsers accept the real shape ───────────────────────────────────────

const options: AssessmentOptions = parseAssessmentOptions(OPTIONS_RAW)
equal(options.lamina, 'lamina_health', 'options: lamina')
equal(options.groups.length, 2, 'options: groups')
equal(options.groups[1].entries[0].kind, 'number', 'options: entry kind')
equal(options.groups[0].entries[1].options?.[1].label, 'Male', 'options: choice')
equal(options.range?.high, 15, 'options: range')
equal(options.results[0].models[0].status, 'placeholder', 'options: model')
equal(options.flags[0].entries, ['sbp'], 'options: flag entries')
equal(options.example?.values.age, 52, 'options: example')
ok(options.notice !== null, 'options: notice')

const parsed = parseAssessmentAnswer(ANSWER_RAW)
equal(parsed.answer.subject, 'subject_demo', 'answer: subject')
equal(parsed.answer.dose.current?.weeks, 13, 'answer: current weeks')
equal(parsed.answer.dose.planned?.days_per_week, 5, 'answer: planned days')
equal(parsed.answer.assessment.entered, { given: 4, of: 4 }, 'answer: entered')
equal(parsed.answer.assessment.results[0].change?.points, -0.32, 'answer: change')
equal(parsed.answer.assessment.flags[1].state, 'raised', 'answer: flag state')
ok(parsed.day === ANSWER_RAW.day, 'answer: day passed through untouched')

// ── Each parser refuses a bad shape, naming the field ────────────────────────

function optionsMangled(change: (raw: typeof OPTIONS_RAW) => void): unknown {
  const raw = clone(OPTIONS_RAW)
  change(raw)
  return raw
}

function answerMangled(change: (raw: typeof ANSWER_RAW) => void): unknown {
  const raw = clone(ANSWER_RAW)
  change(raw)
  return raw
}

throws(
  () =>
    parseAssessmentOptions(
      optionsMangled((raw) => {
        delete (raw as { name?: string }).name
      }),
    ),
  /assessment options: name/,
  'options: missing field refused',
)
throws(
  () =>
    parseAssessmentOptions(
      optionsMangled((raw) => {
        ;(raw as { lamina: unknown }).lamina = 7
      }),
    ),
  /assessment options: lamina must be a string/,
  'options: wrong type refused',
)
throws(
  () =>
    parseAssessmentOptions(
      optionsMangled((raw) => {
        ;(raw.groups[0].entries[0] as { kind: unknown }).kind = 'height'
      }),
    ),
  /groups\[0\]\.entries\[0\]\.kind/,
  'options: unknown kind refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      answerMangled((raw) => {
        delete (raw as { subject?: string }).subject
      }),
    ),
  /assessment answer: subject/,
  'answer: missing field refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      answerMangled((raw) => {
        ;(raw.dose as { unit: unknown }).unit = 7
      }),
    ),
  /assessment answer: dose\.unit/,
  'answer: wrong type refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      answerMangled((raw) => {
        ;(raw.assessment.flags[0] as { state: unknown }).state = 'maybe'
      }),
    ),
  /assessment\.flags\[0\]\.state/,
  'answer: unknown flag state refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      answerMangled((raw) => {
        delete (raw as { day?: unknown }).day
      }),
    ),
  /assessment answer: day/,
  'answer: missing day refused',
)

// ── Typing an entry ──────────────────────────────────────────────────────────

const empty: Entries = clearEntries()
equal(empty, {}, 'clearEntries')

const valid = setEntry(options, empty, 'sbp', '134')
equal(valid.message, '', 'setEntry: valid number accepted')
equal(valid.entries, { sbp: 134 }, 'setEntry: valid number stored')
equal(entryText(options.groups[1].entries[0], valid.entries), '134', 'entryText')

const comma = setEntry(options, valid.entries, 'age', '52,5')
equal(comma.message, '', 'setEntry: decimal comma accepted')
equal(comma.entries.age, 52.5, 'setEntry: decimal comma value')

const removed = setEntry(options, comma.entries, 'age', '')
equal(removed.message, '', 'setEntry: empty removes')
equal(removed.entries, { sbp: 134 }, 'setEntry: empty removed the key')
equal(entryText(options.groups[0].entries[0], removed.entries), '', 'entryText empty')

const before: Entries = { sbp: 134 }
const outOfRange = setEntry(options, before, 'sbp', '900')
equal(
  outOfRange.message,
  'Systolic blood pressure must be between 70 and 260 mmHg',
  'setEntry: out of range message',
)
equal(outOfRange.entries, before, 'setEntry: out of range unchanged')
ok(outOfRange.entries === before, 'setEntry: out of range same object')

const notANumber = setEntry(options, before, 'sbp', 'NaN')
equal(notANumber.message, 'Systolic blood pressure must be a number', 'setEntry: NaN message')
equal(notANumber.entries, before, 'setEntry: NaN unchanged')

const text = setEntry(options, before, 'sbp', '12 high')
equal(text.message, 'Systolic blood pressure must be a number', 'setEntry: text message')
equal(text.entries, before, 'setEntry: text unchanged')

const yesno = setEntry(options, empty, 'smoker', '2')
ok(yesno.message.length > 0, 'setEntry: yesno 2 message')
equal(yesno.entries, {}, 'setEntry: yesno 2 unchanged')

const yesnoFraction = setEntry(options, empty, 'smoker', '0,5')
equal(yesnoFraction.message, 'Smokes now must be 0 or 1', 'setEntry: yesno fraction message')

const choice = setEntry(options, empty, 'sex_male', '0,5')
equal(
  choice.message,
  'Sex must be one of: 0 (Female), 1 (Male)',
  'setEntry: choice message',
)
equal(choice.entries, {}, 'setEntry: choice unchanged')

// ── Progress, the example and the body ───────────────────────────────────────

const partial: Entries = { age: 52, sbp: 134 }
equal(
  groupProgress(options, partial),
  [
    { id: 'about', label: 'About you', given: 1, of: 2 },
    { id: 'tests', label: 'Test results', given: 1, of: 2 },
  ],
  'groupProgress',
)
equal(totalProgress(options, partial), { given: 2, of: 4 }, 'totalProgress')

const example = fillExample(options)
equal(
  example,
  { age: 52, sex_male: 0, sbp: 134, smoker: 0 },
  'fillExample copies the values',
)
equal(entriesBody(options, example), example, 'fillExample then entriesBody')

equal(
  entriesBody(options, { age: 52, banana: 3, sbp: Number.NaN, smoker: Infinity }),
  { age: 52 },
  'entriesBody drops unknown and non-finite',
)
equal(fillExample({ ...options, example: null }), {}, 'fillExample without an example')

// ── The refused field, the state and the change ──────────────────────────────

equal(controlForEntryField('entries.sbp'), 'sbp', 'control: entries.sbp')
equal(controlForEntryField('entries.chol_hdl'), 'chol_hdl', 'control: entries.chol_hdl')
equal(controlForEntryField('entries'), null, 'control: entries')
equal(controlForEntryField('entries.'), null, 'control: entries.')
equal(controlForEntryField('plan.subject'), null, 'control: plan.subject')
for (const junk of [undefined, null, 7, {}, []]) {
  equal(
    controlForEntryField(junk as unknown as string),
    null,
    `control: ${String(junk)}`,
  )
}

equal(
  statusText('placeholder'),
  { text: 'Placeholder model · not validated', tone: 'placeholder' },
  'status: placeholder',
)
equal(
  statusText('draft'),
  { text: 'Draft model · not yet reviewed', tone: 'draft' },
  'status: draft',
)
equal(statusText('reviewed'), { text: 'Reviewed model', tone: 'reviewed' }, 'status: reviewed')
equal(statusText(null), { text: '', tone: 'none' }, 'status: null')
equal(statusText('other'), { text: '', tone: 'none' }, 'status: other')

const down = changeText({ points: -0.34, relative_pct: -4.8 })
equal(down.text, '\u22120.34 points · \u22124.8%', 'change: down text')
equal(down.direction, 'down', 'change: down direction')

const up = changeText({ points: 0.4, relative_pct: 5 })
equal(up.text, '0.40 points · 5.0%', 'change: up text')
equal(up.direction, 'up', 'change: up direction')

const same = changeText({ points: 0, relative_pct: 0 })
equal(same.text, '0.00 points · 0.0%', 'change: zero text')
equal(same.direction, 'same', 'change: zero direction')
equal(changeText(null), { text: '', direction: 'same' }, 'change: missing')

// ── The axis top and the day clamp ───────────────────────────────────────────

equal(
  scaleTop({ current: { p90: 5 }, planned: { value: 10 } }, { high: 8 }),
  25,
  'scaleTop: small values stop at 25',
)
equal(
  scaleTop({ current: { p90: 5 }, planned: { value: 103 } }, { high: 8 }),
  105,
  'scaleTop: large planned value rounds up in steps of 5',
)
equal(
  scaleTop({ current: null, planned: null }, { high: 44 }),
  55,
  'scaleTop: range high gets headroom',
)

equal(DAYS_PER_WEEK_RANGE, [0, 7], 'DAYS_PER_WEEK_RANGE')
equal(clampDays(-1), 0, 'clampDays: -1')
equal(clampDays(3.6), 4, 'clampDays: 3.6')
equal(clampDays(9), 7, 'clampDays: 9')

// ── Display units ────────────────────────────────────────────────────────────

equal(displayUnit('1'), '', 'displayUnit: 1')
equal(displayUnit('mmHg'), 'mmHg', 'displayUnit: mmHg')
equal(displayUnit('MET-h/week'), 'MET-h/week', 'displayUnit: MET-h/week')

console.log(`assessment-check: ${checks} checks passed`)
