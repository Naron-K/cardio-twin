/**
 * AdaptationChart — per-attribute X″ corrections held by the loop.
 *
 * The recovery arc: a disturbance (slider drag or preset) pushes CO out
 * of tolerance → CO_DEVIATION fires → co_feedback / sv_feedback go
 * negative (corrective).  The shaded area under each line is the amount
 * of correction the loop is currently holding; as the outcome returns to
 * band the leaky integrator drains it back to 0 — homeostasis.
 *
 * Norm line intentionally omitted (kept to the two X″ signals for clarity).
 * The reference line at y=0 marks "recovered".
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Formatter, NameType, ValueType } from 'recharts/types/component/DefaultTooltipContent'
import type { StreamTick } from '../hooks/useCardioStream'

interface Props {
  ticks: StreamTick[]
}

const fmt4 = (v: number) => v.toFixed(4)

export function AdaptationChart({ ticks }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={ticks} margin={{ top: 16, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
        <XAxis
          dataKey="tick"
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          width={64}
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
          labelStyle={{ color: '#94a3b8' }}
          formatter={((value, name) => [fmt4(Number(value)), name]) as Formatter<ValueType, NameType>}
        />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />

        {/* Zero baseline — "recovered"; corrections sit below it (negative) */}
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="5 3" />

        {/* SV correction — the pump attribute most directly corrected;
            shaded area = correction currently held on SV */}
        <Area
          type="monotone"
          dataKey="sv_feedback"
          name="SV X″"
          stroke="#6366f1"
          strokeWidth={1.8}
          fill="#6366f1"
          fillOpacity={0.16}
          dot={false}
          isAnimationActive={false}
        />
        {/* CO correction — goes negative when CO is above target */}
        <Area
          type="monotone"
          dataKey="co_feedback"
          name="CO X″"
          stroke="#10b981"
          strokeWidth={1.8}
          fill="#10b981"
          fillOpacity={0.16}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}
