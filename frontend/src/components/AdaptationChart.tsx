/**
 * AdaptationChart — feedback_norm + per-attribute X″ corrections.
 *
 * This is the "arrhythmia demo arc": inject arrhythmia → HR spikes →
 * CO leaves tolerance → CO_DEVIATION fires → co_feedback / sv_feedback
 * go negative (corrective) and feedback_norm rises.  As the drift
 * fades the corrections decay back to 0 — homeostasis re-established.
 *
 * The reference line at y=0 makes the correction direction clear.
 */
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { StreamTick } from '../hooks/useCardioStream'

interface Props {
  ticks: StreamTick[]
}

const fmt4 = (v: number) => v.toFixed(4)

export function AdaptationChart({ ticks }: Props) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={ticks} margin={{ top: 16, right: 8, bottom: 0, left: -8 }}>
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
          formatter={(v: number, name: string) => [fmt4(v), name]}
        />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />

        {/* Zero baseline — corrections below this are corrective (negative) */}
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="5 3" />

        {/* feedback_norm — overall loop intensity */}
        <Line
          type="monotone"
          dataKey="feedback_norm"
          name="‖X″‖ norm"
          stroke="#f59e0b"
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
        {/* CO correction — goes negative when CO is above target */}
        <Line
          type="monotone"
          dataKey="co_feedback"
          name="CO X″"
          stroke="#10b981"
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
        {/* SV correction — the pump attribute most directly corrected */}
        <Line
          type="monotone"
          dataKey="sv_feedback"
          name="SV X″"
          stroke="#6366f1"
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
