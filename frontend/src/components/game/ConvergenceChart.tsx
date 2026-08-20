/**
 * ConvergenceChart — how far the twin sits from its clinical targets, and how
 * much of that distance the feedback loop is closing.
 *
 * Replaces the ECG strip that used to occupy this panel.  Every value plotted
 * here is computed by the model: each behavioural outcome ships a target, a
 * tolerance, the value the loop produced (`after`) and the value the same cycle
 * would have produced with the loop disabled (`before`, the shadow pass).  The
 * gap between the two lines is the loop's contribution, live.
 *
 * D is summed across outcomes in units of their own tolerance, so quantities in
 * mmHg, L/min, mL and mm can be added at all:
 *
 *     D = Σ |actual − target| / tolerance
 *
 * D = 0 means every outcome sits exactly on target; D = 1 means the outcomes
 * are one tolerance band off in total, however that is distributed.
 */
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { StreamTick } from '../../hooks/useCardioStream'
import { totalDeviation } from '../../game/outcomes'

interface Props {
  ticks: StreamTick[]
  height?: number
}

// Steps derived on the Oxygenated-Blue and warn hues.  DESIGN.md's own steps
// sit too light for a dark chart surface (OKLCH L 0.81 / 0.77 against a band of
// 0.48–0.67); these are the same hues re-stepped into it, and clear the
// colour-vision separation check at ΔE 19 where 8 is the target.
const WITH_LOOP = '#00a5bb'
const WITHOUT_LOOP = '#c8801f'
const INK_DIM = 'rgba(216,227,251,0.55)'

export function ConvergenceChart({ ticks, height = 150 }: Props) {
  // Ticks that arrived before the first outcome evaluation would otherwise
  // plot as a run of zeros, which reads as "perfectly on target".
  const data = ticks
    .filter((t) => Object.keys(t.beforeAfter).length > 0)
    .map((t) => {
      const withLoop = totalDeviation(t.beforeAfter, 'after')
      const withoutLoop = totalDeviation(t.beforeAfter, 'before')
      return {
        tick: t.tick,
        withLoop,
        withoutLoop,
        // Shaded between the two lines: the distance the loop is closing right
        // now.  A range series rather than a stacked one, so it stays correct
        // when the loop is *losing* ground and the shadow sits lower.
        contribution: [
          Math.min(withLoop, withoutLoop),
          Math.max(withLoop, withoutLoop),
        ] as [number, number],
      }
    })

  const latest = data[data.length - 1]
  const outcomeCount = ticks.length ? Object.keys(ticks[ticks.length - 1].beforeAfter).length : 0
  const closed = latest ? latest.withoutLoop - latest.withLoop : 0

  if (!latest) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        Waiting for the first outcome evaluation…
      </p>
    )
  }

  return (
    <div>
      <div className="flex items-baseline gap-4 mb-2">
        <p className="font-mono text-[11px] readout text-ink/40">
          D now <span className="text-ink text-[13px]">{latest.withLoop.toFixed(2)}</span>
        </p>
        <p className="font-mono text-[11px] readout text-ink/40">
          loop is closing <span className="text-ink text-[13px]">{closed.toFixed(2)}</span> bands
        </p>
        <p className="font-mono text-[11px] readout text-ink/25">
          across {outcomeCount} outcomes · lower is better
        </p>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 4, right: 10, bottom: 0, left: -18 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
          <XAxis
            dataKey="tick"
            tick={{ fontSize: 9, fill: 'rgba(216,227,251,0.35)' }}
            stroke="rgba(255,255,255,0.12)"
            interval="preserveStartEnd"
            minTickGap={44}
            label={{
              value: 'feedback cycle',
              position: 'insideBottomRight',
              offset: -2,
              fill: 'rgba(216,227,251,0.3)',
              fontSize: 9,
            }}
          />
          <YAxis
            tick={{ fontSize: 9, fill: 'rgba(216,227,251,0.35)' }}
            stroke="rgba(255,255,255,0.12)"
            width={46}
            allowDecimals
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#040e1f',
              border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: 8,
              fontSize: 11,
            }}
            labelStyle={{ color: INK_DIM }}
            labelFormatter={(v) => `cycle ${v}`}
            formatter={(value, name) => {
              // The shaded band arrives as [lo, hi]; report the gap it spans.
              if (Array.isArray(value)) {
                const [lo, hi] = value as [number, number]
                return [`${(hi - lo).toFixed(3)} bands`, name]
              }
              return [`${Number(value).toFixed(3)} bands`, name]
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 10, paddingTop: 2 }}
            formatter={(value) => <span style={{ color: INK_DIM }}>{value}</span>}
          />

          {/* Every outcome exactly on target. */}
          <ReferenceLine
            y={0}
            stroke="rgba(255,255,255,0.22)"
            strokeDasharray="5 3"
            label={{
              value: 'on target',
              position: 'insideBottomLeft',
              fill: 'rgba(216,227,251,0.35)',
              fontSize: 9,
            }}
          />

          {/* Drawn first so both lines sit on top of it. */}
          <Area
            type="monotone"
            dataKey="contribution"
            name="What the loop is closing"
            stroke="none"
            fill={WITH_LOOP}
            fillOpacity={0.16}
            isAnimationActive={false}
            activeDot={false}
          />

          <Line
            type="monotone"
            dataKey="withoutLoop"
            name="Without feedback loop"
            stroke={WITHOUT_LOOP}
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="withLoop"
            name="With feedback loop"
            stroke={WITH_LOOP}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <p className="font-mono text-[10px] readout text-ink/30 leading-relaxed mt-1">
        D = Σ |actual − target| ÷ tolerance, over the model's behavioural outcomes.
        Counted in tolerance bands so mmHg, L/min, mL and mm can be summed at all.
        Dashed = the same cycle recomputed with feedback zeroed; the shaded gap is the loop's work.
        Which outcome contributes what — including any the model flags as unreliable — is broken
        out per row under Outcomes.
      </p>
    </div>
  )
}
