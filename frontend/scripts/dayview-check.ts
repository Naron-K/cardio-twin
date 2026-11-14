/**
 * Checks for the pure half of dayView.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/dayview-check.ts
 *
 * `npm run build` only type-checks src, so this is the executable evidence
 * that gaps stay gaps, a lone reading stays a dot, an all-null bin draws
 * nothing, and a malformed day summary is refused with its field named.
 */
import assert from 'node:assert/strict'
import {
  PLAY_SPEEDS,
  advanceMinute,
  binSums,
  clock,
  groupColourIndex,
  measuredRuns,
  modelledDisplay,
  parseDaySummary,
  sessionAt,
  totalTo,
  valueAt,
  verdictText,
} from '../src/twin/dayView.ts'

function sampleDay(): Record<string, unknown> {
  const nMinutes = 8
  return {
    lamina: 'lamina_wearable',
    subject: 'demo',
    date: '2025-06-01',
    timezone: 'Australia/Melbourne',
    synthetic: true,
    n_minutes: nMinutes,
    pair: {
      label: 'Heart rate',
      unit: 'bpm',
      measured: [60, 61, null, 63, 64, null, null, 67],
      modelled: [59, 60, 61, 62, 63, 64, 65, null],
    },
    rates: [
      {
        attribute: 'AE_rate',
        label: 'Active energy',
        unit: 'kcal',
        values: [0, 1, null, 2, 3, null, 0, 1],
      },
    ],
    events: [
      { indicator: 'is_walk', group: 'walk', label: 'Walk' },
      { indicator: 'is_strength', group: 'strength', label: 'Strength' },
      { indicator: 'is_cardio', group: 'cardio', label: 'Cardio' },
    ],
    gaps: [[2, 4]],
    sessions: [
      {
        start: 0,
        end: 4,
        minutes: 4,
        label: 'Walking',
        group: 'walk',
        group_label: 'Walk',
        mean_measured: 60.5,
        peak_measured: 63,
        mean_modelled: 60,
        n_paired: 4,
        difference: 0.5,
        rate_totals: { AE_rate: 3 },
        verdict: 'as_expected',
      },
    ],
    kpis: [
      {
        key: 'AE_rate',
        label: 'Active energy',
        value: 7,
        unit: 'kcal',
        note: 'sum over 7 minutes',
      },
    ],
    summary: 'One session. Every session was as expected.',
    model: {
      sd: 5,
      sd_source: 'default',
      fitted: false,
      applies_to: null,
    },
  }
}

// ── Measured runs ─────────────────────────────────────────────────────────────

const runs = measuredRuns([60, 61, null, 63, null, null, 66, 67])
assert.equal(runs.length, 3)
assert.deepEqual(runs[0].map((point) => point.m), [0, 1])
assert.deepEqual(runs[0].map((point) => point.v), [60, 61])
assert.deepEqual(runs[1], [{ m: 3, v: 63 }])
assert.deepEqual(runs[2].map((point) => point.m), [6, 7])

// A gap at each edge does not invent a leading or trailing run.
assert.deepEqual(measuredRuns([null, 1, null]), [[{ m: 1, v: 1 }]])
// GUARD: non-finite values are missing, never points.
assert.deepEqual(measuredRuns([Infinity, 1, Number.NaN, 2]), [
  [{ m: 1, v: 1 }],
  [{ m: 3, v: 2 }],
])
assert.deepEqual(measuredRuns([]), [])

// ── Modelled display ─────────────────────────────────────────────────────────

const n = 120
const modelled = Array.from({ length: n }, (_, minute) => minute + 1)
const session = { start: 40, end: 50 }

const display = modelledDisplay(modelled, [session])
assert.equal(display.length, 1)
const points = display[0]
const byMinute = new Map(points.map((point) => [point.m, point.v]))

// Per minute from session start - 30 to session end + 30.
for (let minute = 10; minute < 80; minute += 1) {
  assert.equal(byMinute.get(minute), minute + 1, `per-minute ${minute}`)
}
// Outside, one point per 10-minute bin at the bin's centre.
assert.equal(byMinute.get(5), 5.5)
assert.equal(byMinute.get(85), 85.5)
assert.equal(byMinute.get(95), 95.5)
assert.equal(byMinute.get(105), 105.5)
assert.equal(byMinute.get(115), 115.5)
assert.equal(byMinute.has(6), false)
assert.equal(byMinute.has(80), false)
assert.equal(points.length, 75)

// GUARD: an all-null bin draws no point, and a missing minute splits the run.
const gappy = modelled.slice()
gappy[20] = null
for (let minute = 80; minute < 90; minute += 1) gappy[minute] = null

const gappyDisplay = modelledDisplay(gappy, [session])
const gappyPoints = gappyDisplay.flat()
assert.equal(gappyPoints.some((point) => point.m === 20), false)
assert.equal(gappyPoints.some((point) => point.m === 85), false)
assert.equal(gappyDisplay.length, 3)
assert.equal(gappyPoints.some((point) => point.m === 19), true)
assert.equal(gappyPoints.some((point) => point.m === 21), true)

// A day with no modelled readings at all draws nothing.
assert.deepEqual(modelledDisplay([null, null, null], []), [])

// ── Bin sums ─────────────────────────────────────────────────────────────────

const binValues = [
  1, 2, null, 3, null, null, null, null, null, null,
  null, null, null, null, null, null, null, null, null, 4,
]
assert.deepEqual(binSums(binValues), [6, 4])
assert.deepEqual(binSums([null, null, null]), [null])
assert.deepEqual(binSums([1, 2, 3]), [6])
assert.deepEqual(binSums([]), [])

// ── Clock ────────────────────────────────────────────────────────────────────

assert.equal(clock(0), '00:00')
assert.equal(clock(59), '00:59')
assert.equal(clock(60), '01:00')
assert.equal(clock(1439), '23:59')
assert.equal(clock(1440), '24:00')
assert.equal(clock(-1), '')
assert.equal(clock(Number.NaN), '')
assert.equal(clock(Number.POSITIVE_INFINITY), '')

// ── Verdicts ─────────────────────────────────────────────────────────────────
// The verdict is a number: measured minus modelled, then the same distance in
// model SDs.  The level only picks the colour.

assert.deepEqual(
  verdictText({ verdict: 'as_expected', difference: 1.5, n_paired: 8 }, 5, 'bpm'),
  { tone: 'ok', text: '+1.5 bpm · 0.3 SD' },
)
assert.deepEqual(
  verdictText({ verdict: 'slightly_higher', difference: 7.4, n_paired: 8 }, 10, 'bpm'),
  { tone: 'slight', text: '+7.4 bpm · 0.7 SD' },
)
assert.deepEqual(
  verdictText({ verdict: 'slightly_lower', difference: -7.4, n_paired: 8 }, 10, 'bpm'),
  { tone: 'slight', text: '−7.4 bpm · 0.7 SD' },
)
assert.deepEqual(
  verdictText({ verdict: 'higher', difference: 13.2, n_paired: 8 }, 10, 'bpm'),
  { tone: 'off', text: '+13.2 bpm · 1.3 SD' },
)
assert.deepEqual(
  verdictText({ verdict: 'lower', difference: -13.2, n_paired: 8 }, 10, 'bpm'),
  { tone: 'off', text: '−13.2 bpm · 1.3 SD' },
)
assert.deepEqual(
  verdictText({ verdict: 'too_few', difference: null, n_paired: 2 }, 10, 'bpm'),
  { tone: 'none', text: 'n < 3' },
)

// No unit and no usable SD drop their parts rather than printing junk.
assert.equal(verdictText({ verdict: 'higher', difference: 13.2, n_paired: 8 }, 10, '').text, '+13.2 · 1.3 SD')
assert.equal(verdictText({ verdict: 'higher', difference: 13.2, n_paired: 8 }, 0, 'bpm').text, '+13.2 bpm')
assert.equal(verdictText({ verdict: 'as_expected', difference: 0, n_paired: 8 }, 10, 'bpm').text, '±0.0 bpm · 0.0 SD')

// Without a declared level the same three levels come from the difference,
// the pair count and the model's usual error.
assert.equal(verdictText({ difference: 2, n_paired: 5 }, 10, 'bpm').tone, 'ok')
assert.equal(verdictText({ difference: 6, n_paired: 5 }, 10, 'bpm').tone, 'slight')
assert.equal(verdictText({ difference: 12, n_paired: 5 }, 10, 'bpm').tone, 'off')
assert.equal(verdictText({ difference: 12, n_paired: 2 }, 10, 'bpm').tone, 'none')

// ── Group colours ────────────────────────────────────────────────────────────

const day = parseDaySummary(sampleDay())
assert.equal(groupColourIndex(day, 'walk'), 0)
assert.equal(groupColourIndex(day, 'strength'), 1)
assert.equal(groupColourIndex(day, 'cardio'), 2)
assert.equal(groupColourIndex(day, 'other'), -1)
assert.equal(groupColourIndex(day, 'undeclared'), -1)

// ── Parsing ─────────────────────────────────────────────────────────────────

assert.equal(day.pair.label, 'Heart rate')
assert.equal(day.pair.measured.length, 8)
assert.equal(day.rates[0].values.length, 8)
assert.deepEqual(day.gaps, [[2, 4]])
assert.equal(day.sessions[0].verdict, 'as_expected')
assert.equal(day.model.sd_source, 'default')

// GUARD: a missing field is refused and named.
const missing = sampleDay()
const missingPair = missing.pair as Record<string, unknown>
delete missingPair.label
assert.throws(() => parseDaySummary(missing), /pair\.label/)

// GUARD: a wrong type is refused and named.
const wrongType = sampleDay()
wrongType.n_minutes = '8'
assert.throws(() => parseDaySummary(wrongType), /n_minutes/)

// GUARD: a per-minute array of the wrong length is refused and named.
const wrongLength = sampleDay()
const wrongPair = wrongLength.pair as Record<string, unknown>
;(wrongPair.measured as unknown[]).pop()
assert.throws(() => parseDaySummary(wrongLength), /pair\.measured/)

const wrongRateLength = sampleDay()
const rates = wrongRateLength.rates as Record<string, unknown>[]
;(rates[0].values as unknown[]).pop()
assert.throws(() => parseDaySummary(wrongRateLength), /rates\[0\]\.values/)

// ── Playback ─────────────────────────────────────────────────────────────────

// x60 is one minute of the day a second; the cursor stops at the end.
assert.deepEqual([...PLAY_SPEEDS], [60, 600, 3600])
assert.equal(advanceMinute(0, 60, 1000, 1440), 1)
assert.equal(advanceMinute(100, 600, 500, 1440), 105)
assert.equal(advanceMinute(1439, 3600, 1000, 1440), 1440)
// GUARD: junk input leaves the cursor where it was, inside the day.
assert.equal(advanceMinute(100, 0, 1000, 1440), 100)
assert.equal(advanceMinute(100, 600, -5, 1440), 100)
assert.equal(advanceMinute(100, Number.NaN, 1000, 1440), 100)
assert.equal(advanceMinute(Number.NaN, 60, 1000, 1440), 1)
assert.equal(advanceMinute(-50, 60, 0, 1440), 0)
assert.equal(advanceMinute(5000, 60, 0, 1440), 1440)

// The latest reading within the look-back, never one from the future.
const sparse = [null, 70, null, null, null, null, null, 90, null]
assert.equal(valueAt(sparse, 1), 70)
assert.equal(valueAt(sparse, 4), 70)
assert.equal(valueAt(sparse, 6), 70)
assert.equal(valueAt(sparse, 7), 90)
assert.equal(valueAt(sparse, 6, 2), null)
assert.equal(valueAt(sparse, 0), null)
assert.equal(valueAt(sparse, 99), 90)
assert.equal(valueAt(sparse, Number.NaN), null)

// Running totals count only what has happened by the cursor.
const energy = [1, null, 2.5, 3]
assert.equal(totalTo(energy, 0), 1)
assert.equal(totalTo(energy, 2), 3.5)
assert.equal(totalTo(energy, 50), 6.5)
assert.equal(totalTo([null, null], 1), null)
assert.equal(totalTo(energy, -1), null)

// The enlarged session follows the cursor: inside one, else the last passed.
const playSessions = [
  { start: 100, end: 130 },
  { start: 600, end: 640 },
]
assert.equal(sessionAt(playSessions, 50), -1)
assert.equal(sessionAt(playSessions, 100), 0)
assert.equal(sessionAt(playSessions, 129.5), 0)
assert.equal(sessionAt(playSessions, 300), 0)
assert.equal(sessionAt(playSessions, 610), 1)
assert.equal(sessionAt(playSessions, 1439), 1)
assert.equal(sessionAt([], 300), -1)

console.log('dayview-check ok')
