import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchSchema, computeResults, downloadResultsXML } from './utils/api'
import type { Schema, SimulationResults, AttributeSchema } from './utils/api'
import { Sidebar } from './components/Sidebar'
import { GaugeChart } from './components/GaugeChart'
import { CardioRadarChart } from './components/CardioRadarChart'
import { DataTable } from './components/DataTable'
import { useToast } from './components/Toast'

// Computed attributes shown as gauges (most clinically significant)
const GAUGE_ATTRS = ['MAP', 'CO', 'Q']

type ChartType = 'radar' | 'table'

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSensors(schema: Schema): Record<string, AttributeSchema> {
  const out: Record<string, AttributeSchema> = {}
  for (const [id, attr] of Object.entries(schema.attributes)) {
    if (attr.source === 'SENSOR') out[id] = attr
  }
  return out
}

function getDefaults(schema: Schema): Record<string, number> {
  const out: Record<string, number> = {}
  for (const attr of Object.values(schema.attributes)) {
    if (attr.source === 'SENSOR') {
      out[attr.id] = (attr.physio_min + attr.physio_max) / 2
    }
  }
  return out
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [schema, setSchema] = useState<Schema | null>(null)
  const [values, setValues] = useState<Record<string, number>>({})
  const [results, setResults] = useState<SimulationResults | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [chartType, setChartType] = useState<ChartType>(
    () => (localStorage.getItem('cardiotwin_chart_type') as ChartType) ?? 'radar'
  )
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { showToast } = useToast()

  const handleChartType = useCallback((type: ChartType) => {
    setChartType(type)
    localStorage.setItem('cardiotwin_chart_type', type)
  }, [])

  // Debounced compute – fires 300ms after the last slider change
  const triggerCompute = useCallback((newValues: Record<string, number>) => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await computeResults(newValues)
        setResults(res)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        setError(`Computation failed: ${msg}`)
      } finally {
        setLoading(false)
      }
    }, 300)
  }, [])

  // Load schema on mount, then immediately run first simulation
  useEffect(() => {
    fetchSchema()
      .then((s) => {
        setSchema(s)
        const defaults = getDefaults(s)
        setValues(defaults)
        triggerCompute(defaults)
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e)
        setError(`Failed to load schema: ${msg}. Is the backend running on port 8000?`)
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback(
    (id: string, value: number) => {
      setValues((prev) => {
        const next = { ...prev, [id]: value }
        triggerCompute(next)
        return next
      })
    },
    [triggerCompute]
  )

  const handleReset = useCallback(() => {
    if (!schema) return
    const defaults = getDefaults(schema)
    setValues(defaults)
    triggerCompute(defaults)
  }, [schema, triggerCompute])

  // Called when XML is uploaded or preset is loaded — bypass debounce, set directly
  const handleLoadXML = useCallback(
    (loadedResults: SimulationResults, loadedValues: Record<string, number>) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      setValues(loadedValues)
      setResults(loadedResults)
      setError(null)
    },
    []
  )

  // Called when a saved profile is loaded — repopulate sliders and recompute
  const handleLoadProfile = useCallback(
    (loadedValues: Record<string, number>) => {
      setValues(loadedValues)
      triggerCompute(loadedValues)
    },
    [triggerCompute]
  )

  // Download current results as XML
  const handleDownload = useCallback(async () => {
    if (!results) return
    try {
      const xml = await downloadResultsXML(results, schema?.lamina_name ?? 'CardioTwin')
      const blob = new Blob([xml], { type: 'application/xml' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'cardiotwin_results.xml'
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      showToast(`Download failed: ${msg}`, 'error')
    }
  }, [results, schema, showToast])

  // ── Loading screen (before schema arrives) ──────────────────────────────────
  if (!schema && !error) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <p className="text-slate-400 animate-pulse text-sm">Loading schema…</p>
      </div>
    )
  }

  const sensors = schema ? getSensors(schema) : {}

  return (
    <div className="min-h-screen bg-slate-900 flex">
      {/* Sidebar */}
      {schema && (
        <Sidebar
          sensors={sensors}
          values={values}
          onChange={handleChange}
          onReset={handleReset}
          onLoadXML={handleLoadXML}
          onLoadProfile={handleLoadProfile}
          loading={loading}
        />
      )}

      {/* Main panel */}
      <main className="flex-1 p-6 overflow-y-auto">
        {/* Page header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h2 className="text-slate-100 text-xl font-bold">
              {schema?.lamina_name ?? 'Cardiovascular Simulation'}
            </h2>
            <p className="text-slate-500 text-xs mt-1">
              Real-time physiological digital twin — adjust sliders to recompute
            </p>
          </div>
          {results && (
            <button
              onClick={handleDownload}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 active:bg-slate-500
                         text-slate-300 text-xs rounded-md border border-slate-600 transition-colors shrink-0 ml-4"
            >
              Download XML
            </button>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-5 p-3 bg-red-900/40 border border-red-700 rounded-md text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Gate warnings */}
        {results?.warnings && results.warnings.length > 0 && (
          <div className="mb-5 p-3 bg-yellow-900/30 border border-yellow-700/40 rounded-md">
            <p className="text-yellow-400 text-xs font-semibold uppercase tracking-wide mb-1.5">
              Gate Warnings
            </p>
            {results.warnings.map((w, i) => (
              <p key={i} className="text-yellow-300 text-xs leading-relaxed">
                {w}
              </p>
            ))}
          </div>
        )}

        {/* Computed values grid */}
        {results && (
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            {Object.entries(results.computed).map(([id, attr]) => (
              <ComputedCard key={id} id={id} attr={attr} />
            ))}
          </div>
        )}

        {/* Gauge charts — MAP, CO, Q */}
        {results && (
          <div className="grid grid-cols-3 gap-4 mb-6">
            {GAUGE_ATTRS.map((id) => {
              const attr = results.computed[id]
              if (!attr) return null
              return (
                <GaugeChart
                  key={id}
                  name={attr.name}
                  value={attr.value}
                  unit={attr.unit}
                  normalised={attr.normalised}
                />
              )
            })}
          </div>
        )}

        {/* Composite vector visualisation with chart switcher */}
        {results && schema && (
          <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <p className="text-slate-300 text-sm font-semibold">Composite Vectors</p>
              <div className="flex gap-1">
                {(['radar', 'table'] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => handleChartType(type)}
                    className={`px-3 py-1 text-xs rounded border transition-colors ${
                      chartType === type
                        ? 'bg-slate-600 border-slate-500 text-slate-100'
                        : 'bg-slate-800 border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                    }`}
                  >
                    {type.charAt(0).toUpperCase() + type.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            {chartType === 'radar' && <CardioRadarChart results={results} schema={schema} />}
            {chartType === 'table' && <DataTable results={results} schema={schema} />}
          </div>
        )}

        {/* Initial loading hint */}
        {loading && !results && (
          <p className="text-slate-500 text-sm animate-pulse">Running simulation…</p>
        )}
      </main>
    </div>
  )
}

// ── Computed value card ───────────────────────────────────────────────────────

interface ComputedCardProps {
  id: string
  attr: { value: number; normalised: number; unit: string; name: string }
}

function ComputedCard({ id: _id, attr }: ComputedCardProps) {
  const pct = Math.min(100, Math.max(0, attr.normalised * 100))

  // Colour the bar by normalised position (green centre, amber edges, red extremes)
  const barColor =
    pct < 15 || pct > 85
      ? 'bg-red-500'
      : pct < 25 || pct > 75
        ? 'bg-amber-400'
        : 'bg-cyan-500'

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      <p className="text-slate-500 text-xs uppercase tracking-wide mb-1">{attr.name}</p>
      <p className="text-slate-100 text-2xl font-mono font-bold leading-none">
        {attr.value.toFixed(2)}
        <span className="text-slate-500 text-sm font-normal ml-1.5">{attr.unit}</span>
      </p>

      {/* Normalised range bar */}
      <div className="mt-3 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColor} rounded-full transition-all duration-300`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-slate-600 text-xs mt-1">{pct.toFixed(0)}% of physiological range</p>
    </div>
  )
}
