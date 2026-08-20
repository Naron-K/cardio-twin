/**
 * outcomes — the one place the 2D view is allowed to learn what "good" means.
 *
 * Every band, every threshold and every verdict here is read out of the
 * behavioural outcomes the model ships on each tick: `target`, `tolerance`,
 * `physio_min`, `physio_max` and `within_after` all arrive in the `before_after`
 * payload, computed by the lamina from its XML.  Nothing in this file invents a
 * number.
 *
 * This exists because the game view used to hold its own table of "safe" ranges
 * (a 4.2–6.2 L/min band for cardiac output, a 60–100 bpm band for a quantity the
 * model has no outcome for at all).  That is a second clinical opinion living in
 * the UI, which is exactly what the project decided against: targets and
 * tolerances come from the model.  A quantity the model declares no outcome for
 * gets no band — it is reported as unjudged rather than judged by us.
 */
import type { BeforeAfter, StreamTick } from '../hooks/useCardioStream'

export type Outcomes = Record<string, BeforeAfter>

/** Tolerance band as an interval: the model's target ± its own tolerance. */
export function bandOf(o: BeforeAfter): [number, number] {
  return [o.target - o.tolerance, o.target + o.tolerance]
}

/**
 * One outcome's distance from target counted in its own tolerance, which is the
 * only way mmHg, L/min, mL and mm can be added together at all.
 */
export function deviationBands(o: BeforeAfter, field: 'before' | 'after' = 'after'): number {
  if (!o.tolerance) return 0
  return Math.abs(o[field] - o.target) / o.tolerance
}

/** D = Σ |actual − target| / tolerance, over every outcome the model evaluated. */
export function totalDeviation(outcomes: Outcomes, field: 'before' | 'after' = 'after'): number {
  let d = 0
  for (const o of Object.values(outcomes)) d += deviationBands(o, field)
  return d
}

/**
 * The model's own verdict on whether anything is off.  Replaces the old
 * `alert` flag, which compared MAP and HR against ranges typed into the UI.
 */
export function anyOutOfBand(outcomes: Outcomes): boolean {
  const list = Object.values(outcomes)
  return list.length > 0 && list.some((o) => !o.within_after)
}

/** Find the outcome that judges a given attribute, if the model declares one. */
export function outcomeForAttribute(
  outcomes: Outcomes,
  attributeId: string
): BeforeAfter | undefined {
  return Object.values(outcomes).find((o) => o.attribute_id === attributeId)
}

/**
 * Outcomes in a stable display order.  Sorted by outcome id rather than a
 * hand-kept list, so an outcome added to the XML shows up here on its own
 * instead of being silently dropped by a UI that never heard of it.
 */
export function orderedOutcomes(outcomes: Outcomes): { id: string; o: BeforeAfter }[] {
  return Object.entries(outcomes)
    .map(([id, o]) => ({ id, o }))
    .sort((a, b) => a.o.attribute_id.localeCompare(b.o.attribute_id))
}

/** Latest tick that actually carries an outcome evaluation, or null. */
export function latestEvaluated(ticks: StreamTick[]): StreamTick | null {
  for (let i = ticks.length - 1; i >= 0; i--) {
    if (Object.keys(ticks[i].beforeAfter).length > 0) return ticks[i]
  }
  return null
}
