/**
 * TrendGrid — every attribute the model computes, over a chosen stretch of time.
 *
 * One small chart per computed attribute, in the order the chain runs them.
 * The vertical scale is the attribute's declared physiological range, so a
 * line's height says where in that range the value sits, the same convention
 * the outcome bars use.  Where the model declares an outcome on the attribute,
 * its tolerance band is shaded and its target dashed; where it declares none,
 * there is no band, because a band drawn here would be a judgement the model
 * did not make.
 *
 * A replay is plotted against the feed's own position in the day, and the
 * window toggle chooses the last 30 minutes, the last 3 hours, or the whole
 * day.  A live feed keeps the short ring buffer and indexes it as before.
 * A missing, non-finite or stale reading is a gap: each unbroken run is drawn
 * on its own (a lone reading becomes a dot), so the line never joins two
 * points the model did not produce.  The headline is the latest non-stale
 * value; a stale latest tick shows a dash instead.
 *
 * Plain SVG rather than a chart library: nine live charts at 10 Hz is a lot
 * of reconciliation for axes nobody needs at this size.
 */
import { useState } from 'react'
import type { StreamTick } from '../../hooks/useCardioStream'
import type { AttributeSchema, LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'
import type { TrendSample, WindowBounds, WindowKind } from '../../twin/trendWindow'
import { clockOfSeconds, splitRuns, ticksInWindow, windowBounds } from '../../twin/trendWindow'

interface Props {
  index: LaminaIndex
  ticks: StreamTick[]
}

const W = 300
const H = 80

const WINDOWS: { kind: WindowKind; label: string }[] = [
  { kind: '30m', label: '30 min' },
  { kind: '3h', label: '3 h' },
  { kind: 'day', label: 'Day' },
]

export function TrendGrid({ index, ticks }: Props) {
  const [windowKind, setWindowKind] = useState<WindowKind>('day')
  const latest = ticks.length > 0 ? ticks[ticks.length - 1] : null
  const latestX = latest?.source.positionS
  const bounds =
    typeof latestX === 'number' && Number.isFinite(latestX)
      ? windowBounds(windowKind, latestX, latest?.source.durationS)
      : null
  const replay = bounds !== null

  if (index.computed.length === 0) {
    return (
      <p className="font-mono text-[12px] readout text-ink/40">
        This lamina computes nothing, so there is nothing to plot.
      </p>
    )
  }

  const cols = index.computed.length > 6 ? 3 : 2

  return (
    <div className="flex flex-col gap-2 w-full h-full min-h-0">
      {replay && (
        <div className="flex justify-end shrink-0">
          <div className="flex rounded-full border border-white/10 bg-surface-lowest/80 p-0.5">
            {WINDOWS.map((w) => (
              <button
                key={w.kind}
                type="button"
                onClick={() => setWindowKind(w.kind)}
                className={`min-h-[44px] rounded-full px-3 font-mono text-[11px] readout uppercase transition-colors ${
                  windowKind === w.kind ? 'bg-white/10 text-ink' : 'text-ink/40 hover:text-ink/70'
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>
      )}
      <div
        className="grid gap-3 w-full flex-1 min-h-0"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
      >
        {index.computed.map((attr) => (
          <Trend
            key={attr.id}
            attr={attr}
            index={index}
            ticks={ticks}
            latest={latest}
            bounds={bounds}
          />
        ))}
      </div>
    </div>
  )
}

function Trend({
  attr,
  index,
  ticks,
  latest,
  bounds,
}: {
  attr: AttributeSchema
  index: LaminaIndex
  ticks: StreamTick[]
  latest: StreamTick | null
  bounds: WindowBounds | null
}) {
  const staleReason = latest?.staleComputed[attr.id]
  const latestIsStale = Boolean(staleReason)

  // The headline is the freshest value the model actually produced.  A stale
  // last tick is not a reading, so it becomes a dash rather than last cycle's
  // number wearing this cycle's timestamp.
  let current: number | undefined
  if (!latestIsStale) {
    for (let i = ticks.length - 1; i >= 0; i -= 1) {
      const v = ticks[i].computed[attr.id]
      if (Number.isFinite(v) && !ticks[i].staleComputed[attr.id]) {
        current = v
        break
      }
    }
  }

  const samples: TrendSample[] = ticks.map((t, i) => ({
    x: bounds ? t.source.positionS ?? Number.NaN : i,
    value: t.computed[attr.id],
    stale: Boolean(t.staleComputed[attr.id]),
    dataTime: t.source.dataTime,
  }))
  const visible = bounds ? ticksInWindow(samples, bounds) : samples

  // Scale only to data actually drawn in this window; a stale or missing value
  // must not stretch the axis.
  const real = visible.filter(
    (s) => !s.stale && typeof s.value === 'number' && Number.isFinite(s.value),
  )
  let lo = attr.physio_min
  let hi = attr.physio_max
  for (const s of real) {
    const v = s.value as number
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  const span = Math.max(1e-9, hi - lo)
  const y = (v: number) => H - ((v - lo) / span) * H
  const outOfRange =
    current !== undefined && (current < attr.physio_min || current > attr.physio_max)

  const outcome = index.outcomesOfAttribute[attr.id]?.[0]
  const live = outcome ? latest?.beforeAfter[outcome.id] : undefined
  const liveTarget = live && Number.isFinite(live.target) ? live.target : undefined
  const liveTolerance = live && Number.isFinite(live.tolerance) ? live.tolerance : undefined
  const target = liveTarget ?? outcome?.target_value
  const tolerance = liveTolerance ?? outcome?.tolerance

  const xLo = bounds ? bounds.lo : 0
  const xHi = bounds ? bounds.hi : Math.max(1, ticks.length - 1)
  const xSpan = Math.max(1e-9, xHi - xLo)
  const x = (v: number) => ((v - xLo) / xSpan) * W

  const runs = splitRuns(visible).map((run) =>
    run.map((s) => ({ x: x(s.x), y: y(s.value as number) })),
  )
  const lineClass = latestIsStale ? 'text-ink/30' : 'text-oxy-container'

  // The labels sit at the chart's edges, so they name the window's edges, not
  // the first and last reading: mid-replay a Day chart ends at 24:00 while
  // the line stops at the minute being played.
  const firstClock = bounds ? clockOfSeconds(bounds.lo) : null
  const lastClock = bounds ? clockOfSeconds(bounds.hi) : null

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
        {outcome && target !== undefined && tolerance !== undefined && (
          <>
            <rect
              x={0}
              width={W}
              y={y(target + tolerance)}
              height={Math.max(0.5, y(target - tolerance) - y(target + tolerance))}
              className="fill-current text-oxy-container"
              fillOpacity={0.12}
            />
            <line
              x1={0}
              x2={W}
              y1={y(target)}
              y2={y(target)}
              stroke="currentColor"
              className="text-oxy"
              strokeOpacity={0.5}
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}
        {runs.map((run, i) =>
          run.length === 1 ? (
            <circle
              key={`dot-${i}`}
              cx={run[0].x}
              cy={run[0].y}
              r={1.5}
              fill="currentColor"
              className={lineClass}
              vectorEffect="non-scaling-stroke"
            />
          ) : (
            <polyline
              key={`run-${i}`}
              points={run.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}
              fill="none"
              stroke="currentColor"
              className={lineClass}
              strokeWidth={1.75}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ),
        )}
      </svg>

      <div className="flex justify-between font-mono text-[9px] readout text-ink/25 tabular-nums">
        <span>{bounds ? firstClock : fmtValue(lo)}</span>
        <span>
          {outcome
            ? `target ${fmtValue(target)} ± ${fmtValue(tolerance)}`
            : 'no outcome declared'}
        </span>
        <span>{bounds ? lastClock : fmtValue(hi)}</span>
      </div>
    </div>
  )
}
