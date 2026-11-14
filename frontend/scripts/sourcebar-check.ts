/**
 * Checks for the pure half of sourceBar.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/sourcebar-check.ts
 *
 * `npm run build` only type-checks src, so this is the executable evidence that
 * a replay opens on a day the response actually offered, and that a malformed
 * response or tick reads as nothing rather than throwing.
 */
import assert from 'node:assert/strict'
import {
  datesNewestFirst,
  defaultReplayFeed,
  defaultScenarioFeed,
  parsePresets,
  parseSources,
  scenarioStatusLine,
  statusLine,
} from '../src/twin/sourceBar.ts'

const sources = {
  lamina: 'lamina_wearable',
  modes: ['simulated', 'replay'],
  replay: {
    subjects: {
      demo: ['2025-05-30', '2025-06-01', '2025-05-31'],
      s9: ['2025-01-02'],
    },
    speeds: [60, 120, 600],
    default_speed: 60,
    fitted: { demo: false, s9: true },
  },
  presets: [],
}

// Dates are newest first, with duplicates and non-dates dropped.
assert.deepEqual(datesNewestFirst(['2025-05-30', '2025-06-01', '2025-05-31']), [
  '2025-06-01',
  '2025-05-31',
  '2025-05-30',
])
assert.deepEqual(datesNewestFirst(['2025-06-01', '2025-06-01', 5, null]), ['2025-06-01'])
assert.deepEqual(datesNewestFirst(undefined), [])

// An existing replay is kept when the response still offers that day.
const existing = {
  source: 'replay',
  subject: 's9',
  date: '2025-01-02',
  speed: 600,
} as const
assert.deepEqual(defaultReplayFeed(sources, existing), existing)

// Otherwise the first subject's newest day opens at the default speed.
assert.deepEqual(defaultReplayFeed(sources), {
  source: 'replay',
  subject: 'demo',
  date: '2025-06-01',
  speed: 60,
})

// A day no longer offered is replaced rather than handed to the socket.
assert.deepEqual(
  defaultReplayFeed(sources, { ...existing, date: '2024-01-01' }),
  { source: 'replay', subject: 'demo', date: '2025-06-01', speed: 60 },
)

// No replay block means no replay option at all.
assert.equal(
  defaultReplayFeed({ lamina: 'circulatory', modes: ['simulated'], replay: null, presets: [] }),
  null,
)
assert.equal(
  defaultReplayFeed({ lamina: 'wearable', modes: ['simulated', 'replay'], presets: [] }),
  null,
)
assert.equal(
  defaultReplayFeed({
    lamina: 'wearable',
    modes: ['simulated', 'replay'],
    replay: { subjects: { demo: [] }, speeds: [60], default_speed: 60, fitted: {} },
  }),
  null,
)

// GUARD: malformed shapes are no replay, not an exception.
for (const bad of [null, undefined, 42, 'x', {}, { replay: 5 }, { replay: { subjects: 5 } }]) {
  assert.equal(defaultReplayFeed(bad), null)
}

// GUARD: the parsed response drops wrong types instead of passing them on.
const parsed = parseSources({
  lamina: 'wearable',
  modes: ['simulated', 'replay', 7],
  replay: {
    subjects: { demo: ['2025-06-01', 5], 'Bad Subject': ['2025-06-01'] },
    speeds: [60, -1, 'fast'],
    default_speed: '60',
    fitted: { demo: 'yes', s9: true },
  },
  presets: 'none',
})
assert.deepEqual(parsed.modes, ['simulated', 'replay'])
assert.deepEqual(Object.keys(parsed.replay?.subjects ?? {}), ['demo'])
assert.deepEqual(parsed.replay?.subjects.demo, ['2025-06-01'])
assert.deepEqual(parsed.replay?.speeds, [60])
assert.equal(parsed.replay?.default_speed, 60)
assert.deepEqual(parsed.replay?.fitted, { s9: true })
assert.deepEqual(parsed.presets, [])

// ── Scenario presets ─────────────────────────────────────────────────────────

const scenarioSources = {
  lamina: 'wearable',
  modes: ['simulated', 'scenario'],
  replay: null,
  presets: [
    {
      name: 'resting',
      label: 'Resting',
      description: 'Borrowed from a proxy cohort; the rule and its caveats.',
      subject: 'demo',
      order: 2,
    },
    {
      name: 'walking',
      label: 'Walking',
      description: 'Borrowed from a proxy cohort; the rule and its caveats.',
      subject: 'demo',
      order: 1,
    },
  ],
}

// The first preset by order opens when there is no scenario yet.
assert.deepEqual(defaultScenarioFeed(scenarioSources), {
  source: 'scenario',
  preset: 'walking',
})

// An existing preset is kept while the response still offers it.
const existingScenario = { source: 'scenario', preset: 'resting' } as const
assert.deepEqual(defaultScenarioFeed(scenarioSources, existingScenario), existingScenario)

// A preset no longer offered is replaced rather than handed to the socket.
assert.deepEqual(
  defaultScenarioFeed(scenarioSources, { source: 'scenario', preset: 'running' }),
  { source: 'scenario', preset: 'walking' },
)

// No presets, or no scenario mode, means no scenario option at all.
assert.equal(defaultScenarioFeed({ ...scenarioSources, presets: [] }), null)
assert.equal(defaultScenarioFeed({ ...scenarioSources, modes: ['simulated'] }), null)
assert.equal(defaultScenarioFeed({ ...scenarioSources, modes: ['simulated'], presets: [] }), null)

// GUARD: malformed shapes are no scenario, not an exception.
for (const bad of [null, undefined, 42, 'x', {}, { presets: 5 }]) {
  assert.equal(defaultScenarioFeed(bad), null)
}

// GUARD: incomplete or wrongly typed preset entries are dropped.
const parsedPresets = parsePresets([
  { name: 'resting', label: 'Resting', description: 'd', subject: 'demo', order: 2 },
  { name: 'walking', label: 'Walking', description: 'd', subject: 'demo', order: 1 },
  { name: 'Bad Name', label: 'Bad', description: 'd', subject: 'demo', order: 3 },
  { name: 'Upper', label: 'Upper', description: 'd', subject: 'demo', order: 4 },
  { name: 'missing_label', description: 'd', subject: 'demo', order: 5 },
  { name: 'bad_order', label: 'Bad', description: 'd', subject: 'demo', order: '5' },
  { name: 'resting', label: 'Duplicate', description: 'd', subject: 'demo', order: 6 },
  null,
  7,
])
assert.deepEqual(parsedPresets.map((preset) => preset.name), ['walking', 'resting'])
assert.deepEqual(parsePresets('none'), [])

const parsedScenarioSources = parseSources(scenarioSources)
assert.deepEqual(
  parsedScenarioSources.presets.map((preset) => preset.name),
  ['walking', 'resting'],
)

// ── Status line ──────────────────────────────────────────────────────────────

// The clock is the literal time part; the +10:30 offset is never applied.
assert.equal(
  statusLine({
    kind: 'replay',
    detail: '',
    dataTime: '2025-04-03T08:15:00+10:30',
    positionS: 29700,
    durationS: 86400,
    coefficients: 'fitted',
  }),
  '08:15 · 34% of the day · fitted coefficients',
)

assert.equal(
  statusLine({
    kind: 'replay',
    detail: '',
    dataTime: '2025-04-03T12:00:00Z',
    positionS: 43200,
    durationS: 86400,
    coefficients: 'declared defaults',
    synthetic: true,
  }),
  '12:00 · 50% of the day · declared defaults · synthetic day',
)

assert.equal(statusLine({ kind: 'replay', detail: '', ended: true }), 'Day finished')

// GUARD: missing or malformed tick fields read as nothing, never throw.
assert.equal(statusLine(undefined), '')
assert.equal(statusLine(null), '')
assert.equal(
  statusLine({
    kind: 'replay',
    detail: '',
    dataTime: 5 as unknown as string,
    positionS: 'x' as unknown as number,
    durationS: 0,
    coefficients: 7 as unknown as string,
  }),
  '',
)

// Fitted coefficients name their owner when the tick says whose they are.
assert.equal(
  statusLine({
    kind: 'replay',
    detail: '',
    subject: 's2',
    dataTime: '2025-04-03T08:15:00+10:30',
    positionS: 29700,
    durationS: 86400,
    coefficients: 'fitted',
  }),
  "08:15 · 34% of the day · s2's fitted coefficients",
)
assert.equal(
  scenarioStatusLine({
    kind: 'scenario',
    detail: '',
    preset: 'walk',
    label: 'Walk',
    subject: 's2',
    coefficients: 'fitted',
  }),
  "Scenario · Walk · s2's fitted coefficients",
)

// ── Scenario status line ─────────────────────────────────────────────────────

assert.equal(
  scenarioStatusLine({
    kind: 'scenario',
    detail: '',
    preset: 'resting',
    label: 'Resting',
    coefficients: 'fitted',
  }),
  'Scenario · Resting · fitted coefficients',
)

assert.equal(
  scenarioStatusLine({
    kind: 'scenario',
    detail: '',
    preset: 'walking',
    label: 'Walking',
    coefficients: 'declared defaults',
  }),
  'Scenario · Walking · declared defaults',
)

// GUARD: a non-scenario tick has no scenario line, and malformed fields read
// as nothing rather than being printed.
assert.equal(scenarioStatusLine({ kind: 'replay', detail: '', label: 'Resting' }), '')
assert.equal(scenarioStatusLine(undefined), '')
assert.equal(
  scenarioStatusLine({
    kind: 'scenario',
    detail: '',
    label: 7 as unknown as string,
    coefficients: 9 as unknown as string,
  }),
  'Scenario',
)

console.log('sourcebar-check ok')
