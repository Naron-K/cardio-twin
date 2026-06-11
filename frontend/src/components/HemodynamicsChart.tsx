/**
 * HemodynamicsChart — CO / SV / MAP time-series.
 *
 * Two Y-axes:
 *   Left  — flow (L/min): CO [0–14]
 *   Right — mixed clinical: MAP (mmHg) [50–130] + SV (mL) [0–160]
 *
 * Q is excluded because with default vessel-radius slider values the
 * Poiseuille formula produces unrealistic R, making Q orders-of-magnitude
 * too large. Q is shown as text in the sidebar instead.
 *
 * isAnimationActive={false} is required for smooth 10Hz streaming.
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

const fmt2 = (v: number) => v.toFixed(2)
const fmt1 = (v: number) => v.toFixed(1)

export function HemodynamicsChart({ ticks }: Props) {
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

        {/* Left axis — cardiac output (L/min) */}
        <YAxis
          yAxisId="flow"
          domain={[0, 14]}
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          unit=" L/min"
          width={58}
        />

        {/* Right axis — MAP mmHg + SV mL share the scale visually;
            MAP sits in [60–110] and SV in [30–150], both fit [0, 160] */}
        <YAxis
          yAxisId="right"
          orientation="right"
          domain={[0, 160]}
          tick={{ fontSize: 9, fill: '#64748b' }}
          stroke="#334155"
          width={52}
        />

        <Tooltip
          contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', fontSize: 11 }}
          labelStyle={{ color: '#94a3b8' }}
          formatter={(v: number, name: string) => {
            if (name === 'CO')  return [`${fmt2(v)} L/min`, name]
            if (name === 'MAP') return [`${fmt1(v)} mmHg`, name]
            if (name === 'SV')  return [`${fmt1(v)} mL`, name]
            return [v, name]
          }}
        />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 4 }} />

        {/* CO normal range [4, 8] L/min */}
        <ReferenceLine yAxisId="flow" y={8} stroke="#22d3ee" strokeDasharray="4 3" strokeOpacity={0.25} />
        <ReferenceLine yAxisId="flow" y={4} stroke="#22d3ee" strokeDasharray="4 3" strokeOpacity={0.25} />
        {/* MAP normal range [70, 100] mmHg — on right axis */}
        <ReferenceLine yAxisId="right" y={100} stroke="#fb923c" strokeDasharray="4 3" strokeOpacity={0.25} />
        <ReferenceLine yAxisId="right" y={70}  stroke="#fb923c" strokeDasharray="4 3" strokeOpacity={0.25} />

        {/* CO — cardiac output (L/min) */}
        <Line
          yAxisId="flow"
          type="monotone"
          dataKey="co"
          name="CO"
          stroke="#22d3ee"
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />

        {/* MAP — mean arterial pressure (mmHg, on right axis) */}
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="map"
          name="MAP"
          stroke="#fb923c"
          dot={false}
          strokeWidth={1.5}
          isAnimationActive={false}
        />

        {/* SV — stroke volume (mL, on right axis; shares [0,160] with MAP) */}
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="sv"
          name="SV"
          stroke="#34d399"
          dot={false}
          strokeWidth={1.5}
          strokeDasharray="5 3"
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
