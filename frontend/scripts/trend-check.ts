/**
 * Checks for the pure half of trendWindow.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/trend-check.ts
 *
 * `npm run build` only type-checks src, so this is the executable evidence that
 * gaps, window edges and clock labels still behave the way TrendGrid draws
 * them.
 */
import assert from 'node:assert/strict'
import {
  DAY_SECONDS,
  clockOfSeconds,
  formatClock,
  splitRuns,
  ticksInWindow,
  windowBounds,
  type TrendSample,
} from '../src/twin/trendWindow.ts'

const at = (x: number, value?: number, stale = false): TrendSample => ({
  x,
  value,
  stale,
})

// ── Runs ──────────────────────────────────────────────────────────────────────

// A gap in the middle splits the series into two runs.
const middleGap = splitRuns([at(0, 1), at(1, 2), at(2), at(3, 4), at(4, 5)])
assert.equal(middleGap.length, 2)
assert.deepEqual(middleGap[0].map((s) => s.value), [1, 2])
assert.deepEqual(middleGap[1].map((s) => s.value), [4, 5])

// A stale tick is a gap even though it still carries a value.
const staleGap = splitRuns([at(0, 1), at(1, 2, true), at(2, 3)])
assert.equal(staleGap.length, 2)
assert.deepEqual(staleGap[0].map((s) => s.value), [1])
assert.deepEqual(staleGap[1].map((s) => s.value), [3])

// A single isolated reading is its own run, and gaps at the edges do not
// invent leading or trailing runs.
const isolated = splitRuns([at(0), at(1, 2), at(2), at(3, 4), at(4), at(5, 6), at(6)])
assert.equal(isolated.length, 3)
for (const run of isolated) assert.equal(run.length, 1)
assert.deepEqual(isolated.map((run) => run[0].value), [2, 4, 6])

// GUARD: non-finite values and x positions are gaps, never points.
const malformed = splitRuns([at(NaN, 1), at(1, Infinity), at(2, 3), at(Infinity, 4)])
assert.equal(malformed.length, 1)
assert.deepEqual(malformed[0].map((s) => s.value), [3])

// GUARD: an empty series has no runs (and nothing throws).
assert.deepEqual(splitRuns([]), [])

// ── Windows ───────────────────────────────────────────────────────────────────

// 30 minutes back from the latest position.
assert.deepEqual(windowBounds('30m', 5000), { lo: 3200, hi: 5000 })
// 3 hours back from the latest position.
assert.deepEqual(windowBounds('3h', 5000), { lo: 5000 - 10_800, hi: 5000 })

// Day runs from 0 to the declared duration.
assert.deepEqual(windowBounds('day', 5000, 3600), { lo: 0, hi: 3600 })
// GUARD: a missing, non-finite or non-positive duration falls back to a day.
assert.deepEqual(windowBounds('day', 5000), { lo: 0, hi: DAY_SECONDS })
assert.equal(DAY_SECONDS, 86_400)
assert.deepEqual(windowBounds('day', 5000, NaN), { lo: 0, hi: DAY_SECONDS })
assert.deepEqual(windowBounds('day', 5000, -10), { lo: 0, hi: DAY_SECONDS })
assert.deepEqual(windowBounds('day', 5000, 0), { lo: 0, hi: DAY_SECONDS })

// GUARD: a window that cannot be anchored has no bounds, so nothing is drawn.
assert.equal(windowBounds('30m', undefined), null)
assert.equal(windowBounds('30m', NaN), null)
assert.equal(windowBounds('3h', Infinity), null)

// Filtering includes both edges and drops everything outside them.
const near = [at(9, 1), at(10, 2), at(15, 3), at(20, 4), at(21, 5)]
const inside = ticksInWindow(near, { lo: 10, hi: 20 })
assert.deepEqual(inside.map((s) => s.x), [10, 15, 20])

// A reversed interval still describes the same window.
assert.deepEqual(
  ticksInWindow(near, { lo: 20, hi: 10 }).map((s) => s.x),
  [10, 15, 20],
)

// GUARD: no bounds, or malformed bounds, selects nothing.
assert.deepEqual(ticksInWindow(near, null), [])
assert.deepEqual(ticksInWindow(near, { lo: NaN, hi: 20 }), [])
assert.deepEqual(ticksInWindow(near, { lo: 10, hi: Infinity }), [])

// ── Clock labels ─────────────────────────────────────────────────────────────

// The literal local time is used; the +10:30 offset is never applied.
assert.equal(formatClock('2025-04-03T08:05:00+10:30'), '08:05')
assert.equal(formatClock('2025-04-03T23:59:00Z'), '23:59')
assert.equal(formatClock('2025-04-03T00:00:00-05:00'), '00:00')

// GUARD: malformed or absent timestamps are empty, not "NaN:NaN".
for (const iso of [
  '',
  '2025-04-03',
  'not-a-time',
  '2025-13-03T08:05:00',
  '2025-04-03T24:05:00',
  '2025-04-03T08:60:00',
]) {
  assert.equal(formatClock(iso), '', iso)
}
assert.equal(formatClock(undefined), '')
assert.equal(formatClock(null), '')

// Window edges: seconds since midnight as a clock, 24:00 at the end of a day.
assert.equal(clockOfSeconds(0), '00:00')
assert.equal(clockOfSeconds(37620), '10:27')
assert.equal(clockOfSeconds(86400), '24:00')
assert.equal(clockOfSeconds(-60), '')
assert.equal(clockOfSeconds(Number.NaN), '')
assert.equal(clockOfSeconds(undefined), '')

console.log('trend-check ok')
