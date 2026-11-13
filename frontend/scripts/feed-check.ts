/**
 * Checks for the query-string half of feed.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/feed-check.ts
 *
 * `npm run build` only type-checks src, so this is the executable evidence that
 * a URL can name a replay without handing an unchecked value to the socket.
 */
import assert from 'node:assert/strict'
import { feedFromSearch, feedToSearch } from '../src/feed.ts'

const simulated = { source: 'simulated' } as const
const replay = {
  source: 'replay',
  subject: 's2',
  date: '2025-04-03',
  speed: 600,
} as const
const scenario = { source: 'scenario', preset: 'resting' } as const

// Round trips: what goes into the URL comes back as the same request.
assert.deepEqual(feedFromSearch(''), simulated)
assert.deepEqual(feedFromSearch('?source=simulated'), simulated)
assert.deepEqual(feedFromSearch(feedToSearch(replay, '')), replay)
assert.deepEqual(feedFromSearch(feedToSearch(scenario, '')), scenario)
assert.deepEqual(feedFromSearch(feedToSearch(simulated, '')), simulated)
assert.deepEqual(feedFromSearch('?source=scenario&preset=resting'), scenario)

// Speed is not part of identity, but it does survive the round trip.
assert.deepEqual(
  feedFromSearch('?source=replay&subject=s2&date=2025-04-03&speed=120'),
  { ...replay, speed: 120 },
)
assert.deepEqual(
  feedFromSearch('?source=replay&subject=s2&date=2025-04-03'),
  { ...replay, speed: 60 },
)

// Unrelated parameters survive both writing a replay and going back to live.
const replaySearch = feedToSearch(replay, '?scale=1.25&idle=0')
const replayQuery = new URLSearchParams(replaySearch)
assert.equal(replayQuery.get('scale'), '1.25')
assert.equal(replayQuery.get('idle'), '0')
assert.equal(replayQuery.get('subject'), 's2')
assert.deepEqual(feedFromSearch(replaySearch), replay)

const simulatedSearch = feedToSearch(
  simulated,
  '?scale=1.25&idle=0&source=replay&subject=s2&date=2025-04-03&speed=600&preset=resting',
)
const simulatedQuery = new URLSearchParams(simulatedSearch)
assert.equal(simulatedQuery.get('scale'), '1.25')
assert.equal(simulatedQuery.get('idle'), '0')
assert.equal(simulatedQuery.get('source'), null)
assert.equal(simulatedQuery.get('subject'), null)
assert.equal(simulatedQuery.get('date'), null)
assert.equal(simulatedQuery.get('speed'), null)
assert.equal(simulatedQuery.get('preset'), null)
assert.deepEqual(feedFromSearch(simulatedSearch), simulated)

// A scenario keeps unrelated parameters and drops the replay fields.
const scenarioSearch = feedToSearch(
  scenario,
  '?scale=1.25&source=replay&subject=s2&date=2025-04-03&speed=600',
)
const scenarioQuery = new URLSearchParams(scenarioSearch)
assert.equal(scenarioQuery.get('scale'), '1.25')
assert.equal(scenarioQuery.get('source'), 'scenario')
assert.equal(scenarioQuery.get('preset'), 'resting')
assert.equal(scenarioQuery.get('subject'), null)
assert.equal(scenarioQuery.get('date'), null)
assert.equal(scenarioQuery.get('speed'), null)
assert.deepEqual(feedFromSearch(scenarioSearch), scenario)

// Writing a replay removes a preset left by a scenario link.
const replayFromScenario = new URLSearchParams(
  feedToSearch(replay, '?source=scenario&preset=resting'),
)
assert.equal(replayFromScenario.get('source'), 'replay')
assert.equal(replayFromScenario.get('preset'), null)

// GUARD: a scenario names a preset matching ^[a-z0-9_]{1,32}$.
assert.deepEqual(
  feedFromSearch('?source=scenario&preset=wearable_rest_2'),
  { source: 'scenario', preset: 'wearable_rest_2' },
)
assert.deepEqual(
  feedFromSearch(`?source=scenario&preset=${'p'.repeat(32)}`),
  { source: 'scenario', preset: 'p'.repeat(32) },
)
for (const search of [
  '?source=scenario',
  '?source=scenario&preset=',
  '?source=scenario&preset=Resting',
  '?source=scenario&preset=rest-ing',
  '?source=scenario&preset=rest%20ing',
  '?source=scenario&preset=' + 'p'.repeat(33),
  '?source=scenario&preset=resting.1',
]) {
  assert.deepEqual(feedFromSearch(search), simulated, search)
}

// GUARD: an unknown or missing source is not a replay.
for (const search of [
  '?source=device',
  '?source=',
  '?subject=s2&date=2025-04-03&speed=600',
  '',
]) {
  assert.deepEqual(feedFromSearch(search), simulated, search)
}

// GUARD: missing subject or date falls back to simulated.
for (const search of [
  '?source=replay&date=2025-04-03&speed=600',
  '?source=replay&subject=s2&speed=600',
  '?source=replay&subject=&date=2025-04-03',
  '?source=replay&subject=s2&date=',
]) {
  assert.deepEqual(feedFromSearch(search), simulated, search)
}

// GUARD: a date must be exactly YYYY-MM-DD.
for (const date of ['2025-4-3', '20250403', '2025/04/03', '2025-04-03T10:00', 'yesterday']) {
  assert.deepEqual(
    feedFromSearch(`?source=replay&subject=s2&date=${encodeURIComponent(date)}`),
    simulated,
    date,
  )
}

// GUARD: a subject is lowercase letters, digits and underscore, 1..32 chars.
for (const subject of ['S2', 's-2', 's 2', 's.2', 's'.repeat(33), '']) {
  assert.deepEqual(
    feedFromSearch(
      `?source=replay&subject=${encodeURIComponent(subject)}&date=2025-04-03`,
    ),
    simulated,
    subject,
  )
}
assert.deepEqual(
  feedFromSearch(`?source=replay&subject=${'s'.repeat(32)}&date=2025-04-03`),
  { ...replay, subject: 's'.repeat(32), speed: 60 },
)
assert.deepEqual(
  feedFromSearch('?source=replay&subject=wearable_1&date=2025-04-03'),
  { ...replay, subject: 'wearable_1', speed: 60 },
)

// GUARD: a speed is a positive integer.  A bad speed alone does not discard an
// otherwise valid day; it falls back to the default like an absent one.
for (const speed of ['0', '-60', '60.5', 'abc', '1e3', 'NaN', 'Infinity', '']) {
  assert.deepEqual(
    feedFromSearch(
      `?source=replay&subject=s2&date=2025-04-03&speed=${encodeURIComponent(speed)}`,
    ),
    { ...replay, speed: 60 },
    speed,
  )
}
assert.deepEqual(
  feedFromSearch('?source=replay&subject=s2&date=2025-04-03&speed=120'),
  { ...replay, speed: 120 },
)

console.log('feed-check ok')
