/**
 * Checks for the pure half of display.ts (no DOM, no React).
 *
 * Run from frontend/ with:
 *   node --experimental-strip-types scripts/display-check.ts
 *
 * `npm run build` only type-checks src, so this is the executable evidence that
 * the tier and scale arithmetic still matches the rules in the file.
 */
import assert from 'node:assert/strict'
import {
  DESIGN_HEIGHT,
  DESIGN_WIDTH,
  computeProfile,
  scaleFromUrl,
} from '../src/display.ts'

const profile = (w: number, h: number, scale: number | null = null) =>
  computeProfile(w, h, scale)

// Auto scale: 3840x2160 is twice the design in both directions.
assert.deepEqual(profile(3840, 2160), {
  scale: 2,
  tier: 'wide',
  width: 1920,
  height: 1080,
})

// The design resolution stays at 1 and still fits the wide layout.
assert.equal(profile(1920, 1080).scale, 1)
assert.equal(profile(1920, 1080).tier, 'wide')

// Narrower screens keep scale 1 and drop through the tiers.
assert.deepEqual(profile(1024, 690), { scale: 1, tier: 'tablet', width: 1024, height: 690 })
assert.deepEqual(profile(768, 950), { scale: 1, tier: 'tablet', width: 768, height: 950 })
assert.deepEqual(profile(1366, 650), { scale: 1, tier: 'tablet', width: 1366, height: 650 })
assert.deepEqual(profile(390, 844), { scale: 1, tier: 'phone', width: 390, height: 844 })

// A requested scale shrinks the effective layout before the tier is chosen.
const requested = profile(1920, 1080, 1.25)
assert.equal(requested.scale, 1.25)
assert.equal(requested.width, 1536)
assert.equal(requested.tier, 'wide')

// 1280x720 at 1.5 is 853.33x480 effective. The rule in display.ts puts the
// tablet floor at 500 px of height, so this lands in 'phone'. (A 480 px floor
// would make it 'tablet'; the rule is the contract, so follow it.)
assert.equal(profile(1280, 720, 1.5).tier, 'phone')

// Bad measurements must still describe a drawable screen.
for (const [w, h] of [
  [0, 0],
  [-5, -5],
  [NaN, NaN],
  [Infinity, Infinity],
  [0, 1080],
]) {
  const p = profile(w, h, null)
  assert.ok(Number.isFinite(p.scale) && p.scale > 0, `scale for ${w}x${h}`)
  assert.ok(Number.isFinite(p.width) && p.width > 0, `width for ${w}x${h}`)
  assert.ok(Number.isFinite(p.height) && p.height > 0, `height for ${w}x${h}`)
  assert.ok(['phone', 'tablet', 'wide'].includes(p.tier), `tier for ${w}x${h}`)
}

// A fallback profile is exactly the design size.
assert.deepEqual(profile(0, -5), {
  scale: 1,
  tier: 'wide',
  width: DESIGN_WIDTH,
  height: DESIGN_HEIGHT,
})

// URL scale: only a finite number in [0.5, 3] is accepted.
for (const search of [
  '',
  '?scale=',
  '?scale=abc',
  '?scale=0.1',
  '?scale=9',
  '?scale=Infinity',
]) {
  assert.equal(scaleFromUrl(search), null, `scaleFromUrl(${JSON.stringify(search)})`)
}

assert.equal(scaleFromUrl('?scale=1.25&idle=0'), 1.25)
assert.equal(scaleFromUrl('?idle=0&scale=0.5'), 0.5)
assert.equal(scaleFromUrl('?scale=3'), 3)

console.log('display-check ok')
