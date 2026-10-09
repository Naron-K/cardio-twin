/**
 * OutcomeTiles — one tile per behavioural outcome, sized to be read from the
 * back of a room.
 *
 * A tile exists because the lamina declares an outcome, not because this file
 * thinks an attribute is important: the set of tiles, their targets, their
 * tolerances, their scales and their verdicts all arrive on the tick. A lamina
 * that declares no outcomes gets no tiles and a sentence saying why.
 *
 * The bar is OutcomePanel's own, so the dashboard and the inspector cannot
 * draw one outcome two different ways.
 */
import type { StreamTick } from '../../hooks/useCardioStream'
import type { LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'
import { deviationBands, orderedOutcomes, totalDeviation } from '../../twin/outcomes'
import { ToleranceBar } from '../twin/OutcomePanel'

interface Props {
  index: LaminaIndex
  latest: StreamTick | null
}

export function OutcomeTiles({ index, latest }: Props) {
  const outcomes = latest?.beforeAfter ?? {}
  const rows = orderedOutcomes(outcomes)

  if (index.outcomes.length === 0) {
    return (
      <p className="font-mono text-[12px] readout text-ink/40 py-6">
        This lamina declares no behavioural outcomes, so there is nothing to judge it against.
      </p>
    )
  }

  if (rows.length === 0) {
    return (
      <p className="font-mono text-[12px] readout text-ink/40 py-6 animate-pulse">
        Waiting for the first outcome evaluation…
      </p>
    )
  }

  const dWith = totalDeviation(outcomes, 'after')
  const dWithout = totalDeviation(outcomes, 'before')

  return (
    <div className="flex flex-col gap-2.5 min-h-0">
      <div className="flex flex-col gap-2 min-h-0 overflow-y-auto pr-1">
        {rows.map(({ id, o }) => {
          const attr = index.attribute(o.attribute_id)
          const loopHolds = Math.abs(o.x_pp) > 1e-4
          return (
            <div
              key={id}
              className={`rounded-el border px-3.5 py-2.5 ${
                o.within_after
                  ? 'border-white/10 bg-surface-lowest/60'
                  : 'border-crimson-container/50 bg-crimson-container/10'
              }`}
              title={attr?.description}
            >
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[13px] font-bold readout text-ink/80">
                  {o.attribute_id}
                </span>
                <span className="font-mono text-[11px] readout text-ink/35 truncate">
                  {attr?.name}
                </span>
                <span
                  className={`ml-auto shrink-0 font-mono text-[10px] font-bold readout uppercase ${
                    o.within_after ? 'text-oxy' : 'text-crimson'
                  }`}
                >
                  {o.within_after ? 'In tolerance' : 'Outside'}
                </span>
              </div>

              <div className="flex items-baseline gap-1.5 mt-0.5">
                <span
                  className={`font-display text-[28px] font-bold leading-none tabular-nums ${
                    o.within_after ? 'text-ink' : 'text-crimson-container'
                  }`}
                >
                  {fmtValue(o.after)}
                </span>
                <span className="font-mono text-[12px] readout text-ink/40 truncate">{o.unit}</span>
                {loopHolds && (
                  <span
                    className="ml-auto shrink-0 font-mono text-[11px] readout text-warn/80 tabular-nums"
                    title="The part of this value the feedback loop is holding (X″)"
                  >
                    loop {o.x_pp > 0 ? '+' : ''}
                    {fmtValue(o.x_pp)}
                  </span>
                )}
              </div>

              <div className="mt-1.5">
                <ToleranceBar o={o} />
              </div>

              <p className="flex justify-between gap-2 font-mono text-[10px] readout text-ink/40 tabular-nums">
                <span>
                  target {fmtValue(o.target)} ± {fmtValue(o.tolerance)}
                </span>
                <span className="text-ink/30">{deviationBands(o).toFixed(2)} bands off</span>
              </p>
            </div>
          )
        })}
      </div>

      <div className="shrink-0 grid grid-cols-2 gap-2 pt-2 border-t border-white/10">
        <Figure label="Deviation, loop on" value={dWith.toFixed(2)} tone="oxy" />
        <Figure label="Deviation, loop off" value={dWithout.toFixed(2)} tone="warn" />
        <p className="col-span-2 font-mono text-[10px] readout text-ink/30 leading-snug">
          Deviation adds up every outcome&apos;s distance from its target, in its own tolerance
          bands. Loop off is the same cycle recomputed with the feedback correction removed.
          {latest?.diverged && (
            <span className="text-crimson-container"> The circuit breaker has tripped.</span>
          )}
        </p>
      </div>
    </div>
  )
}

function Figure({ label, value, tone }: { label: string; value: string; tone: 'oxy' | 'warn' }) {
  return (
    <div>
      <p className="font-mono text-[10px] readout uppercase text-ink/35">{label}</p>
      <p
        className={`font-display text-[22px] font-bold leading-tight tabular-nums ${
          tone === 'oxy' ? 'text-oxy' : 'text-warn'
        }`}
      >
        {value}
      </p>
    </div>
  )
}
