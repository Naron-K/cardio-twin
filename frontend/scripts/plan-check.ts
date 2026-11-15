/**
 * Checks for twin/planDay.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/plan-check.ts
 *
 * The executable evidence that Level and Target agree with the settle table
 * both ways, that no wanted slider value can make an overlap or leave the
 * waking hours, that a count follows its length until it is touched, that the
 * link round-trips, and that malformed input is refused rather than drawn.
 */
import assert from 'node:assert/strict'
import {
  addSession,
  controlForField,
  decodePlan,
  encodePlan,
  intensityFor,
  parsePlanOptions,
  parsePlannedDay,
  planBody,
  planFromOptions,
  removeSession,
  sessionHour,
  setAwakeEnd,
  setAwakeStart,
  setCount,
  setDay,
  setIntensity,
  setKind,
  setLength,
  setStart,
  setTarget,
  settleAt,
  targetOf,
  targetRange,
  unitText,
} from '../src/twin/planDay.ts'
import type { Plan, PlanOptions } from '../src/twin/planDay.ts'

const HOURS = Array.from({ length: 24 }, (_, hour) => hour)
const POINTS = [2, 3, 4, 5, 6]

function settleValues(offset: number): number[][] {
  return HOURS.map((hour) =>
    POINTS.map((point) => Math.round((80 + offset + hour * 0.4 + point * 6) * 100) / 100),
  )
}

const RAW = {
  lamina: 'lamina_test',
  subject: 'subject_demo',
  subject_label: 'Subject demo',
  applies_to: 'Subject demo only',
  fitted: true,
  coefficients_applies_to: null,
  roles: {
    intensity: { attribute: 'AE_rate', label: 'Level', unit: 'kcal/min' },
    settles: { attribute: 'HR_target', label: 'Settles near', unit: 'bpm' },
    count: { attribute: 'step_rate', label: 'Steps', unit: 'steps/min' },
    ambient: { attribute: 'T_app', label: 'Outdoor temperature', unit: 'degC' },
    level: { attribute: 'HR_level', label: 'Resting level', unit: 'bpm' },
    clock: { attribute: 'hour_local', label: 'Clock hour', unit: 'h' },
  },
  kinds: [
    {
      id: 'walk',
      label: 'Walk',
      sessions: 33,
      minutes: 1156,
      intensity: { p10: 2, p50: 4, p90: 6, unit: 'kcal/min' },
      steps_per_min: 120,
      settle: { hours: HOURS, intensities: POINTS, values: settleValues(0) },
    },
    {
      id: 'strength',
      label: 'Strength',
      sessions: 20,
      minutes: 1028,
      intensity: { p10: 2, p50: 4, p90: 6, unit: 'kcal/min' },
      steps_per_min: 30,
      settle: { hours: HOURS, intensities: POINTS, values: settleValues(6) },
    },
  ],
  day: {
    awake: { start: 380, end: 1345 },
    ambient: { min: 10, max: 30, default: 20, unit: 'degC' },
    level: { min: 60, max: 90, default: 75, recorded: [75, 79], unit: 'bpm' },
    count_outside: {
      min: 0,
      max: 20000,
      default: 8000,
      p10: 5000,
      p90: 15000,
      unit: 'steps',
    },
    settle_at: { level: 75, ambient: 20 },
  },
  default_plan: {
    awake: [380, 1345],
    ambient: 20,
    level: 75,
    count_outside: 8000,
    sessions: [
      { kind: 'walk', start: 450, minutes: 30, intensity: 4, count: 3600, target: 110 },
      { kind: 'strength', start: 1080, minutes: 45, intensity: 4, count: 1350, target: 105 },
    ],
  },
  projection_error: null,
  limits: { max_sessions: 6, session_minutes: [5, 180], step_minutes: 5 },
  limits_text: ['Steps outside sessions: as set'],
}

const options: PlanOptions = parsePlanOptions(RAW)
const walk = options.kinds[0]
const strength = options.kinds[1]

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function threeSessionPlan(): Plan {
  const plan = planFromOptions(options)
  plan.sessions = [
    { kind: 'walk', start: 450, minutes: 30, intensity: 4, count: 3600, countTouched: false },
    { kind: 'strength', start: 600, minutes: 45, intensity: 4, count: 1350, countTouched: false },
    { kind: 'walk', start: 800, minutes: 30, intensity: 4, count: 3600, countTouched: false },
  ]
  return plan
}

function assertPlanValid(plan: Plan, label: string): void {
  assert.ok(plan.awake[0] >= 240 && plan.awake[0] <= 720, `${label}: awake start`)
  assert.ok(plan.awake[1] >= 1080 && plan.awake[1] <= 1435, `${label}: awake end`)
  assert.ok(plan.awake[0] < plan.awake[1], `${label}: awake order`)

  plan.sessions.forEach((session, index) => {
    const kind = options.kinds.find((entry) => entry.id === session.kind)
    assert.ok(kind, `${label}: session ${index + 1} kind`)
    assert.ok(
      session.start >= plan.awake[0],
      `${label}: session ${index + 1} starts inside the day`,
    )
    assert.ok(
      session.start + session.minutes <= plan.awake[1],
      `${label}: session ${index + 1} ends inside the day`,
    )
    assert.ok(
      session.minutes >= options.limits.session_minutes[0] &&
        session.minutes <= options.limits.session_minutes[1],
      `${label}: session ${index + 1} length`,
    )
    assert.ok(
      session.intensity >= kind!.intensity.p10 &&
        session.intensity <= kind!.intensity.p90,
      `${label}: session ${index + 1} intensity`,
    )
    const highest = Math.round(kind!.steps_per_min * 180 * 1.5)
    assert.ok(
      session.count >= 0 && session.count <= highest,
      `${label}: session ${index + 1} count`,
    )
  })

  for (let first = 0; first < plan.sessions.length; first += 1) {
    for (let second = first + 1; second < plan.sessions.length; second += 1) {
      const a = plan.sessions[first]
      const b = plan.sessions[second]
      assert.ok(
        !(a.start < b.start + b.minutes && b.start < a.start + a.minutes),
        `${label}: sessions ${first + 1} and ${second + 1} overlap`,
      )
    }
  }
}

// ── The settle table ─────────────────────────────────────────────────────────

for (const hour of [0, 7, 12, 23]) {
  for (const point of [2, 2.5, 3.3, 4.7, 5.6, 6]) {
    const settled = settleAt(walk, point, hour)
    const back = intensityFor(walk, settled, hour)
    assert.ok(Math.abs(back - point) < 1e-9, `inverse at hour ${hour}, ${point}`)
  }

  // Below the first point and above the last are the table's own ends.
  assert.equal(settleAt(walk, 1, hour), settleAt(walk, 2, hour))
  assert.equal(settleAt(walk, 9, hour), settleAt(walk, 6, hour))
  assert.equal(intensityFor(walk, settleAt(walk, 2, hour) - 50, hour), 2)
  assert.equal(intensityFor(walk, settleAt(walk, 6, hour) + 50, hour), 6)

  assert.deepEqual(targetRange(walk, hour), [
    Math.round(settleAt(walk, 2, hour)),
    Math.round(settleAt(walk, 6, hour)),
  ])
}

// ── Level and Target follow each other ───────────────────────────────────────

const base = threeSessionPlan()
const hour = sessionHour(base.sessions[0])
const wantedBpm = Math.round(settleAt(walk, 4.5, hour))

const targeted = setTarget(base, 0, wantedBpm, options).plan
assert.equal(targetOf(targeted, 0, options), wantedBpm)

const levelled = setIntensity(base, 0, 4.7, options).plan
assert.equal(
  targetOf(levelled, 0, options),
  Math.round(settleAt(walk, 4.7, sessionHour(levelled.sessions[0]))),
)

// A target past the table's ends stops at p90 (and at p10 below it).
assert.equal(setTarget(base, 0, 999, options).plan.sessions[0].intensity, 6)
assert.equal(setTarget(base, 0, -999, options).plan.sessions[0].intensity, 2)

// ── No edit can make an overlap or leave the waking hours ────────────────────
// A small deterministic generator, so a failure names the same wanted value.

let seed = 20261115
function random(): number {
  seed = (seed * 1664525 + 1013904223) >>> 0
  return seed / 4294967296
}

for (let round = 0; round < 600; round += 1) {
  const index = Math.floor(random() * 3)
  const wanted = Math.floor(random() * 3000) - 500

  const moved = setStart(threeSessionPlan(), index, wanted)
  assertPlanValid(moved.plan, `setStart(${index}, ${wanted})`)

  const lengthened = setLength(threeSessionPlan(), index, wanted, options)
  assertPlanValid(lengthened.plan, `setLength(${index}, ${wanted})`)
}

// The awake sliders stop at the sessions and say why.
const started = setAwakeStart(base, 600)
assert.equal(started.plan.awake[0], 450)
assert.equal(started.message, 'Session 1 starts 07:30')

// The slider's own lower end is 18:00, so a session that ends before it does
// not stop the slider; the typical plan's late session does.
const typical = planFromOptions(options)
const ended = setAwakeEnd(typical, 1100)
assert.equal(ended.plan.awake[1], 1125)
assert.equal(ended.message, 'Session 2 ends 18:45')

assert.equal(setAwakeEnd(base, 700).plan.awake[1], 1080)
assert.equal(setAwakeEnd(base, 700).message, '')
assert.equal(setAwakeStart(base, 450).message, '')
assert.equal(setAwakeEnd(typical, 1200).message, '')

// ── The count follows the length until it is touched ─────────────────────────

let counted = setLength(base, 0, 60, options).plan
assert.equal(counted.sessions[0].count, Math.round(walk.steps_per_min * 60))
counted = setCount(counted, 0, 123, options).plan
assert.equal(counted.sessions[0].count, 123)
counted = setLength(counted, 0, 90, options).plan
assert.equal(counted.sessions[0].count, 123)

// A kind change returns to its typical count and lets length follow again.
const rekinded = setKind(counted, 0, 'strength', options).plan
assert.equal(rekinded.sessions[0].intensity, strength.intensity.p50)
assert.equal(
  rekinded.sessions[0].count,
  Math.round(strength.steps_per_min * rekinded.sessions[0].minutes),
)
assert.equal(rekinded.sessions[0].countTouched, false)

// ── Adding sessions ──────────────────────────────────────────────────────────

const full: Plan = {
  ...base,
  sessions: Array.from({ length: 6 }, (_, index) => ({
    kind: 'walk',
    start: 450 + index * 100,
    minutes: 30,
    intensity: 4,
    count: 3600,
    countTouched: false,
  })),
}
const atLimit = addSession(full, options)
assert.equal(atLimit.message, 'No free 30 min')
assert.deepEqual(atLimit.plan, full)

const packed: Plan = {
  ...base,
  awake: [720, 1080],
  sessions: [
    { kind: 'walk', start: 720, minutes: 180, intensity: 4, count: 21600, countTouched: false },
    { kind: 'walk', start: 900, minutes: 180, intensity: 4, count: 21600, countTouched: false },
  ],
}
const noFit = addSession(packed, options)
assert.equal(noFit.message, 'No free 30 min')
assert.deepEqual(noFit.plan, packed)

const added = addSession(base, options)
assert.equal(added.message, '')
assert.equal(added.plan.sessions.length, 4)
assertPlanValid(added.plan, 'addSession')
assert.equal(removeSession(added.plan, 3).plan.sessions.length, 3)

// ── The link ─────────────────────────────────────────────────────────────────

const text = encodePlan(base)
assert.deepEqual(decodePlan(text, options), base)
assert.deepEqual(decodePlan(encodePlan(planFromOptions(options)), options), planFromOptions(options))

const badLinks = [
  '',
  'x',
  `2${text.slice(1)}`,
  encodePlan({
    ...base,
    sessions: [{ ...base.sessions[0], kind: 'swim' }],
  }),
  encodePlan({ ...base, level: 999 }),
  encodePlan({
    ...base,
    sessions: [{ ...base.sessions[0], intensity: 7 }],
  }),
  encodePlan({
    ...base,
    sessions: [{ ...base.sessions[0], start: 300 }],
  }),
]
for (const link of badLinks) assert.equal(decodePlan(link, options), null, link)

// The body carries the target each session settles near.
const body = planBody(base, 'subject_demo', options)
assert.equal(body.subject, 'subject_demo')
assert.equal(body.sessions[0].target, targetOf(base, 0, options))
assert.deepEqual(body.awake, base.awake)

// ── Bad options are refused with the field named ─────────────────────────────

function mangled(change: (raw: typeof RAW) => void): unknown {
  const raw = clone(RAW)
  change(raw)
  return raw
}

assert.throws(() => parsePlanOptions({} as unknown), /plan options: kinds/)
assert.throws(
  () =>
    parsePlanOptions(
      mangled((raw) => {
        delete (raw as { subject_label?: string }).subject_label
      }),
    ),
  /subject_label/,
)
assert.throws(
  () =>
    parsePlanOptions(
      mangled((raw) => {
        raw.kinds[0].settle.values[0].push(1)
      }),
    ),
  /kinds\[0\]\.settle\.values\[0\]/,
)
assert.throws(
  () =>
    parsePlanOptions(
      mangled((raw) => {
        raw.kinds[1].settle.intensities[2] = raw.kinds[1].settle.intensities[1]
      }),
    ),
  /kinds\[1\]\.settle\.intensities/,
)

// ── NaN and Infinity never make a plan invalid ───────────────────────────────

const numericalEdits: [string, (value: number) => { plan: Plan }][] = [
  ['setAwakeStart', (value) => setAwakeStart(base, value)],
  ['setAwakeEnd', (value) => setAwakeEnd(base, value)],
  ['setStart', (value) => setStart(base, 0, value)],
  ['setLength', (value) => setLength(base, 0, value, options)],
  ['setIntensity', (value) => setIntensity(base, 0, value, options)],
  ['setTarget', (value) => setTarget(base, 0, value, options)],
  ['setCount', (value) => setCount(base, 0, value, options)],
  ['setDay', (value) => setDay(base, 'level', value, options)],
]

for (const [name, edit] of numericalEdits) {
  for (const value of [NaN, Infinity, -Infinity]) {
    const result = edit(value)
    assertPlanValid(result.plan, `${name}(${String(value)})`)
    assert.deepEqual(result.plan, base, `${name}(${String(value)}) is a no-op`)
  }
}

// ── The answer to a run ──────────────────────────────────────────────────────

function plannedResponse(): Record<string, unknown> {
  const n = 8
  return {
    lamina: 'lamina_test',
    subject: 'subject_demo',
    subject_label: 'Subject demo',
    date: '2000-01-01',
    timezone: 'UTC',
    synthetic: true,
    n_minutes: n,
    pair: {
      label: 'Heart rate',
      unit: 'bpm',
      measured: Array<number | null>(n).fill(null),
      modelled: [null, null, 100, 101, 102, 101, 100, null],
    },
    rates: [
      {
        attribute: 'AE_rate',
        label: 'Level',
        unit: 'kcal',
        values: [0, 0, 3, 3, 3, 3, 0, 0],
      },
      {
        attribute: 'step_rate',
        label: 'Steps',
        unit: 'steps',
        values: [0, 0, 10, 10, 10, 10, 0, 0],
      },
    ],
    events: [{ indicator: 'is_walk', group: 'walk', label: 'Walk' }],
    gaps: [[6, 8]],
    sessions: [
      {
        start: 2,
        end: 6,
        minutes: 4,
        label: 'Walking',
        group: 'walk',
        group_label: 'Walk',
        mean_measured: null,
        peak_measured: null,
        mean_modelled: 101,
        n_paired: 0,
        difference: null,
        rate_totals: { AE_rate: 12, step_rate: 40 },
        verdict: null,
        target_set: 110,
        intensity_set: 3,
        count_set: 40,
        peak_modelled: 102,
      },
    ],
    kpis: [
      { key: 'AE_rate', label: 'Level', value: 12, unit: 'kcal', note: '± 51 kcal' },
      { key: 'step_rate', label: 'Steps', value: 40, unit: 'steps', note: 'as set' },
      { key: 'sessions', label: 'In sessions', value: 4, unit: 'min', note: '1 sessions' },
      {
        key: 'peak_modelled',
        label: 'Highest heart rate',
        value: 102,
        unit: 'bpm',
        note: 'at 00:04',
      },
    ],
    summary: null,
    model: {
      sd: 10,
      sd_source: 'projection',
      fitted: true,
      applies_to: 'Subject demo only',
    },
    planned: true,
    projection_error: { hr_mae: 10, energy_mae: 51 },
    limits_text: [
      'Steps outside sessions: as set',
      'No fatigue, recovery, sleep or night',
    ],
  }
}

const planned = parsePlannedDay(plannedResponse())
assert.equal(planned.day.summary, '')
assert.equal(planned.day.sessions[0].verdict, 'too_few')
assert.equal(planned.day.model.sd_source, 'projection')
assert.deepEqual(planned.extras.sessions, [
  { start: 2, target_set: 110, intensity_set: 3, count_set: 40, peak_modelled: 102 },
])
assert.equal(planned.extras.limits_text.length, 2)
assert.deepEqual(planned.extras.projection_error, { hr_mae: 10, energy_mae: 51 })

function plannedMangled(change: (raw: Record<string, unknown>) => void): unknown {
  const raw = plannedResponse()
  change(raw)
  return raw
}

assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        delete raw.planned
      }),
    ),
  /planned/,
)
assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        raw.planned = false
      }),
    ),
  /planned/,
)
assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        delete (raw.sessions as Record<string, unknown>[])[0].target_set
      }),
    ),
  /sessions\[0\]\.target_set/,
)
assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        raw.limits_text = ['fine', 7]
      }),
    ),
  /limits_text\[1\]/,
)
assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        raw.limits_text = 'as set'
      }),
    ),
  /limits_text/,
)
assert.throws(
  () =>
    parsePlannedDay(
      plannedMangled((raw) => {
        raw.projection_error = 'rough'
      }),
    ),
  /projection_error/,
)

// ── The refused field's control ──────────────────────────────────────────────

assert.equal(controlForField('awake'), 'awake-start')
assert.equal(controlForField('awake[0]'), 'awake-start')
assert.equal(controlForField('awake[1]'), 'awake-end')
assert.equal(controlForField('ambient'), 'ambient')
assert.equal(controlForField('level'), 'level')
assert.equal(controlForField('count_outside'), 'count_outside')
assert.equal(controlForField('sessions'), 'add')
assert.equal(controlForField('sessions[0]'), 's0')
assert.equal(controlForField('sessions[0].start'), 's0-start')
assert.equal(controlForField('sessions[2].minutes'), 's2-len')
assert.equal(controlForField('sessions[1].intensity'), 's1-level')
assert.equal(controlForField('sessions[0].count'), 's0-steps')
assert.equal(controlForField('sessions[0].kind'), 's0-kind')
assert.equal(controlForField('sessions[0].target'), 's0-target')

for (const junk of ['', 'nonsense', 'awake[2]', 'sessions[x]', 'sessions[0].banana']) {
  assert.equal(controlForField(junk), null, junk)
}
for (const junk of [undefined, null, 7, {}, []]) {
  assert.doesNotThrow(() => controlForField(junk as unknown as string))
  assert.equal(controlForField(junk as unknown as string), null)
}

// ── Units for display ────────────────────────────────────────────────────────

assert.equal(unitText('degC'), '°C')
assert.equal(unitText('1'), '')
assert.equal(unitText('bpm'), 'bpm')
assert.equal(unitText(''), '')

console.log('plan-check ok')
