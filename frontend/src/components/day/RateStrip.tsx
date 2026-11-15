import type { DaySummary } from '../../twin/dayView'
import { binSums, clock, timeStep } from '../../twin/dayView'

interface Props {
  day: DaySummary
  from?: number
  to?: number
  /** Drawing width in SVG units; match DayChart's so the axes line up. */
  width?: number
  /** While the day plays: bars after this minute are not drawn yet. */
  until?: number | null
}

const DEFAULT_WIDTH = 1000
const L = 52
const R = 30
const TOP = 18
const LANE = 60
const BOTTOM = 24
const BIN = 10

const RATE_FILL = [
  'fill-day-g1',
  'fill-day-bar',
  'fill-day-g2',
  'fill-day-g3',
  'fill-day-other',
] as const

function rateFill(index: number): string {
  return RATE_FILL[index % RATE_FILL.length]
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function RateStrip({ day, from, to, width = DEFAULT_WIDTH, until = null }: Props) {
  const W = Number.isFinite(width) && width >= 300 ? width : DEFAULT_WIDTH
  let lo = isFiniteNumber(from) ? from : 0
  let hi = isFiniteNumber(to) ? to : day.n_minutes
  lo = Math.max(0, Math.min(day.n_minutes, lo))
  hi = Math.max(0, Math.min(day.n_minutes, hi))
  if (lo > hi) {
    const swap = lo
    lo = hi
    hi = swap
  }
  if (hi <= lo) {
    lo = 0
    hi = day.n_minutes
  }
  const span = Math.max(1, hi - lo)
  const cursor = isFiniteNumber(until) ? Math.max(0, until) : null
  const drawTo = cursor === null ? hi : Math.min(hi, cursor)

  if (day.rates.length === 0) {
    return (
      <p className="rounded-el border border-white/10 bg-surface-lowest/60 px-3 py-2 font-body text-[13px] text-ink/70">
        No activity rates on this day
      </p>
    )
  }

  const H = TOP + LANE * day.rates.length + BOTTOM
  const x = (minute: number) => L + ((minute - lo) / span) * (W - L - R)
  const xStep = timeStep(span, W - L - R)
  const xTicks: number[] = []
  for (let minute = Math.ceil(lo / xStep) * xStep; minute <= hi; minute += xStep) {
    xTicks.push(minute)
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label={`${day.rates.map((rate) => rate.label).join(' and ')}, per ten minutes`}
    >
      {day.gaps.map(([start, end], index) => {
        const a = Math.max(start, lo)
        const b = Math.min(end, drawTo)
        if (b <= a) return null
        return (
          <rect
            key={`gap-${index}`}
            x={x(a)}
            y={0}
            width={x(b) - x(a)}
            height={H - BOTTOM}
            className="fill-day-gap"
          />
        )
      })}

      {day.rates.map((rate, index) => {
        const laneTop = TOP + index * LANE
        const laneBottom = laneTop + LANE
        const up = index % 2 === 0
        const baseline = up ? laneBottom - 4 : laneTop + 4
        const maxHeight = LANE - 24
        const labelY = up ? laneTop + 12 : laneBottom - 6

        const sums = binSums(rate.values, BIN)
        const bars: { shown: boolean; x: number; width: number; value: number }[] = []
        for (let bin = 0; bin < sums.length; bin += 1) {
          const value = sums[bin]
          if (!isFiniteNumber(value) || value <= 0) continue
          const start = bin * BIN
          const end = start + BIN
          const a = Math.max(start, lo)
          const b = Math.min(end, hi)
          if (b <= a) continue
          bars.push({
            // Scaled with the whole day's bars, so heights hold still while
            // the cursor reveals them.
            shown: start <= drawTo,
            x: x(a),
            width: Math.max(1, x(b) - x(a) - 1.5),
            value,
          })
        }

        const peak =
          bars.length > 0
            ? Math.max(...bars.map((bar) => bar.value))
            : null
        const maxValue = Math.max(peak ?? 0, 1)
        const peakText =
          peak === null
            ? null
            : `${Math.round(peak).toLocaleString('en-GB')} ${rate.unit}`.trim()
        const label =
          peakText === null
            ? `${rate.label} (no data)`
            : `${rate.label} (peak ${peakText} / 10 min)`

        return (
          <g key={`rate-${index}`}>
            {bars.map((bar, barIndex) => {
              if (!bar.shown) return null
              const barHeight = (bar.value / maxValue) * maxHeight
              return (
                <rect
                  key={`bar-${index}-${barIndex}`}
                  x={bar.x}
                  y={up ? baseline - barHeight : baseline}
                  width={bar.width}
                  height={barHeight}
                  className={rateFill(index)}
                />
              )
            })}
            <text
              x={L + 4}
              y={labelY}
              fontSize={13}
              className="fill-ink"
              fillOpacity={0.8}
            >
              {label}
            </text>
          </g>
        )
      })}

      {xTicks.map((minute, index) => (
        <text
          key={`x-${index}`}
          x={x(minute)}
          y={H - 6}
          textAnchor="middle"
          fontSize={13}
          className="fill-ink"
          fillOpacity={0.7}
        >
          {clock(minute)}
        </text>
      ))}

      {cursor !== null && cursor >= lo && cursor <= hi && (
        <line
          x1={x(cursor)}
          x2={x(cursor)}
          y1={0}
          y2={H - BOTTOM}
          className="stroke-ink"
          strokeOpacity={0.85}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  )
}
