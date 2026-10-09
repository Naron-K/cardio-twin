/**
 * InspectDrawer — the machinery behind the dashboard, out of the audience's way.
 *
 * The dashboard answers "what is the twin saying". This answers "how did it get
 * there": the declared functions with live values substituted, the segments,
 * the loop and the tags that wired it, the composites, the pipeline
 * configuration, and the lamina map. They are the same views the twin screen
 * has always had, from the same view registry, so a lamina earns exactly the
 * tabs it earns there and nothing is maintained twice.
 */
import { useEffect, useState } from 'react'
import type { StreamTick } from '../../hooks/useCardioStream'
import type { LaminaIndex } from '../../twin/schema'
import { viewsFor, withinByOutcome } from '../../twin/views'
import { LaminaMap } from '../twin/LaminaMap'

interface Props {
  index: LaminaIndex
  ticks: StreamTick[]
  latest: StreamTick | null
  onClose: () => void
}

const MAP_TAB = { id: 'map', label: 'Lamina map' }

export function InspectDrawer({ index, ticks, latest, onClose }: Props) {
  const views = viewsFor(index)
  const tabs = [...views.map((v) => ({ id: v.id, label: v.label })), MAP_TAB]
  const [chosen, setChosen] = useState<string>(tabs[0].id)
  const tab = tabs.some((t) => t.id === chosen) ? chosen : tabs[0].id
  const view = views.find((v) => v.id === tab)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        aria-label="Close inspector"
        onClick={onClose}
        className="absolute inset-0 bg-surface/60 backdrop-blur-[2px] cursor-default"
      />
      <aside
        className="relative h-full w-[min(1120px,74vw)] flex flex-col bg-surface-low border-l
                   border-white/10 shadow-inset1"
      >
        <header className="shrink-0 flex items-baseline gap-3 px-6 pt-5 pb-3 border-b border-white/10">
          <p className="font-mono text-[11px] font-bold readout uppercase text-oxy/55">
            Inspect · {index.schema.lamina_id}
          </p>
          <h3 className="font-display text-base font-semibold text-ink">
            {view?.title ?? 'Everything the model declares, and how it is wired'}
          </h3>
          <button
            onClick={onClose}
            className="ml-auto font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink"
          >
            ✕ Close
          </button>
        </header>

        <nav className="shrink-0 flex flex-wrap gap-1 px-6 py-3">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setChosen(t.id)}
              className={`rounded-el px-2.5 py-1 font-mono text-[10px] font-bold readout uppercase
                          transition-all border ${
                            tab === t.id
                              ? 'bg-crimson-container/12 border-crimson-container/50 text-crimson'
                              : 'border-transparent text-ink/40 hover:text-ink/75 hover:bg-white/5'
                          }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="flex-1 min-h-0 overflow-y-auto px-6 pb-6">
          {tab === MAP_TAB.id ? (
            <div className="h-full min-h-[480px] rounded-card border border-white/10 bg-surface-lowest stage-grid p-3">
              <LaminaMap
                index={index}
                computed={latest?.computed ?? {}}
                sensors={latest?.sensors ?? {}}
                firing={latest?.tagsEmitted ?? []}
                withinByOutcome={withinByOutcome(latest)}
                expanded
                onToggleExpand={() => undefined}
              />
            </div>
          ) : (
            // The views cap their own height to fit the twin screen's small tab
            // panel. Here the drawer is the scroller, so the caps are lifted for
            // its contents only; a capped view would cut its cards off halfway
            // down a mostly empty drawer.
            <div className="[&_.overflow-y-auto]:max-h-none">
              {view && <p className="font-mono text-[11px] readout text-oxy/50 mb-2">{view.eyebrow}</p>}
              {view?.render({ index, ticks, latest }) ?? null}
            </div>
          )}

          <CycleReport latest={latest} />
        </div>
      </aside>
    </div>
  )
}

/** What the loop did on the newest cycle, as the backend reported it. */
function CycleReport({ latest }: { latest: StreamTick | null }) {
  return (
    <div className="mt-5 pt-3 border-t border-white/10 grid grid-cols-3 gap-4 font-mono text-[11px] readout">
      <Item label="Tags fired">
        {latest?.tagsEmitted.length ? (
          <span className="text-warn">{latest.tagsEmitted.join(', ')}</span>
        ) : (
          <span className="text-ink/30">none</span>
        )}
      </Item>
      <Item label="Dead-zone snapped">
        {latest?.snapped.length ? (
          <span className="text-ink/60">{latest.snapped.join(', ')}</span>
        ) : (
          <span className="text-ink/30">none</span>
        )}
      </Item>
      <Item label="Circuit breaker">
        {latest?.diverged ? (
          <span className="text-crimson-container">tripped, loop diverged</span>
        ) : (
          <span className="text-oxy/60">holding</span>
        )}
      </Item>
      {(latest?.warnings.length ?? 0) > 0 && (
        <div className="col-span-3 space-y-0.5">
          {latest!.warnings.slice(0, 6).map((w, i) => (
            <p key={i} className="text-warn/70 leading-tight">
              {w}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase text-ink/30">{label}</p>
      <p className="mt-0.5">{children}</p>
    </div>
  )
}
