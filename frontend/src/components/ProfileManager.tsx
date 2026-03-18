import { useState, useCallback } from 'react'
import { getProfiles, saveProfile, deleteProfile, buildPatientXML } from '../utils/localStorage'
import type { Profile } from '../utils/localStorage'
import { useToast } from './Toast'

interface ProfileManagerProps {
  values: Record<string, number>
  onLoad: (values: Record<string, number>) => void
  disabled: boolean
}

export function ProfileManager({ values, onLoad, disabled }: ProfileManagerProps) {
  const [profiles, setProfiles] = useState<Profile[]>(() => getProfiles())
  const [name, setName] = useState('')
  const { showToast } = useToast()

  const refresh = () => setProfiles(getProfiles())

  const handleSave = useCallback(() => {
    const trimmed = name.trim()
    if (!trimmed) {
      showToast('Enter a name before saving', 'warning')
      return
    }
    saveProfile(trimmed, values)
    refresh()
    setName('')
    showToast(`Profile "${trimmed}" saved`, 'success')
  }, [name, values, showToast])

  const handleLoad = useCallback(
    (p: Profile) => {
      onLoad(p.values)
      showToast(`Loaded "${p.name}"`, 'info')
    },
    [onLoad, showToast]
  )

  const handleDelete = useCallback(
    (p: Profile) => {
      deleteProfile(p.id)
      refresh()
      showToast(`Deleted "${p.name}"`, 'info')
    },
    [showToast]
  )

  const handleExport = useCallback((p: Profile) => {
    const xml = buildPatientXML(p.name, p.values)
    const blob = new Blob([xml], { type: 'application/xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${p.name.replace(/\s+/g, '_')}.xml`
    a.click()
    URL.revokeObjectURL(url)
  }, [])

  return (
    <div className="space-y-3">
      <span className="text-slate-400 text-xs font-semibold uppercase tracking-widest">
        Profiles
      </span>

      {/* Save input row */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Profile name…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !disabled && handleSave()}
          disabled={disabled}
          className="flex-1 min-w-0 px-2 py-1.5 bg-slate-700 border border-slate-600 rounded
                     text-slate-200 text-xs placeholder-slate-500
                     focus:outline-none focus:border-cyan-500 disabled:opacity-50"
        />
        <button
          onClick={handleSave}
          disabled={disabled}
          className="px-2.5 py-1.5 bg-cyan-700 hover:bg-cyan-600 active:bg-cyan-500
                     text-white text-xs rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
        >
          Save
        </button>
      </div>

      {/* Saved profile list */}
      {profiles.length > 0 ? (
        <div className="space-y-1.5 max-h-44 overflow-y-auto pr-0.5">
          {profiles.map((p) => (
            <div
              key={p.id}
              className="flex items-center gap-1 bg-slate-700/50 border border-slate-700 rounded px-2 py-1.5"
            >
              <div className="flex-1 min-w-0">
                <p className="text-slate-200 text-xs truncate" title={p.name}>
                  {p.name}
                </p>
                <p className="text-slate-500 text-xs">
                  {new Date(p.timestamp).toLocaleDateString()}
                </p>
              </div>

              {/* Actions */}
              <button
                onClick={() => handleLoad(p)}
                className="text-xs text-cyan-400 hover:text-cyan-300 px-1 py-0.5 shrink-0"
                title="Load profile"
              >
                Load
              </button>
              <button
                onClick={() => handleExport(p)}
                className="text-xs text-slate-400 hover:text-slate-300 px-1 py-0.5 shrink-0"
                title="Export as XML"
              >
                XML
              </button>
              <button
                onClick={() => handleDelete(p)}
                className="text-xs text-red-500 hover:text-red-400 px-1 py-0.5 shrink-0"
                title="Delete profile"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-slate-600 text-xs">No saved profiles</p>
      )}
    </div>
  )
}
