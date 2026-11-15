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
  searchForView,
  subjectLabel,
  viewFromSearch,
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

// Days with no readings are left out; a subject left with none goes too.
const withEmpty = parseSources({
  lamina: 'wearable',
  replay: {
    subjects: { demo: ['2025-06-01'], s2: ['2025-01-02', '2025-04-03', '2025-04-21'], s5: ['2025-03-01'] },
    fitted: {},
    no_readings: { s2: ['2025-01-02', '2025-04-21'], s5: ['2025-03-01'], ghost: ['2025-01-01'] },
  },
})
assert.deepEqual(withEmpty.replay?.subjects, { demo: ['2025-06-01'], s2: ['2025-04-03'] })
// GUARD: a malformed no_readings field leaves nothing out rather than throwing.
for (const bad of [null, 5, 'x', ['2025-06-01'], { demo: 'all' }]) {
  const result = parseSources({ replay: { subjects: { demo: ['2025-06-01'] }, no_readings: bad } })
  assert.deepEqual(result.replay?.subjects, { demo: ['2025-06-01'] })
}
// The picker then never opens an empty day, even when the URL names one.
assert.deepEqual(pickDay(withEmpty, { subject: 's2', date: '2025-01-02' }), {
  subject: 's2',
  date: '2025-04-03',
})

// ── Labels: the screen shows a name, never the folder id ─────────────────────

const labelled = parseSources({
  replay: {
    subjects: { subject_demo: ['2025-04-03'], demo: ['2025-06-01'], s9: ['2025-01-02'] },
    labels: { subject_demo: '  Subject demo ', demo: 'Synthetic sample', s9: '', ghost: 'Nobody' },
  },
})
assert.deepEqual(labelled.replay?.labels, {
  subject_demo: 'Subject demo',
  demo: 'Synthetic sample',
  s9: 's9', // an empty label falls back to the id rather than an empty option
})
// The server's order is kept, so the picker opens on the first subject it lists.
assert.deepEqual(Object.keys(labelled.replay?.subjects ?? {}), ['subject_demo', 'demo', 's9'])
assert.equal(subjectLabel(labelled, 'subject_demo'), 'Subject demo')
assert.equal(subjectLabel(labelled, 'unknown'), 'unknown')
assert.equal(subjectLabel(null, 'demo'), 'demo')
// GUARD: a malformed labels field labels every subject with its id.
for (const bad of [null, 5, 'x', ['Subject demo'], { demo: 7 }, { demo: 'x'.repeat(41) }]) {
  const result = parseSources({ replay: { subjects: { demo: ['2025-06-01'] }, labels: bad } })
  assert.deepEqual(result.replay?.labels, { demo: 'demo' })
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

// Writing the day keeps unrelated parameters, drops the old feed ones, and
// names the recorded view.
assert.equal(
  routeToSearch(
    { subject: 'demo', date: '2025-06-01' },
    '?scale=1.5&source=replay&speed=600&preset=walk&subject=s9&date=2025-01-02',
  ),
  '?scale=1.5&view=recorded&subject=demo&date=2025-06-01',
)
assert.equal(
  routeToSearch({ subject: 'demo', date: '2025-06-01' }, '?view=plan&plan=abc'),
  '?view=recorded&subject=demo&date=2025-06-01',
)
assert.equal(
  routeToSearch({ subject: 'demo', date: '2025-06-01' }, ''),
  '?view=recorded&subject=demo&date=2025-06-01',
)

// ── Which view the URL names ─────────────────────────────────────────────────

assert.equal(viewFromSearch(''), 'plan')
assert.equal(viewFromSearch('?view=plan'), 'plan')
assert.equal(viewFromSearch('?view=recorded'), 'recorded')
// An old link with only a subject and date still opens its recorded day.
assert.equal(viewFromSearch('?subject=subject_demo&date=2025-04-03'), 'recorded')
assert.equal(viewFromSearch('?view=nonsense'), 'plan')
// GUARD: a malformed query reads as the plan view rather than throwing.
assert.equal(viewFromSearch('?%%%&view=%E0%A4%A'), 'plan')

// Switching view keeps scale, drops the other view's keys, and sets the view.
assert.equal(
  searchForView('plan', '?view=recorded&subject=demo&date=2025-06-01&scale=1.5'),
  '?view=plan&scale=1.5',
)
assert.equal(
  searchForView('plan', '?view=recorded&plan=abc&scale=1.5'),
  '?view=plan&plan=abc&scale=1.5',
)
assert.equal(
  searchForView('recorded', '?view=plan&subject=demo&date=2025-06-01&plan=abc&scale=1.5'),
  '?view=recorded&subject=demo&date=2025-06-01&scale=1.5',
)
assert.equal(searchForView('recorded', '?view=plan&plan=abc'), '?view=recorded')
assert.equal(searchForView('plan', ''), '?view=plan')

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
