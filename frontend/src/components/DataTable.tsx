import type { Schema, SimulationResults } from '../utils/api'

interface DataTableProps {
  results: SimulationResults
  schema: Schema
}

const COMPOSITE_LABELS: Record<string, string> = {
  pressure_state: 'Pressure State',
  vessel_state: 'Vessel State',
  pump_state: 'Pump State',
  conduction_state: 'Conduction State',
  flow_state: 'Flow State',
}

function barColor(pct: number): string {
  if (pct < 15 || pct > 85) return 'bg-red-500'
  if (pct < 25 || pct > 75) return 'bg-amber-400'
  return 'bg-cyan-500'
}

export function DataTable({ results, schema }: DataTableProps) {
  return (
    <div className="space-y-6">
      {Object.entries(results.vectors).map(([compositeId, vector]) => (
        <div key={compositeId}>
          <p className="text-slate-400 text-xs font-semibold uppercase tracking-wide mb-2">
            {COMPOSITE_LABELS[compositeId] ?? compositeId}
          </p>
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="text-left text-slate-500 pb-1.5 font-normal pr-4">Attribute</th>
                <th className="text-right text-slate-500 pb-1.5 font-normal pr-4">Value</th>
                <th className="text-right text-slate-500 pb-1.5 font-normal pr-4">Unit</th>
                <th className="text-slate-500 pb-1.5 font-normal" style={{ width: 120 }}>
                  Normalised
                </th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(vector).map(([attrId, normalised]) => {
                const attrSchema = schema.attributes[attrId]
                const resultAttr = results.computed[attrId] ?? results.sensors[attrId]
                const pct = Math.min(100, Math.max(0, normalised * 100))

                return (
                  <tr key={attrId} className="border-b border-slate-800/60">
                    <td className="py-2 text-slate-300 pr-4">
                      {attrSchema?.name ?? attrId}
                    </td>
                    <td className="py-2 text-right text-slate-100 font-mono pr-4">
                      {resultAttr ? resultAttr.value.toFixed(3) : '—'}
                    </td>
                    <td className="py-2 text-right text-slate-500 pr-4">
                      {resultAttr?.unit ?? ''}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full ${barColor(pct)} rounded-full transition-all duration-300`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-slate-500 font-mono w-8 text-right shrink-0">
                          {pct.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
