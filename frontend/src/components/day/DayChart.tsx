import type { DayPoint, DaySummary } from '../../twin/dayView'
import { clock, groupColourIndex, measuredRuns, modelledDisplay } from '../../twin/dayView'

interface Props {
  day: DaySummary
  from?: number
  to?: number
  height?: number
  labels?: boolean
  selected?: number | null
  /**
   * The drawing's own width in SVG units.  Text is set in those units, so a
   * chart shown in a narrow panel needs a narrower drawing or its 13 px labels
   * shrink with it.  Roughly the panel's pixel width.
   */
  width?: number
}

const DEFAULT_WIDTH = 1000
const L = 52
const R = 30
const T = 26
const B = 30

const GROUP_FILL = [
  'fill-day-g0',
  'fill-day-g1',
  'fill-day-g2',
  'fill-day-g3',
] as const

function groupFill(index: number): string {
  return index >= 0 && index < GROUP_FILL.length
    ? GROUP_FILL[index]
    : 'fill-day-other'
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function clipPoints(
  runs: DayPoint[][],
  from: number,
  to: number,
): DayPoint[][] {
  return runs
    .map((run) => run.filter((point) => point.m >= from && point.m <= to))
    .filter((run) => run.length > 0)
}

function niceStep(range: number): number {
  // About eight gridlines, not five: with five, a heart-rate day whose band
  // reaches 30 bpm rounds to a 50 bpm step and the axis starts at 0, wasting
  // a third of the chart on values no one has.
  const rough = range / 8
  const power = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1e-9))))
  for (const candidate of [1, 2, 5, 10]) {
    if (rough <= candidate * power) return candidate * power
  }
  return 10 * power
}

function axisValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

export function DayChart({
  day,
  from,
  to,
  height = 380,
  width = DEFAULT_WIDTH,
  labels = true,
  selected = null,
}: Props) {
  const H = height
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

  const first = Math.floor(lo)
  const last = Math.ceil(hi)
  const hasMeasured = day.pair.measured.some((value) => isFiniteNumber(value))

  if (!hasMeasured) {
    const label = day.pair.label.toLowerCase().replace(/\s+/g, '-')
    return (
      <p className="rounded-el border border-white/10 bg-surface-lowest/60 px-3 py-2 font-body text-[13px] text-ink/70">
        No {label} readings on this day
      </p>
    )
  }

  const values: number[] = []
  const margin = isFiniteNumber(day.model.sd) ? day.model.sd : 0
  for (let minute = first; minute < last; minute += 1) {
    const measured = day.pair.measured[minute]
    if (isFiniteNumber(measured)) values.push(measured)
    const modelled = day.pair.modelled[minute]
    if (isFiniteNumber(modelled)) {
      values.push(modelled + margin, modelled - margin)
    }
  }

  let lowValue = values.length > 0 ? Math.min(...values) : 0
  let highValue = values.length > 0 ? Math.max(...values) : 1
  if (highValue - lowValue < 1e-9) {
    highValue += 1
    lowValue -= 1
  }
  const padding = (highValue - lowValue) * 0.08
  const step = niceStep(highValue - lowValue + padding * 2)
  lowValue = Math.floor((lowValue - padding) / step) * step
  highValue = Math.ceil((highValue + padding) / step) * step
  if (highValue <= lowValue) highValue = lowValue + step

  const x = (minute: number) => L + ((minute - lo) / span) * (W - L - R)
  const y = (value: number) => T + ((highValue - value) / (highValue - lowValue)) * (H - T - B)

  const yTicks: number[] = []
  for (let value = lowValue; value <= highValue + step * 0.001; value += step) {
    yTicks.push(value)
  }

  const xStep = span > 720 ? 120 : span > 180 ? 30 : 10
  const xTicks: number[] = []
  for (let minute = Math.ceil(lo / xStep) * xStep; minute <= hi; minute += xStep) {
    xTicks.push(minute)
  }

  const modelRuns = clipPoints(
    modelledDisplay(day.pair.modelled, day.sessions),
    lo,
    hi,
  )
  const measured = clipPoints(measuredRuns(day.pair.measured), lo, hi)
  const dotRadius = span > 720 ? 2.2 : 3.2
  const plotWidth = W - L - R

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label={`${day.pair.label}, measured and modelled`}
    >
      {day.gaps.map(([start, end], index) => {
        const a = Math.max(start, lo)
        const b = Math.min(end, hi)
        if (b <= a) return null
        const xa = x(a)
        const xb = x(b)
        const width = xb - xa
        return (
          <g key={`gap-${index}`}>
            <rect x={xa} y={T} width={width} height={H - T - B} className="fill-day-gap" />
            {width > plotWidth * 0.15 && (
              <text
                x={(xa + xb) / 2}
                y={(T + H - B) / 2}
                textAnchor="middle"
                fontSize={13}
                className="fill-ink"
                fillOpacity={0.7}
              >
                Watch not worn · no data
              </text>
            )}
          </g>
        )
      })}

      {day.sessions.map((session, index) => {
        const a = Math.max(session.start, lo)
        const b = Math.min(session.end, hi)
        if (b <= a) return null
        const xa = x(a)
        const width = Math.max(2, x(b) - xa)
        const fill = groupFill(groupColourIndex(day, session.group))
        return (
          <g key={`session-${index}`}>
            <rect
              x={xa}
              y={T}
              width={width}
              height={H - T - B}
              className={fill}
              fillOpacity={0.16}
            />
            <rect x={xa} y={T - 6} width={width} height={5} className={fill} />
            {selected === index && (
              <rect
                x={xa}
                y={T}
                width={width}
                height={H - T - B}
                fill="none"
                className="stroke-day-model"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            )}
            {labels && width > 26 && (
              <text x={xa} y={T - 10} fontSize={13} className="fill-ink">
                {session.label}
              </text>
            )}
          </g>
        )
      })}

      {yTicks.map((value, index) => (
        <g key={`y-${index}`}>
          <line
            x1={L}
            x2={W - R}
            y1={y(value)}
            y2={y(value)}
            className="stroke-ink"
            strokeOpacity={0.15}
            vectorEffect="non-scaling-stroke"
          />
          <text
            x={L - 8}
            y={y(value) + 4}
            textAnchor="end"
            fontSize={13}
            className="fill-ink"
            fillOpacity={0.7}
          >
            {axisValue(value)}
          </text>
        </g>
      ))}

      {xTicks.map((minute, index) => (
        <text
          key={`x-${index}`}
          x={x(minute)}
          y={H - 8}
          textAnchor="middle"
          fontSize={13}
          className="fill-ink"
          fillOpacity={0.7}
        >
          {clock(minute)}
        </text>
      ))}

      <text x={L} y={14} fontSize={13} className="fill-ink" fillOpacity={0.8}>
        {day.pair.unit}
      </text>

      {modelRuns.map((run, index) => {
        if (run.length < 2) return null
        const upper = run.map(
          (point) => `${x(point.m)},${y(point.v + margin)}`,
        )
        const lower = run
          .slice()
          .reverse()
          .map((point) => `${x(point.m)},${y(point.v - margin)}`)
        return (
          <g key={`model-${index}`}>
            <polygon points={upper.concat(lower).join(' ')} className="fill-day-band" />
            <polyline
              points={run.map((point) => `${x(point.m)},${y(point.v)}`).join(' ')}
              fill="none"
              className="stroke-day-model"
              strokeWidth={2}
              strokeDasharray="7 5"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </g>
        )
      })}

      {measured.map((run, index) => (
        <g key={`measured-${index}`}>
          {run.length > 1 && (
            <polyline
              points={run.map((point) => `${x(point.m)},${y(point.v)}`).join(' ')}
              fill="none"
              className="stroke-day-measured"
              strokeWidth={2.5}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )}
          {run.map((point) => (
            <circle
              key={`dot-${index}-${point.m}`}
              cx={x(point.m)}
              cy={y(point.v)}
              r={dotRadius}
              className="fill-day-measured"
            />
          ))}
        </g>
      ))}
    </svg>
  )
}
