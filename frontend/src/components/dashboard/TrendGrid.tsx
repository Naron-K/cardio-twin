/**
 * TrendGrid — every attribute the model computes, over the last half-minute.
 *
 * One small chart per computed attribute, in the order the chain runs them.
 * The vertical scale is the attribute's declared physiological range, so a
 * line's height says where in that range the value sits, the same convention
 * the outcome bars use. Where the model declares an outcome on the attribute,
 * its tolerance band is shaded and its target dashed; where it declares none,
 * there is no band, because a band drawn here would be a judgement the model
 * did not make.
 *
 * Plain SVG rather than a chart library: nine live charts at 10 Hz is a lot
 * of reconciliation for axes nobody needs at this size.
 */
import type { StreamTick } from '../../hooks/useCardioStream'
import type { AttributeSchema, LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  ticks: StreamTick[]
}

const W = 300
const H = 80

export function TrendGrid({ index, ticks }: Props) {
  if (index.computed.length === 0) {
    return (
      <p className="font-mono text-[12px] readout text-ink/40">
        This lamina computes nothing, so there is nothing to plot.
      </p>
    )
  }

  const cols = index.computed.length > 6 ? 3 : 2
  const latest = ticks.length > 0 ? ticks[ticks.length - 1] : null

  return (
    <div
      className="grid gap-3 w-full h-full min-h-0"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {index.computed.map((attr) => (
        <Trend
          key={attr.id}
          attr={attr}
          index={index}
          series={ticks.map((t) => t.computed[attr.id])}
          staleReason={latest?.staleComputed[attr.id]}
        />
      ))}
    </div>
  )
}

function Trend({
  attr,
  index,
  series,
  staleReason,
}: {
  attr: AttributeSchema
  index: LaminaIndex
  series: (number | undefined)[]
  staleReason?: string
}) {
  const values = series.filter((v): v is number => v !== undefined && Number.isFinite(v))
  const current = values.length > 0 ? values[values.length - 1] : undefined

  // The declared range, widened only if the value has actually left it, so a
  // line is never clipped off the top of its own chart.
  let lo = attr.physio_min
  let hi = attr.physio_max
  for (const v of values) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  const span = Math.max(1e-9, hi - lo)
  const y = (v: number) => H - ((v - lo) / span) * H
  const outOfRange = current !== undefined && (current < attr.physio_min || current > attr.physio_max)

  const outcome = index.outcomesOfAttribute[attr.id]?.[0]
  const points = series
    .map((v, i) =>
      v === undefined || !Number.isFinite(v)
        ? null
        : `${((i / Math.max(1, series.length - 1)) * W).toFixed(1)},${y(v).toFixed(1)}`
    )
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className="rounded-el border border-white/10 bg-surface-lowest/60 px-3 pt-2 pb-1.5 min-h-0 flex flex-col"
      title={staleReason ? `${attr.id}: ${staleReason}` : attr.description}
    >
      <div className="flex items-baseline gap-1.5">
        <span className="font-mono text-[12px] font-bold readout text-ink/80">{attr.id}</span>
        <span className="font-mono text-[10px] readout text-ink/30 truncate">{attr.name}</span>
        <span
          className={`ml-auto shrink-0 font-mono text-[14px] font-bold tabular-nums ${
            staleReason
              ? 'text-ink/30 line-through decoration-warn/50'
              : outOfRange
                ? 'text-crimson-container'
                : 'text-ink'
          }`}
        >
          {fmtValue(current)}
        </span>
        <span className="font-mono text-[10px] readout text-ink/35 shrink-0">{attr.unit}</span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="mt-1 w-full flex-1 min-h-[44px]"
        role="img"
        aria-label={`${attr.id} over time`}
      >
        {outcome && (
          <>
            <rect
              x={0}
              width={W}
              y={y(outcome.target_value + outcome.tolerance)}
              height={Math.max(0.5, y(outcome.target_value - outcome.tolerance) - y(outcome.target_value + outcome.tolerance))}
              className="fill-current text-oxy-container"
              fillOpacity={0.12}
            />
            <line
              x1={0}
              x2={W}
              y1={y(outcome.target_value)}
              y2={y(outcome.target_value)}
              stroke="currentColor"
              className="text-oxy"
              strokeOpacity={0.5}
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}
        {points && (
          <polyline
            points={points}
            fill="none"
            stroke="currentColor"
            className={staleReason ? 'text-ink/30' : 'text-oxy-container'}
            strokeWidth={1.75}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      <div className="flex justify-between font-mono text-[9px] readout text-ink/25 tabular-nums">
        <span>{fmtValue(lo)}</span>
        <span>
          {outcome
            ? `target ${fmtValue(outcome.target_value)} ± ${fmtValue(outcome.tolerance)}`
            : 'no outcome declared'}
        </span>
        <span>{fmtValue(hi)}</span>
      </div>
    </div>
  )
}
