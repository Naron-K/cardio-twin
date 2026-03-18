import { useState } from 'react'
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import type { Schema, SimulationResults } from '../utils/api'

interface CardioRadarChartProps {
  results: SimulationResults
  schema: Schema
}

// Display order and short labels for composite tabs
const COMPOSITE_ORDER = [
  'pressure_state',
  'vessel_state',
  'pump_state',
  'conduction_state',
  'flow_state',
]

const COMPOSITE_LABELS: Record<string, string> = {
  pressure_state: 'Pressure',
  vessel_state: 'Vessel',
  pump_state: 'Pump',
  conduction_state: 'Conduction',
  flow_state: 'Flow',
}

export function CardioRadarChart({ results, schema }: CardioRadarChartProps) {
  const availableIds = COMPOSITE_ORDER.filter((id) => id in results.vectors)
  const [activeId, setActiveId] = useState<string>(() => availableIds[0] ?? '')

  const vectorData = results.vectors[activeId] ?? {}
  const composite = schema.composites[activeId]

  // Convert normalised [0,1] values to [0,100] percentages for display
  const radarData = Object.entries(vectorData).map(([attrId, normalised]) => ({
    subject: schema.attributes[attrId]?.name ?? attrId,
    value: Math.round(normalised * 100),
    fullMark: 100,
  }))

  return (
    <div>
      {/* Composite selector tabs */}
      <div className="flex gap-1.5 mb-3 flex-wrap">
        {availableIds.map((id) => (
          <button
            key={id}
            onClick={() => setActiveId(id)}
            className={`px-3 py-1 text-xs rounded-full border transition-colors ${
              activeId === id
                ? 'bg-cyan-600/80 border-cyan-500 text-white'
                : 'bg-slate-700 border-slate-600 text-slate-400 hover:border-slate-500 hover:text-slate-300'
            }`}
          >
            {COMPOSITE_LABELS[id] ?? id}
          </button>
        ))}
      </div>

      {/* Composite description */}
      {composite && (
        <p className="text-slate-600 text-xs mb-3 leading-relaxed">{composite.description}</p>
      )}

      {/* Radar chart for composites with ≥ 3 attributes */}
      {radarData.length >= 3 ? (
        <ResponsiveContainer width="100%" height={260}>
          <RadarChart data={radarData} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
            <PolarGrid stroke="#334155" />
            <PolarAngleAxis
              dataKey="subject"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
            />
            <PolarRadiusAxis
              angle={90}
              domain={[0, 100]}
              tick={{ fill: '#475569', fontSize: 9 }}
              tickCount={3}
            />
            <Radar
              dataKey="value"
              stroke="#06b6d4"
              fill="#06b6d4"
              fillOpacity={0.2}
              strokeWidth={2}
              dot={{ fill: '#06b6d4', r: 3 }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #334155',
                borderRadius: '6px',
                color: '#e2e8f0',
                fontSize: '12px',
              }}
              formatter={(v) => [`${v}%`, 'Normalised']}
            />
          </RadarChart>
        </ResponsiveContainer>
      ) : (
        /* Fallback: horizontal bar for single-attribute composites (e.g. flow_state) */
        <div className="py-4 space-y-3">
          {radarData.map((item) => (
            <div key={item.subject} className="flex items-center gap-3">
              <span className="text-slate-400 text-sm w-24 truncate">{item.subject}</span>
              <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-cyan-500 rounded-full transition-all duration-300"
                  style={{ width: `${item.value}%` }}
                />
              </div>
              <span className="text-slate-300 text-sm font-mono w-10 text-right">
                {item.value}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
