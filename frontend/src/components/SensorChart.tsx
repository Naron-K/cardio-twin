/**
 * SensorChart — scrolling HR / SBP / DBP time-series.
 *
 * HR on the right Y-axis (bpm), SBP/DBP on the left (mmHg) so the
 * two ranges don't compress each other.  isAnimationActive={false}
 * is critical: Recharts animation causes jank on rapid updates.
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

const fmt1 = (v: number) => v.toFixed(1)

export function SensorChart({ ticks }: Props) {
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
        {/* Left axis — blood pressure */}
        <YAxis
          yAxisId="bp"
          domain={[50, 200]}
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          unit=" mmHg"
          width={60}
        />
        {/* Right axis — heart rate */}
        <YAxis
          yAxisId="hr"
          orientation="right"
          domain={[30, 220]}
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          unit=" bpm"
          width={56}
        />
        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
          labelStyle={{ color: '#94a3b8' }}
          formatter={(v: number, name: string) => [fmt1(v), name]}
        />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />

        {/* Normal range reference bands — SBP 90–140, DBP 60–90 */}
        <ReferenceLine yAxisId="bp" y={140} stroke="#3b82f6" strokeDasharray="4 3" strokeOpacity={0.3} />
        <ReferenceLine yAxisId="bp" y={90}  stroke="#8b5cf6" strokeDasharray="4 3" strokeOpacity={0.3} />

        <Line
          yAxisId="bp"
          type="monotone"
          dataKey="sbp"
          name="SBP"
          stroke="#3b82f6"
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
        <Line
          yAxisId="bp"
          type="monotone"
          dataKey="dbp"
          name="DBP"
          stroke="#8b5cf6"
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />
        <Line
          yAxisId="hr"
          type="monotone"
          dataKey="hr"
          name="HR"
          stroke="#ef4444"
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
