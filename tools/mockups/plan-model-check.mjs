// Parity check for the Plan a day mockup's in-page model.
// usage: node tools/mockups/plan-model-check.mjs docs/design/mockups/plan-day-demo.html
//
// Extracts the PLAN_DATA object and the <script id="model"> block from the
// built page, runs projectDay() on every reference plan in PLAN_DATA.check,
// and compares heart rate, target, energy and steps with the numbers the
// lamina's forward model (fit_hr_model.simulate_day) produced in Python.
// Also checks that the Level <-> Target link inverts itself.
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const file = process.argv[2]
if (!file) throw new Error('usage: node plan-model-check.mjs <built page.html>')
const html = readFileSync(file, 'utf8')
const dataMatch = html.match(/window\.PLAN_DATA\s*=\s*(\{[\s\S]*?\});\s*<\/script>/)
if (!dataMatch) throw new Error('window.PLAN_DATA = {...}; not found: was the page built from the template?')
const modelMatch = html.match(/<script id="model">([\s\S]*?)<\/script>/)
if (!modelMatch) throw new Error('<script id="model"> block not found')

const ctx = { Math, Number, Array, Object, console }
ctx.globalThis = ctx
vm.createContext(ctx)
vm.runInContext(modelMatch[1], ctx)
for (const name of ['projectDay', 'settleTarget', 'intensityForTarget']) {
  if (typeof ctx[name] !== 'function') throw new Error(`model script must define globalThis.${name}`)
}
const data = JSON.parse(dataMatch[1])

let worst = 0
const fail = []
for (const [i, ref] of data.check.entries()) {
  const out = ctx.projectDay(ref.plan, data)
  for (const key of ['hr', 'target', 'ae', 'steps']) {
    const got = out[key]
    if (!Array.isArray(got) || got.length !== 1440) {
      fail.push(`case ${i}: ${key} is not a 1440-long array`)
      continue
    }
    for (let m = 0; m < 1440; m++) {
      const a = got[m], b = ref[key][m]
      if ((a === null) !== (b === null)) {
        fail.push(`case ${i}: ${key}[${m}] is ${a} in the page and ${b} in Python`)
        break
      }
      if (a !== null) {
        const d = Math.abs(a - b)
        worst = Math.max(worst, d)
        if (d > 1e-3) { fail.push(`case ${i}: ${key}[${m}] page ${a} vs Python ${b}`); break }
      }
    }
  }
}

// Level -> Target -> Level must come back to the same intensity.
const plan = data.default_plan
for (const kind of data.kinds) {
  const hour = 12
  for (const x of [kind.ae.p10, kind.ae.p50, kind.ae.p90]) {
    const t = ctx.settleTarget(kind.id, x, hour, plan, data)
    const back = ctx.intensityForTarget(kind.id, t, hour, plan, data)
    if (Math.abs(back - x) > 1e-3) fail.push(`${kind.id}: intensity ${x} -> target ${t} -> ${back}`)
  }
  const lo = ctx.settleTarget(kind.id, kind.ae.p10, hour, plan, data)
  const hi = ctx.settleTarget(kind.id, kind.ae.p90, hour, plan, data)
  if (!(hi > lo)) fail.push(`${kind.id}: target does not rise with intensity (${lo} -> ${hi})`)
  console.log(`${kind.label}: settles ${lo.toFixed(1)}-${hi.toFixed(1)} bpm over its level range`)
}

if (fail.length) {
  console.error('FAIL\n' + fail.slice(0, 20).join('\n'))
  process.exit(1)
}
console.log(`OK: ${data.check.length} reference plans, largest difference ${worst.toExponential(2)}`)
