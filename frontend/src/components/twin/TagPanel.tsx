/**
 * TagPanel — the wiring between "an outcome drifted" and "something changed".
 *
 * A `<tag>` is the only thing in the model that turns a judgement into an
 * action. It names the outcome it watches, how the deviation is measured, what
 * decides whether to emit at all, which gate kernel shapes the correction, the
 * polarity of that correction, and the composites it delivers to with what
 * weight. Every one of those is a name selected in XML out of a registry the
 * engine offers, so the row reads as a sentence about a decision someone made.
 *
 * The lit rows are the tags the cycle report says fired this tick, and the
 * signed number beside each target is the correction that landed on that
 * composite's attributes. A tag that has fired is doing something to the
 * numbers elsewhere on screen; without this panel that influence is invisible.
 */
import { polarityLabel } from '../../twin/schema'
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  firing: string[]
  /** Signed X'' applied per attribute this cycle, from the cycle report. */
  deltas: Record<string, number>
  /** Outcome id → the model's within-tolerance verdict this cycle. */
  withinByOutcome: Record<string, boolean>
}

export function TagPanel({ index, firing, deltas, withinByOutcome }: Props) {
  if (index.tags.length === 0) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        This lamina declares no tags, so its feedback loop is a no-op.
      </p>
    )
  }

  const firingSet = new Set(firing)

  return (
    <div className="max-h-[150px] overflow-y-auto pr-1 space-y-1">
      {index.tags.map((t) => {
        const lit = firingSet.has(t.id)
        const outcome = index.outcomeById[t.outcome]
        const within = withinByOutcome[t.outcome]

        return (
          <div
            key={t.id}
            className={`grid grid-cols-[136px_104px_minmax(0,1fr)] items-center gap-2 rounded-el px-2 py-1
                        border ${lit ? 'border-warn-strong/50 bg-warn-strong/[0.07]' : 'border-transparent'}`}
          >
            <span className="flex items-center gap-1.5 min-w-0">
              <span
                className={`w-1.5 h-1.5 rounded-full shrink-0 ${lit ? 'bg-warn-strong' : 'bg-ink/15'}`}
                title={lit ? 'fired this cycle' : 'quiet'}
              />
              <span className="font-mono text-[10px] font-bold readout text-ink/75 truncate">
                {t.id}
              </span>
            </span>

            <span
              className={`font-mono text-[9px] readout truncate ${
                within === false ? 'text-crimson-container' : 'text-ink/40'
              }`}
              title={outcome ? `${outcome.name} — ${outcome.description}` : t.outcome}
            >
              {t.outcome}
            </span>

            <span className="font-mono text-[9px] readout text-ink/35 leading-snug">
              {t.deviation_type} → {t.emitter} → {t.gate_kernel} ·{' '}
              <span className={t.polarity < 0 ? 'text-oxy/60' : 'text-warn/70'}>
                {polarityLabel(t.polarity)}
              </span>{' '}
              →{' '}
              {(t.targets ?? []).map((target, i) => {
                const composite = index.schema.composites?.[target.address]
                const landed = (composite?.attribute_ids ?? [])
                  .map((id) => deltas[id] ?? 0)
                  .reduce((sum, d) => sum + Math.abs(d), 0)
                return (
                  <span key={target.address}>
                    {i > 0 && ', '}
                    <span className="text-ink/60">{target.address}</span>
                    <span className="text-ink/20">×{target.weight}</span>
                    {landed > 1e-6 && (
                      <span className="text-warn/70"> Δ{landed.toFixed(3)}</span>
                    )}
                  </span>
                )
              })}
            </span>
          </div>
        )
      })}

      <p className="font-mono text-[9px] readout text-ink/25 leading-snug pt-1">
        Every field is a name the XML selected out of an engine registry — see Machinery for what
        else was on offer. Δ is the size of the correction that landed on that composite's
        attributes this cycle.
      </p>
    </div>
  )
}
