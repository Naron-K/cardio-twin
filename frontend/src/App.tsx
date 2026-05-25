import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchSchema,
  computeResults,
  downloadResultsXML,
  feedbackStep,
  feedbackRun,
} from './utils/api'
import type {
  Schema,
  SimulationResults,
  AttributeSchema,
  KernelState,
} from './utils/api'
import { Sidebar } from './components/Sidebar'
import { GaugeChart } from './components/GaugeChart'
import { CardioRadarChart } from './components/CardioRadarChart'
import { DataTable } from './components/DataTable'
import { FeedbackPanel } from './components/FeedbackPanel'
import type { NormPoint } from './components/FeedbackPanel'
import { useToast } from './components/Toast'

// Computed attributes shown as gauges (most clinically significant)
const GAUGE_ATTRS = ['MAP', 'CO', 'Q']

type ChartType = 'radar' | 'table'
type StoppedReason = 'settled' | 'max_cycles' | 'diverged' | null

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

  // ── Feedback loop state (Phase F) ─────────────────────────────────────────
  // kernelState is opaque server-side payload, round-tripped verbatim.
  // cycle is the counter the backend echoes back; normHistory feeds the chart.
  const [kernelState, setKernelState] = useState<KernelState>({})
  const [cycle, setCycle] = useState<number>(0)
  const [normHistory, setNormHistory] = useState<NormPoint[]>([])
  const [diverged, setDiverged] = useState<boolean>(false)
  const [stoppedReason, setStoppedReason] = useState<StoppedReason>(null)
  const [feedbackBusy, setFeedbackBusy] = useState<boolean>(false)

  // Refs let the debounced step callback read the latest state without
  // re-creating itself on every cycle update (which would cancel pending
  // debounce timers and break slider responsiveness).
  const kernelStateRef = useRef<KernelState>({})
  const cycleRef = useRef<number>(0)
  useEffect(() => {
    kernelStateRef.current = kernelState
  }, [kernelState])
  useEffect(() => {
    cycleRef.current = cycle
  }, [cycle])

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { showToast } = useToast()

  const handleChartType = useCallback((type: ChartType) => {
    setChartType(type)
    localStorage.setItem('cardiotwin_chart_type', type)
  }, [])

  // Clean /api/compute call that also drops any in-flight feedback state.
  // Used by initial load, slider changes (debounced), Reset, and preset/XML
  // loading.  The demo story is: sliders = scenario knobs, feedback panel =
  // "now watch the body correct" — so any sensor edit invalidates the
  // accumulated X''.
  const computeAndResetFeedback = useCallback(
    async (newValues: Record<string, number>) => {
      setLoading(true)
      setError(null)
      try {
        const res = await computeResults(newValues)
        setResults(res)
        setKernelState({})
        setCycle(0)
        setNormHistory([])
        setDiverged(false)
        setStoppedReason(null)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        setError(`Computation failed: ${msg}`)
      } finally {
        setLoading(false)
      }
    },
    []
  )

  // Debounced slider-change handler — fires 300ms after the last edit.
  // Slider change = new scenario → fresh compute, fresh feedback.
  const triggerCompute = useCallback(
    (newValues: Record<string, number>) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        computeAndResetFeedback(newValues)
      }, 300)
    },
    [computeAndResetFeedback]
  )

  // Load schema on mount, then immediately run first simulation
  useEffect(() => {
    fetchSchema()
      .then((s) => {
        setSchema(s)
        const defaults = getDefaults(s)
        setValues(defaults)
        computeAndResetFeedback(defaults)
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

  // Slider Reset — restore defaults AND drop feedback state (new scenario).
  const handleReset = useCallback(() => {
    if (!schema) return
    const defaults = getDefaults(schema)
    setValues(defaults)
    computeAndResetFeedback(defaults)
  }, [schema, computeAndResetFeedback])

  // Feedback Reset — keep current sensor values, just drop feedback state.
  const handleFeedbackReset = useCallback(() => {
    computeAndResetFeedback(values)
  }, [values, computeAndResetFeedback])

  // Manual single-cycle step — same payload as the debounced version,
  // without the slider-change context.
  const handleFeedbackStep = useCallback(async () => {
    if (feedbackBusy) return
    setFeedbackBusy(true)
    setError(null)
    try {
      const res = await feedbackStep({
        sensorData: values,
        kernelState: kernelStateRef.current,
        cycle: cycleRef.current,
      })
      setResults(res.state)
      setKernelState(res.kernel_state)
      setCycle(res.cycle)
      setDiverged(res.diverged)
      setStoppedReason(res.diverged ? 'diverged' : null)
      setNormHistory((prev) => [
        ...prev,
        { cycle: res.cycle, norm: res.cycle_report.feedback_norm },
      ])
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`Feedback step failed: ${msg}`)
    } finally {
      setFeedbackBusy(false)
    }
  }, [values, feedbackBusy])

  // Batched N-cycle run — appends every trace point to the norm chart.
  const handleFeedbackRun = useCallback(
    async (cycles: number, settledThreshold: number) => {
      if (feedbackBusy) return
      setFeedbackBusy(true)
      setError(null)
      try {
        const res = await feedbackRun({
          sensorData: values,
          kernelState: kernelStateRef.current,
          cycle: cycleRef.current,
          cycles,
          settledThreshold,
          settledWindow: 5,
        })
        setResults(res.state)
        setKernelState(res.kernel_state)
        setCycle(res.cycle)
        setDiverged(res.diverged)
        setStoppedReason(res.stopped_reason)
        setNormHistory((prev) => [
          ...prev,
          ...res.trace.map((t) => ({ cycle: t.cycle, norm: t.feedback_norm })),
        ])
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        setError(`Feedback run failed: ${msg}`)
      } finally {
        setFeedbackBusy(false)
      }
    },
    [values, feedbackBusy]
  )

  // Called when XML is uploaded or preset is loaded — bypass debounce, set directly
  const handleLoadXML = useCallback(
    (loadedResults: SimulationResults, loadedValues: Record<string, number>) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      setValues(loadedValues)
      setResults(loadedResults)
      setError(null)
      // Loading a new scenario invalidates feedback history.
      setKernelState({})
      setCycle(0)
      setNormHistory([])
      setDiverged(false)
      setStoppedReason(null)
    },
    []
  )

  // Called when a saved profile is loaded — repopulate sliders and reset feedback.
  const handleLoadProfile = useCallback(
    (loadedValues: Record<string, number>) => {
      setValues(loadedValues)
      computeAndResetFeedback(loadedValues)
    },
    [computeAndResetFeedback]
  )

  // Shared download helper — used by both the header "Download XML" button
  // and the FeedbackPanel "Save settled state" button.  The `filename`
  // argument lets the settled-save flow tag the file with cycle count so a
  // researcher can tell snapshots apart.
  const triggerXMLDownload = useCallback(
    async (filename: string, scenarioName: string) => {
      if (!results) return
      try {
        const xml = await downloadResultsXML(results, scenarioName)
        const blob = new Blob([xml], { type: 'application/xml' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()
        URL.revokeObjectURL(url)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        showToast(`Download failed: ${msg}`, 'error')
      }
    },
    [results, showToast]
  )

  const handleDownload = useCallback(
    () =>
      triggerXMLDownload(
        'cardiotwin_results.xml',
        schema?.lamina_name ?? 'CardioTwin'
      ),
    [triggerXMLDownload, schema]
  )

  const handleSaveSettled = useCallback(() => {
    const filename = `cardiotwin_settled_cycle${cycle}.xml`
    const label = `${schema?.lamina_name ?? 'CardioTwin'} — settled @ cycle ${cycle}`
    triggerXMLDownload(filename, label)
    showToast(`Saved settled snapshot (cycle ${cycle})`, 'success')
  }, [cycle, schema, triggerXMLDownload, showToast])

  // ── Loading screen (before schema arrives) ──────────────────────────────────
  if (!schema && !error) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <p className="text-slate-400 animate-pulse text-sm">Loading schema…</p>
      </div>
    )
  }

  const sensors = schema ? getSensors(schema) : {}
  const currentNorm =
    normHistory.length > 0
      ? normHistory[normHistory.length - 1].norm
      : results?.feedback_norm ?? 0

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

        {/* Feedback loop panel (Phase F MVP) */}
        {results && (
          <FeedbackPanel
            cycle={cycle}
            feedbackNorm={currentNorm}
            diverged={diverged}
            busy={feedbackBusy || loading}
            history={normHistory}
            stoppedReason={stoppedReason}
            onStep={handleFeedbackStep}
            onRun={handleFeedbackRun}
            onReset={handleFeedbackReset}
            onSaveSettled={handleSaveSettled}
          />
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
