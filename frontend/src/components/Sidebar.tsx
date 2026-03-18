import type { AttributeSchema, SimulationResults } from '../utils/api'
import { XMLUpload } from './XMLUpload'
import { ProfileManager } from './ProfileManager'

interface SidebarProps {
  sensors: Record<string, AttributeSchema>
  values: Record<string, number>
  onChange: (id: string, value: number) => void
  onReset: () => void
  onLoadXML: (results: SimulationResults, values: Record<string, number>) => void
  onLoadProfile: (values: Record<string, number>) => void
  loading: boolean
}

export function Sidebar({
  sensors,
  values,
  onChange,
  onReset,
  onLoadXML,
  onLoadProfile,
  loading,
}: SidebarProps) {
  return (
    <aside className="w-[300px] min-h-screen bg-slate-800 border-r border-slate-700 flex flex-col shrink-0">
      {/* Header */}
      <div className="p-5 border-b border-slate-700">
        <h1 className="text-cyan-400 font-bold text-lg tracking-wide">CardioTwin</h1>
        <p className="text-slate-500 text-xs mt-0.5">Cardiovascular Digital Twin</p>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* XML Upload + Presets */}
        <XMLUpload onLoad={onLoadXML} disabled={loading} />

        <div className="border-t border-slate-700/60" />

        {/* Sensor sliders */}
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
              Sensor Inputs
            </span>
            {loading && (
              <span className="text-xs text-cyan-400 animate-pulse">Computing…</span>
            )}
          </div>

          {Object.values(sensors).map((attr) => {
            const value = values[attr.id] ?? (attr.physio_min + attr.physio_max) / 2
            return (
              <SliderRow
                key={attr.id}
                attr={attr}
                value={value}
                disabled={loading}
                onChange={(v) => onChange(attr.id, v)}
              />
            )
          })}
        </div>

        <div className="border-t border-slate-700/60" />

        {/* Profile manager */}
        <ProfileManager values={values} onLoad={onLoadProfile} disabled={loading} />
      </div>

      {/* Reset button */}
      <div className="p-4 border-t border-slate-700">
        <button
          onClick={onReset}
          disabled={loading}
          className="w-full py-2 px-4 bg-slate-700 hover:bg-slate-600 active:bg-slate-500
                     text-slate-300 text-sm rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Reset to Defaults
        </button>
      </div>
    </aside>
  )
}

// ── Individual slider row ──────────────────────────────────────────────────────

interface SliderRowProps {
  attr: AttributeSchema
  value: number
  disabled: boolean
  onChange: (value: number) => void
}

function SliderRow({ attr, value, disabled, onChange }: SliderRowProps) {
  const step = (attr.physio_max - attr.physio_min) / 200

  return (
    <div className="space-y-1.5">
      {/* Label + live value */}
      <div className="flex justify-between items-baseline">
        <label
          className="text-slate-300 text-sm font-medium truncate max-w-[150px]"
          title={attr.description}
        >
          {attr.name}
        </label>
        <span className="text-cyan-400 text-sm font-mono shrink-0 ml-2">
          {value.toFixed(1)}{' '}
          <span className="text-slate-500 text-xs">{attr.unit}</span>
        </span>
      </div>

      {/* Range input */}
      <input
        type="range"
        min={attr.physio_min}
        max={attr.physio_max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer
                   bg-slate-600 accent-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed"
      />

      {/* Min / max labels */}
      <div className="flex justify-between text-slate-600 text-xs">
        <span>{attr.physio_min}</span>
        <span>{attr.physio_max}</span>
      </div>
    </div>
  )
}
