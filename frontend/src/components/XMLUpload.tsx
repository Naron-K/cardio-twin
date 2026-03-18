import { useRef, useState, useCallback } from 'react'
import { uploadXML } from '../utils/api'
import type { SimulationResults } from '../utils/api'
import { useToast } from './Toast'

const PRESETS = [
  { id: 'normal', label: 'Normal' },
  { id: 'hypertension', label: 'Hypertension' },
  { id: 'heart_failure', label: 'Heart Failure' },
]

interface XMLUploadProps {
  onLoad: (results: SimulationResults, values: Record<string, number>) => void
  disabled: boolean
}

export function XMLUpload({ onLoad, disabled }: XMLUploadProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const { showToast } = useToast()

  const processFile = useCallback(
    async (file: File) => {
      if (!file.name.endsWith('.xml')) {
        showToast('Please upload an .xml file', 'error')
        return
      }
      setBusy(true)
      try {
        const results = await uploadXML(file)
        // Extract sensor values from result to sync sliders
        const values: Record<string, number> = {}
        for (const [id, attr] of Object.entries(results.sensors)) {
          values[id] = attr.value
        }
        onLoad(results, values)
        showToast('XML loaded successfully', 'success')
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        showToast(`Upload failed: ${msg}`, 'error')
      } finally {
        setBusy(false)
      }
    },
    [onLoad, showToast]
  )

  const loadPreset = useCallback(
    async (id: string, label: string) => {
      setBusy(true)
      try {
        const res = await fetch(`/presets/${id}.xml`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const text = await res.text()
        const file = new File([text], `${id}.xml`, { type: 'text/xml' })
        await processFile(file)
        showToast(`Loaded preset: ${label}`, 'success')
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        showToast(`Failed to load preset: ${msg}`, 'error')
        setBusy(false)
      }
    },
    [processFile, showToast]
  )

  const isDisabled = disabled || busy

  return (
    <div className="space-y-3">
      <span className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
        Load Data
      </span>

      {/* Drag-and-drop / click-to-browse area */}
      <div
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files[0]
          if (file && !isDisabled) processFile(file)
        }}
        onDragOver={(e) => {
          e.preventDefault()
          if (!isDisabled) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onClick={() => !isDisabled && fileRef.current?.click()}
        className={`border-2 border-dashed rounded-md p-3 text-center text-xs transition-colors select-none
          ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
          ${dragging
            ? 'border-cyan-500 bg-cyan-900/20 text-cyan-300'
            : 'border-slate-600 hover:border-slate-500 text-slate-500 hover:text-slate-400'
          }`}
      >
        {busy ? 'Loading…' : 'Drop XML or click to browse'}
        <input
          ref={fileRef}
          type="file"
          accept=".xml"
          className="hidden"
          disabled={isDisabled}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) processFile(f)
            e.target.value = '' // reset so same file can be re-uploaded
          }}
        />
      </div>

      {/* Preset buttons */}
      <div className="grid grid-cols-3 gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => loadPreset(p.id, p.label)}
            disabled={isDisabled}
            className="py-1.5 text-xs bg-slate-700 hover:bg-slate-600 active:bg-slate-500
                       text-slate-300 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  )
}
