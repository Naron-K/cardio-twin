import { RadialBarChart, RadialBar } from 'recharts'

interface GaugeChartProps {
  name: string
  value: number
  unit: string
  normalised: number
}

function gaugeColor(n: number): string {
  if (n < 0.15 || n > 0.85) return '#ef4444' // red — extreme
  if (n < 0.25 || n > 0.75) return '#f59e0b' // amber — borderline
  return '#10b981'                            // green — normal
}

export function GaugeChart({ name, value, unit, normalised }: GaugeChartProps) {
  const pct = Math.min(100, Math.max(0, normalised * 100))
  const fill = gaugeColor(normalised)
  // RadialBarChart expects domain [0,100] for background to render full arc
  const data = [{ value: pct, fill }]

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 flex flex-col items-center">
      <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{name}</p>

      {/* Semi-circle gauge: cy at bottom so only upper half is visible */}
      <div className="relative" style={{ width: 160, height: 90 }}>
        <RadialBarChart
          width={160}
          height={90}
          cx={80}
          cy={82}
          innerRadius={52}
          outerRadius={76}
          startAngle={180}
          endAngle={0}
          data={data}
        >
          <RadialBar dataKey="value" background={{ fill: '#334155' }} />
        </RadialBarChart>

        {/* Value overlay centred in the arc opening */}
        <div
          className="absolute inset-x-0 flex flex-col items-center pointer-events-none"
          style={{ top: 52 }}
        >
          <span className="text-slate-100 text-xl font-mono font-bold leading-none">
            {value.toFixed(1)}
          </span>
          <span className="text-slate-500 text-xs mt-0.5">{unit}</span>
        </div>
      </div>

      <p className="text-slate-600 text-xs mt-0.5">{pct.toFixed(0)}% of physiological range</p>
    </div>
  )
}
