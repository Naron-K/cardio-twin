/**
 * StreamingDashboard — live monitoring view (Phase 4 rework).
 *
 * Single-screen dashboard that connects to /ws/feedback and keeps 10
 * sensor sliders in sync with the backend stream via set_sensor messages.
 *
 * Slider → debounce 150ms → sendControl({type:'set_sensor', id, value})
 * Preset → fetch /presets/<name>.xml → uploadXML → send all set_sensor msgs
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useCardioStream } from '../hooks/useCardioStream'
import type { StreamStatus } from '../hooks/useCardioStream'
import { SensorChart } from './SensorChart'
import { AdaptationChart } from './AdaptationChart'
import { HemodynamicsChart } from './HemodynamicsChart'
import { fetchSchema, uploadXML } from '../utils/api'
import type { Schema, AttributeSchema } from '../utils/api'

// ── Constants ─────────────────────────────────────────────────────────────────

const PRESETS = [
  { id: 'normal',        label: 'Normal'       },
  { id: 'hypertension',  label: 'Hypertension' },
  { id: 'heart_failure', label: 'Heart Failure' },
]

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusPip({ status }: { status: StreamStatus }) {
  const dot =
    status === 'open'       ? 'bg-emerald-400' :
    status === 'connecting' ? 'bg-amber-400 animate-pulse' :
                              'bg-red-500'
  const label =
    status === 'open'       ? 'LIVE' :
    status === 'connecting' ? 'RECONNECTING…' :
                              'OFFLINE'
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${dot}`} />
      <span className="text-xs font-mono text-slate-400">{label}</span>
    </span>
  )
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-center gap-1 text-xs text-slate-400">
      <span className="text-slate-500">{label}</span>
      <span className="font-mono text-slate-200">{value}</span>
    </span>
  )
}

interface SliderRowProps {
  attr: AttributeSchema
  value: number
  onChange: (value: number) => void
}

function SliderRow({ attr, value, onChange }: SliderRowProps) {
  const step = (attr.physio_max - attr.physio_min) / 200
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-baseline">
        <label
          className="text-slate-300 text-xs font-medium truncate max-w-[130px]"
          title={attr.description}
        >
          {attr.name}
        </label>
        <span className="text-cyan-400 text-xs font-mono shrink-0 ml-2">
          {value.toFixed(1)}{' '}
          <span className="text-slate-500">{attr.unit}</span>
        </span>
      </div>
      <input
        type="range"
        min={attr.physio_min}
        max={attr.physio_max}
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full h-1.5 rounded-full appearance-none cursor-pointer bg-slate-600 accent-cyan-400"
      />
      <div className="flex justify-between text-slate-600 text-[10px]">
        <span>{attr.physio_min}</span>
        <span>{attr.physio_max}</span>
      </div>
    </div>
  )
}

function Placeholder() {
  return (
    <div className="h-[220px] flex items-center justify-center text-slate-600 text-xs animate-pulse">
      waiting for data…
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  onBack: () => void
}

export function StreamingDashboard({ onBack }: Props) {
  const [schema,     setSchema]     = useState<Schema | null>(null)
  const [values,     setValues]     = useState<Record<string, number>>({})
  const [paused,     setPaused]     = useState(false)
  const [magnitude,  setMagnitude]  = useState(30)
  const [presetBusy, setPresetBusy] = useState(false)
  const [presetErr,  setPresetErr]  = useState<string | null>(null)

  // Per-sensor debounce timers so rapid slider drags don't spam the WS
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const { ticks, status, sendControl } = useCardioStream({ tickMs: 100, bufferSize: 120 })
  const latest = ticks.length > 0 ? ticks[ticks.length - 1] : null

  // Load schema on mount; initialise slider values to physio midpoints.
  // We do NOT send initial set_sensor messages here because the WS may not
  // be open yet. The backend starts with its own SimulatedCardioSource
  // defaults; sliders sync on first user interaction or preset load.
  useEffect(() => {
    fetchSchema().then(s => {
      setSchema(s)
      const defaults: Record<string, number> = {}
      for (const [id, attr] of Object.entries(s.attributes)) {
        if (attr.source === 'SENSOR') {
          defaults[id] = (attr.physio_min + attr.physio_max) / 2
        }
      }
      setValues(defaults)
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Slider change → update local state immediately + debounce set_sensor msg
  const handleSliderChange = useCallback(
    (id: string, value: number) => {
      setValues(prev => ({ ...prev, [id]: value }))
      if (debounceTimers.current[id]) clearTimeout(debounceTimers.current[id])
      debounceTimers.current[id] = setTimeout(() => {
        sendControl({ type: 'set_sensor', id, value })
      }, 150)
    },
    [sendControl]
  )

  // Preset loading — fetch XML from backend static, parse via /api/upload,
  // update all sliders, then send set_sensor for every sensor at once
  const loadPreset = useCallback(
    async (id: string) => {
      setPresetBusy(true)
      setPresetErr(null)
      try {
        const res = await fetch(`/presets/${id}.xml`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const text = await res.text()
        const file = new File([text], `${id}.xml`, { type: 'text/xml' })
        const results = await uploadXML(file)
        const newValues: Record<string, number> = {}
        for (const [sensorId, attr] of Object.entries(results.sensors)) {
          newValues[sensorId] = attr.value
        }
        setValues(newValues)
        for (const [sensorId, value] of Object.entries(newValues)) {
          sendControl({ type: 'set_sensor', id: sensorId, value })
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        setPresetErr(`Failed to load preset: ${msg}`)
      } finally {
        setPresetBusy(false)
      }
    },
    [sendControl]
  )

  const handlePauseResume = useCallback(() => {
    const next = !paused
    sendControl({ type: next ? 'pause' : 'resume' })
    setPaused(next)
  }, [paused, sendControl])

  // Reset — tell backend to reset session, restore sliders to schema defaults
  const handleReset = useCallback(() => {
    sendControl({ type: 'reset' })
    setPaused(false)
    if (!schema) return
    const defaults: Record<string, number> = {}
    for (const [id, attr] of Object.entries(schema.attributes)) {
      if (attr.source === 'SENSOR') defaults[id] = (attr.physio_min + attr.physio_max) / 2
    }
    setValues(defaults)
  }, [schema, sendControl])

  const sensors = schema
    ? Object.values(schema.attributes).filter(a => a.source === 'SENSOR')
    : []

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col">

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 px-5 py-2.5 bg-slate-800 border-b border-slate-700 shrink-0">
        <button
          onClick={onBack}
          className="text-xs text-slate-400 hover:text-slate-200 transition-colors mr-1"
        >
          ← Analysis
        </button>

        <StatusPip status={status} />

        {latest && (
          <>
            <StatPill label="tick" value={String(latest.tick)} />
            <StatPill label="HR"   value={`${latest.hr.toFixed(0)} bpm`} />
            <StatPill label="CO"   value={`${latest.co.toFixed(2)} L/min`} />
            <StatPill label="‖X″‖" value={latest.feedback_norm.toFixed(4)} />
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={handlePauseResume}
            className={`px-3 py-1 text-xs rounded-md border transition-colors
              ${paused
                ? 'bg-emerald-800/60 hover:bg-emerald-700/60 border-emerald-700/50 text-emerald-300'
                : 'bg-slate-700 hover:bg-slate-600 border-slate-600 text-slate-300'
              }`}
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button
            onClick={handleReset}
            className="px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 border border-slate-600
                       text-slate-300 rounded-md transition-colors"
          >
            ↺ Reset
          </button>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">

        {/* ── Sidebar ─────────────────────────────────────────────────── */}
        <aside className="w-72 shrink-0 bg-slate-800/60 border-r border-slate-700 flex flex-col overflow-hidden">

          {/* Sidebar header */}
          <div className="px-4 py-3 border-b border-slate-700">
            <p className="text-cyan-400 font-bold text-sm tracking-wide">CardioTwin</p>
            <p className="text-slate-500 text-[10px]">Live Streaming Mode</p>
          </div>

          {/* Scrollable content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-5">

            {/* Presets */}
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
                Presets
              </p>
              <div className="grid grid-cols-3 gap-1.5">
                {PRESETS.map(p => (
                  <button
                    key={p.id}
                    onClick={() => loadPreset(p.id)}
                    disabled={presetBusy || status !== 'open'}
                    className="py-1.5 text-[10px] bg-slate-700 hover:bg-slate-600 active:bg-slate-500
                               text-slate-300 rounded transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              {presetBusy && (
                <p className="text-[10px] text-cyan-400 animate-pulse mt-1.5">Loading preset…</p>
              )}
              {presetErr && (
                <p className="text-[10px] text-red-400 mt-1.5">{presetErr}</p>
              )}
            </section>

            <div className="border-t border-slate-700/60" />

            {/* Sensor sliders — 10 inputs, each debounced 150ms → set_sensor */}
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">
                Sensor Inputs
              </p>
              {sensors.length === 0 ? (
                <p className="text-xs text-slate-600 italic animate-pulse">Loading schema…</p>
              ) : (
                <div className="space-y-4">
                  {sensors.map(attr => (
                    <SliderRow
                      key={attr.id}
                      attr={attr}
                      value={values[attr.id] ?? (attr.physio_min + attr.physio_max) / 2}
                      onChange={v => handleSliderChange(attr.id, v)}
                    />
                  ))}
                </div>
              )}
            </section>

            <div className="border-t border-slate-700/60" />

            {/* Arrhythmia injection */}
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
                Arrhythmia
              </p>
              <label className="text-xs text-slate-300 block mb-1">
                Magnitude:{' '}
                <span className="text-slate-100 font-mono">{magnitude} bpm</span>
              </label>
              <input
                type="range"
                min={10} max={60} step={5}
                value={magnitude}
                onChange={e => setMagnitude(Number(e.target.value))}
                className="w-full accent-amber-500 cursor-pointer"
              />
              <p className="text-[10px] text-slate-500 mt-1 mb-2.5">
                decay 0.15 · fades in ~25 ticks
              </p>
              <button
                onClick={() => sendControl({ type: 'inject_arrhythmia', magnitude, decay: 0.15 })}
                disabled={status !== 'open' || paused}
                className="w-full px-2 py-1.5 text-xs font-medium rounded-md border transition-colors
                           bg-amber-800/60 hover:bg-amber-700/60 border-amber-700/60 text-amber-200
                           disabled:opacity-40 disabled:cursor-not-allowed"
              >
                ⚡ Inject Arrhythmia
              </button>
            </section>

            <div className="border-t border-slate-700/60" />

            {/* Live readings */}
            <section>
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
                Current readings
              </p>
              {latest ? (
                <div className="space-y-1.5">
                  {/* Sensors */}
                  {[
                    { label: 'HR',  value: `${latest.hr.toFixed(0)} bpm`,   color: 'text-red-400' },
                    { label: 'SBP', value: `${latest.sbp.toFixed(0)} mmHg`, color: 'text-blue-400' },
                    { label: 'DBP', value: `${latest.dbp.toFixed(0)} mmHg`, color: 'text-purple-400' },
                  ].map(r => (
                    <div key={r.label} className="flex justify-between text-xs">
                      <span className="text-slate-500">{r.label}</span>
                      <span className={`font-mono ${r.color}`}>{r.value}</span>
                    </div>
                  ))}

                  {/* Divider */}
                  <div className="border-t border-slate-700/50 my-1" />

                  {/* Computed hemodynamics */}
                  {[
                    { label: 'CO',  value: `${latest.co.toFixed(2)} L/min`,  color: 'text-cyan-400' },
                    { label: 'Q',   value: `${latest.q.toFixed(2)} L/min`,   color: 'text-violet-400' },
                    { label: 'SV',  value: `${latest.sv.toFixed(1)} mL`,     color: 'text-sky-400' },
                    { label: 'MAP', value: `${latest.map.toFixed(1)} mmHg`,  color: 'text-orange-400' },
                  ].map(r => (
                    <div key={r.label} className="flex justify-between text-xs">
                      <span className="text-slate-500">{r.label}</span>
                      <span className={`font-mono ${r.color}`}>{r.value}</span>
                    </div>
                  ))}

                  {/* Divider */}
                  <div className="border-t border-slate-700/50 my-1" />

                  {/* Feedback */}
                  {[
                    { label: 'CO X″', value: latest.co_feedback.toFixed(4),
                      color: latest.co_feedback < 0 ? 'text-emerald-400' : 'text-slate-400' },
                    { label: 'SV X″', value: latest.sv_feedback.toFixed(4),
                      color: latest.sv_feedback < 0 ? 'text-indigo-400' : 'text-slate-400' },
                    { label: '‖X″‖',  value: latest.feedback_norm.toFixed(4),
                      color: latest.feedback_norm > 0.3 ? 'text-amber-400' : 'text-slate-300' },
                  ].map(r => (
                    <div key={r.label} className="flex justify-between text-xs">
                      <span className="text-slate-500">{r.label}</span>
                      <span className={`font-mono ${r.color}`}>{r.value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-600 italic">waiting for first tick…</p>
              )}
            </section>

            {/* Legend */}
            <section className="border-t border-slate-700 pt-4">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
                How to read
              </p>
              <ul className="text-[10px] text-slate-500 space-y-1 leading-relaxed">
                <li><span className="text-cyan-400">■</span> CO — cardiac output (L/min)</li>
                <li><span className="text-emerald-400">■ </span>SV — stroke volume (mL)</li>
                <li><span className="text-orange-400">■</span> MAP — mean arterial pressure</li>
                <li><span className="text-amber-400">■</span> ‖X″‖ — overall feedback correction</li>
                <li className="mt-1.5 text-slate-600">
                  Drag a slider or inject arrhythmia → watch charts react → recover.
                </li>
              </ul>
            </section>

          </div>
        </aside>

        {/* ── Charts ──────────────────────────────────────────────────── */}
        <div className="flex-1 p-4 space-y-3 overflow-y-auto min-w-0">

          <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
            <div className="flex items-baseline gap-2 mb-3">
              <h3 className="text-sm font-semibold text-slate-200">Sensor Feed</h3>
              <span className="text-[10px] text-slate-500">HR · SBP · DBP</span>
            </div>
            {ticks.length === 0 ? <Placeholder /> : <SensorChart ticks={ticks} />}
          </div>

          <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
            <div className="flex items-baseline gap-2 mb-3">
              <h3 className="text-sm font-semibold text-slate-200">Haemodynamics</h3>
              <span className="text-[10px] text-slate-500">CO · MAP · SV</span>
            </div>
            {ticks.length === 0 ? <Placeholder /> : <HemodynamicsChart ticks={ticks} />}
          </div>

          <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
            <div className="flex items-baseline gap-2 mb-3">
              <h3 className="text-sm font-semibold text-slate-200">Adaptation Loop</h3>
              <span className="text-[10px] text-slate-500">feedback norm · CO X″ · SV X″</span>
            </div>
            {ticks.length === 0 ? <Placeholder /> : <AdaptationChart ticks={ticks} />}
          </div>

        </div>
      </div>
    </div>
  )
}
