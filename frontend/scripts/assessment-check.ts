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
 *
 * The added fields are checked against the shapes the running backend returns:
 * several examples, measured values, horizons, mediators and fitness, plus the
 * helpers that pick a horizon, scale the factors and print a profile or a move.
 */
import assert from 'node:assert/strict'
import {
  DAYS_PER_WEEK_RANGE,
  DEFAULT_DAYS_PER_WEEK,
  changeText,
  clampDays,
  clearEntries,
  controlForEntryField,
  decimalsFor,
  deltaText,
  displayUnit,
  entriesBody,
  entryText,
  fillExample,
  fillProfile,
  groupProgress,
  horizonChoices,
  horizonShort,
  mediatorPoint,
  mediatorScale,
  needText,
  parseAssessmentAnswer,
  parseAssessmentOptions,
  profileOf,
  readDaysParam,
  scaleTop,
  setEntry,
  statusText,
  totalProgress,
  valueAtHorizon,
  writeDaysParam,
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

// ── The added fields, as the real answers carry them ─────────────────────────

const ADAPTATION_MODEL = {
  id: 'adapt_glucose_fasting',
  name: 'Fasting glucose: adaptation',
  status: 'placeholder',
  source: 'Invented numbers in the shape training trials report. Not a published model.',
  reviewed_by: '',
}

const NEW_OPTIONS_RAW = {
  ...OPTIONS_RAW,
  example: {
    label: 'Low risk · invented example',
    values: { age: 38, sex_male: 0, sbp: 112, smoker: 0 },
  },
  examples: [
    {
      id: 'low',
      label: 'Low risk · invented example',
      values: { age: 38, sex_male: 0, sbp: 112, smoker: 0 },
    },
    {
      id: 'borderline',
      label: 'Borderline / prediabetes · invented example',
      values: { age: 52, sex_male: 1, sbp: 134, smoker: 0 },
    },
  ],
  measured: [
    {
      key: 'resting_hr',
      attribute: 'resting_hr',
      label: 'Resting heart rate, from your recordings',
      unit: 'bpm',
    },
  ],
  horizons: {
    attribute: 'weeks',
    unit: 'weeks',
    values: [0, 4, 8, 12],
    settled: 1000,
    settled_label: 'Settled',
  },
  mediators: [
    {
      now: 'glucose_fasting',
      at: 'glucose_fasting_at',
      label: 'Fasting glucose',
      unit: 'mmol/L',
      source: 'entered',
      key: null,
      still: null,
      status: 'placeholder',
      models: [ADAPTATION_MODEL],
    },
    {
      now: 'resting_hr',
      at: 'resting_hr_at',
      label: 'Resting heart rate',
      unit: 'bpm',
      source: 'measured',
      key: 'resting_hr',
      still: null,
      status: 'placeholder',
      models: [ADAPTATION_MODEL],
    },
  ],
}

const NEW_ANSWER_RAW = {
  ...ANSWER_RAW,
  dose: {
    ...ANSWER_RAW.dose,
    fitness: { resting_hr: 66, vo2max: 26.13 },
  },
  assessment: {
    ...ANSWER_RAW.assessment,
    horizons: {
      attribute: 'weeks',
      unit: 'weeks',
      values: [0, 4, 8, 12],
      settled: 1000,
      settled_label: 'Settled',
    },
    results: [
      {
        ...ANSWER_RAW.assessment.results[0],
        series: [
          { weeks: 0, value: 14.3 },
          { weeks: 4, value: 12.92 },
          { weeks: 8, value: 12.16 },
          { weeks: 12, value: 11.7 },
        ],
        settled: 10.74,
      },
    ],
    mediators: [
      {
        now: 'glucose_fasting',
        label: 'Fasting glucose',
        unit: 'mmol/L',
        source: 'entered',
        key: null,
        still: null,
        status: 'placeholder',
        value_now: 6.3,
        series: [
          { weeks: 0, value: 6.3 },
          { weeks: 4, value: 6.19 },
          { weeks: 8, value: 6.11 },
          { weeks: 12, value: 6.06 },
        ],
        settled: 5.93,
        moves: true,
        needs: [{ attribute: 'glucose_fasting', label: 'Fasting glucose' }],
      },
      {
        now: 'chol_total',
        label: 'Total cholesterol',
        unit: 'mmol/L',
        source: 'entered',
        key: null,
        still: 'Not expected to change with activity alone.',
        status: 'placeholder',
        value_now: 5.8,
        series: [
          { weeks: 0, value: 5.8 },
          { weeks: 4, value: 5.8 },
          { weeks: 8, value: 5.8 },
          { weeks: 12, value: 5.8 },
        ],
        settled: 5.8,
        moves: false,
        needs: [],
      },
      {
        now: 'vo2max',
        label: 'VO2max',
        unit: 'mL/kg/min',
        source: 'measured',
        key: 'vo2max',
        still: null,
        status: 'placeholder',
        value_now: null,
        series: [],
        settled: null,
        moves: true,
        needs: [{ measured: 'vo2max', label: 'VO2max' }],
      },
    ],
  },
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

// An older server returns none of the added fields: each is empty, not fatal.
equal(options.examples, [], 'options: absent examples')
equal(options.measured, [], 'options: absent measured')
equal(options.horizons, null, 'options: absent horizons')
equal(options.mediators, [], 'options: absent mediators')
equal(parsed.answer.dose.fitness, {}, 'answer: absent fitness')
equal(parsed.answer.assessment.horizons, null, 'answer: absent horizons')
equal(parsed.answer.assessment.mediators, [], 'answer: absent mediators')
equal(parsed.answer.assessment.results[0].series, [], 'answer: absent series')
equal(parsed.answer.assessment.results[0].settled, null, 'answer: absent settled')

const newOptions = parseAssessmentOptions(NEW_OPTIONS_RAW)
equal(newOptions.examples.length, 2, 'options: examples')
equal(newOptions.examples[1].id, 'borderline', 'options: example id')
equal(newOptions.examples[0].values.age, 38, 'options: example profile values')
equal(newOptions.example?.values.age, 38, 'options: singular example kept')
equal(newOptions.measured[0].key, 'resting_hr', 'options: measured key')
equal(newOptions.horizons?.values, [0, 4, 8, 12], 'options: horizons values')
equal(newOptions.mediators[1].source, 'measured', 'options: mediator source')

const newAnswer = parseAssessmentAnswer(NEW_ANSWER_RAW)
equal(newAnswer.answer.dose.fitness.vo2max, 26.13, 'answer: fitness')
equal(
  newAnswer.answer.assessment.horizons?.settled_label,
  'Settled',
  'answer: horizons',
)
equal(
  newAnswer.answer.assessment.results[0].series[2].value,
  12.16,
  'answer: result series',
)
equal(newAnswer.answer.assessment.results[0].settled, 10.74, 'answer: result settled')
equal(
  newAnswer.answer.assessment.mediators[0].value_now,
  6.3,
  'answer: mediator value now',
)
equal(
  newAnswer.answer.assessment.mediators[0].moves,
  true,
  'answer: mediator moves',
)
equal(
  newAnswer.answer.assessment.mediators[1].still,
  'Not expected to change with activity alone.',
  'answer: mediator still',
)
equal(
  newAnswer.answer.assessment.mediators[2].needs[0],
  { measured: 'vo2max', label: 'VO2max' },
  'answer: measured need',
)

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

function newOptionsMangled(
  change: (raw: typeof NEW_OPTIONS_RAW) => void,
): unknown {
  const raw = clone(NEW_OPTIONS_RAW)
  change(raw)
  return raw
}

function newAnswerMangled(
  change: (raw: typeof NEW_ANSWER_RAW) => void,
): unknown {
  const raw = clone(NEW_ANSWER_RAW)
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
throws(
  () =>
    parseAssessmentAnswer(
      newAnswerMangled((raw) => {
        raw.assessment.results[0].series[0].value =
          Number.POSITIVE_INFINITY
      }),
    ),
  /assessment\.results\[0\]\.series\[0\]\.value must be a finite number or null/,
  'answer: non-finite series refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      newAnswerMangled((raw) => {
        raw.assessment.results[0].series.pop()
      }),
    ),
  /assessment\.results\[0\]\.series must have as many entries as the horizons/,
  'answer: series of the wrong length refused',
)
throws(
  () =>
    parseAssessmentAnswer(
      newAnswerMangled((raw) => {
        ;(raw.assessment.mediators[0] as { source: unknown }).source =
          'invented'
      }),
    ),
  /assessment\.mediators\[0\]\.source must be 'entered' or 'measured'/,
  'answer: unknown mediator source refused',
)
throws(
  () =>
    parseAssessmentOptions(
      newOptionsMangled((raw) => {
        ;(raw.examples[1] as { id: unknown }).id = 'low'
      }),
    ),
  /examples\[1\]\.id must be unique/,
  'options: duplicate example id refused',
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

// ── The `days` parameter in the link ─────────────────────────────────────────

equal(DEFAULT_DAYS_PER_WEEK, 3, 'days: default')
equal(readDaysParam('?days=0'), 0, 'days: 0 is read')
equal(readDaysParam('?days=3'), 3, 'days: 3 is read')
equal(readDaysParam('?days=7'), 7, 'days: 7 is read')
equal(readDaysParam('?plan=x&days=5'), 5, 'days: read beside the plan')
equal(readDaysParam('?days=8'), 3, 'days: above 7 is ignored')
equal(readDaysParam('?days=-1'), 3, 'days: below 0 is ignored')
equal(readDaysParam('?days=3.5'), 3, 'days: a fraction is ignored')
equal(readDaysParam('?days=abc'), 3, 'days: text is ignored')
equal(readDaysParam('?days='), 3, 'days: empty is ignored')
equal(readDaysParam('?plan=x'), 3, 'days: absent is the typical 3')
equal(readDaysParam(''), 3, 'days: no query is the typical 3')

equal(writeDaysParam('?plan=x', 5), 'plan=x&days=5', 'days: written beside the plan')
equal(writeDaysParam('?days=2&plan=x', 4), 'days=4&plan=x', 'days: rewritten in place')
equal(writeDaysParam('?days=2', 9), 'days=7', 'days: clamped when written')

// ── Horizons, profiles and factor movement ──────────────────────────────────

const horizons = newAnswer.answer.assessment.horizons
if (horizons === null) throw new Error('fixture: horizons must be present')
const choices = horizonChoices(horizons)
equal(choices.length, 5, 'horizons: one per value then settled')
equal(
  choices.map((choice) => choice.label),
  ['Now', '4 weeks', '8 weeks', '12 weeks', 'Settled'],
  'horizons: labels',
)
equal(
  choices.map((choice) => choice.settled),
  [false, false, false, false, true],
  'horizons: settled flag',
)
equal(choices[4].weeks, null, 'horizons: settled has no weeks')
equal(choices[4].index, 4, 'horizons: settled index after the values')
equal(horizonChoices(null), [], 'horizons: null has no choices')

const seriesResult = newAnswer.answer.assessment.results[0]
equal(valueAtHorizon(seriesResult, choices[2]), 12.16, 'horizons: value at 8 weeks')
equal(valueAtHorizon(seriesResult, choices[4]), 10.74, 'horizons: settled value')
equal(horizonShort(choices[0]), 'Now', 'horizons: short now')
equal(horizonShort(choices[1]), '4 wk', 'horizons: short 4 wk')
equal(horizonShort(choices[4]), 'Settled', 'horizons: short settled')

const mediators = newAnswer.answer.assessment.mediators
const scale = mediatorScale(mediators, choices)
ok(Math.abs(scale - 0.0587) < 0.001, 'mediators: shared scale from moving factors')
equal(
  mediatorScale([mediators[1]], choices),
  0.02,
  'mediators: a non-moving factor is ignored',
)
equal(mediatorScale([], choices), 0.02, 'mediators: empty scale is at least 0.02')
equal(mediatorPoint(100, 6.3, scale), 1, 'mediators: point clamps up')
equal(mediatorPoint(-100, 6.3, scale), -1, 'mediators: point clamps down')
ok(
  Math.abs(mediatorPoint(5.93, 6.3, scale) + 1) < 1e-9,
  'mediators: settled move reaches the scale',
)
equal(mediatorPoint(null, 6.3, scale), 0, 'mediators: a missing value is zero')

equal(decimalsFor(9.99), 2, 'decimals: below 10')
equal(decimalsFor(10), 1, 'decimals: at 10')
equal(decimalsFor(-12.5), 1, 'decimals: above 10 in size')

const profileEntries = fillProfile(newOptions, 'low')
equal(
  profileEntries,
  { age: 38, sex_male: 0, sbp: 112, smoker: 0 },
  'profile: fill copies the example',
)
equal(profileOf(newOptions, profileEntries), 'low', 'profile: found exactly')
equal(
  profileOf(newOptions, { ...profileEntries, age: 39 }),
  null,
  'profile: one changed entry is no profile',
)
profileEntries.age = 99
equal(
  newOptions.examples[0].values.age,
  38,
  'profile: mutating the copy leaves the options alone',
)
throws(
  () => fillProfile(newOptions, 'nope'),
  /examples\.nope is not a declared example/,
  'profile: unknown id refused',
)

equal(
  needText({ attribute: 'sbp', label: 'Systolic blood pressure' }),
  'Systolic blood pressure',
  'need: attribute label',
)
equal(
  needText({ link: 'planned', label: 'Activity with this plan' }),
  'Activity with this plan',
  'need: link label',
)
equal(
  needText({ measured: 'vo2max', label: 'VO2max' }),
  'VO2max',
  'need: measured label',
)

equal(
  deltaText(7.4, 10),
  { text: '\u22122.60 points', direction: 'down' },
  'delta: down',
)
equal(deltaText(12, 10), { text: '+2.00 points', direction: 'up' }, 'delta: up')
equal(
  deltaText(10.001, 10),
  { text: '0.00 points', direction: 'same' },
  'delta: same',
)

// ── Display units ────────────────────────────────────────────────────────────

equal(displayUnit('1'), '', 'displayUnit: 1')
equal(displayUnit('mmHg'), 'mmHg', 'displayUnit: mmHg')
equal(displayUnit('MET-h/week'), 'MET-h/week', 'displayUnit: MET-h/week')

console.log(`assessment-check: ${checks} checks passed`)
