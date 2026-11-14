/**
 * Checks for twin/sources.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/sources-check.ts
 *
 * The executable evidence that the page opens on a day the server actually
 * offers, that a URL or response of the wrong shape reads as nothing rather
 * than throwing, and that the day arrows stop at the ends.
 */
import assert from 'node:assert/strict'
import {
  datesNewestFirst,
  neighbourDays,
  parseSources,
  pickDay,
  routeFromSearch,
  routeToSearch,
} from '../src/twin/sources.ts'

const sources = parseSources({
  lamina: 'lamina_wearable',
  modes: ['simulated', 'replay'],
  replay: {
    subjects: {
      demo: ['2025-05-30', '2025-06-01', '2025-05-31'],
      s9: ['2025-01-02'],
    },
    speeds: [60],
    default_speed: 60,
    fitted: { demo: false, s9: true },
  },
  presets: [],
})

// ── Dates ────────────────────────────────────────────────────────────────────

assert.deepEqual(datesNewestFirst(['2025-05-30', '2025-06-01', '2025-05-31']), [
  '2025-06-01',
  '2025-05-31',
  '2025-05-30',
])
assert.deepEqual(datesNewestFirst(['2025-06-01', '2025-06-01', 5, null]), ['2025-06-01'])
assert.deepEqual(datesNewestFirst(undefined), [])

// ── Parsing ──────────────────────────────────────────────────────────────────

assert.equal(sources.lamina, 'lamina_wearable')
assert.deepEqual(sources.replay?.subjects.demo, ['2025-06-01', '2025-05-31', '2025-05-30'])

// GUARD: wrong types are dropped, not passed on.
const parsed = parseSources({
  lamina: 7,
  replay: {
    subjects: { demo: ['2025-06-01', 5], 'Bad Subject': ['2025-06-01'], empty: [] },
    fitted: { demo: 'yes', s9: true },
  },
})
assert.equal(parsed.lamina, '')
assert.deepEqual(Object.keys(parsed.replay?.subjects ?? {}), ['demo'])
assert.deepEqual(parsed.replay?.fitted, { s9: true })
for (const bad of [null, undefined, 42, 'x', [], { replay: 5 }]) {
  const result = parseSources(bad)
  assert.equal(result.replay === null || Object.keys(result.replay.subjects).length === 0, true)
}

// ── The day the URL names ────────────────────────────────────────────────────

assert.deepEqual(routeFromSearch('?subject=s9&date=2025-01-02'), {
  subject: 's9',
  date: '2025-01-02',
})
// An older dashboard link still names its day.
assert.deepEqual(
  routeFromSearch('?source=replay&subject=demo&date=2025-06-01&speed=60'),
  { subject: 'demo', date: '2025-06-01' },
)
// GUARD: anything that is not a subject id and a date is no route.
for (const bad of [
  '',
  '?subject=demo',
  '?date=2025-06-01',
  '?subject=Demo&date=2025-06-01',
  '?subject=demo&date=1/6/2025',
  '?subject=../etc&date=2025-06-01',
  '?subject=demo&date=2025-06-01x',
]) {
  assert.equal(routeFromSearch(bad), null, bad)
}

// Writing the day keeps unrelated parameters and drops the old feed ones.
assert.equal(
  routeToSearch(
    { subject: 'demo', date: '2025-06-01' },
    '?scale=1.5&source=replay&speed=600&preset=walk&subject=s9&date=2025-01-02',
  ),
  '?scale=1.5&subject=demo&date=2025-06-01',
)
assert.equal(routeToSearch({ subject: 'demo', date: '2025-06-01' }, ''), '?subject=demo&date=2025-06-01')

// ── Which day opens ──────────────────────────────────────────────────────────

// The named day when it is offered.
assert.deepEqual(pickDay(sources, { subject: 's9', date: '2025-01-02' }), {
  subject: 's9',
  date: '2025-01-02',
})
// A day no longer offered falls back to that subject's newest.
assert.deepEqual(pickDay(sources, { subject: 'demo', date: '2024-01-01' }), {
  subject: 'demo',
  date: '2025-06-01',
})
// An unknown subject, or no route, opens the first subject's newest day.
assert.deepEqual(pickDay(sources, { subject: 'nobody', date: '2025-06-01' }), {
  subject: 'demo',
  date: '2025-06-01',
})
assert.deepEqual(pickDay(sources, null), { subject: 'demo', date: '2025-06-01' })
// Nothing offered is nothing to open.
assert.equal(pickDay(null, null), null)
assert.equal(pickDay(parseSources({ lamina: 'x', replay: null }), null), null)
assert.equal(pickDay(parseSources({ replay: { subjects: {} } }), null), null)

// ── Day arrows ───────────────────────────────────────────────────────────────

const days = ['2025-06-01', '2025-05-31', '2025-05-30']
assert.deepEqual(neighbourDays(days, '2025-05-31'), { older: '2025-05-30', newer: '2025-06-01' })
assert.deepEqual(neighbourDays(days, '2025-06-01'), { older: '2025-05-31', newer: null })
assert.deepEqual(neighbourDays(days, '2025-05-30'), { older: null, newer: '2025-05-31' })
assert.deepEqual(neighbourDays(days, '2020-01-01'), { older: null, newer: null })
assert.deepEqual(neighbourDays([], '2025-06-01'), { older: null, newer: null })

console.log('sources-check ok')
