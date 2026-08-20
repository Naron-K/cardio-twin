/**
 * TwinDashboard — the 2D view of whatever lamina the backend is running.
 *
 * The screen is assembled from the model's own description of itself. The
 * schema names the lamina, lists its inputs, its computations, its subsystems,
 * its targets and the wiring of its feedback loop; the tick supplies the
 * numbers; this component arranges them. It contains no attribute id, no unit,
 * no threshold and no clinical judgement — swap `circulatory_lamina.xml` for a
 * lamina describing something else entirely and this file does not change.
 *
 * Three rules hold the layout together:
 *
 *   • **Only what the model computes is drawn.** Sensors appear on the input
 *     rail as controls and nowhere else. The stage receives the computed half
 *     of the snapshot as its single data prop, so there is no route by which a
 *     raw reading could reach the picture.
 *   • **Every band is the model's.** Targets, tolerances, ranges and gates are
 *     read off the schema and the tick. Nothing here decides what "good" means.
 *   • **Structure decides the tabs.** Views come from the view registry, which
 *     filters itself against the schema, so a lamina without composites simply
 *     has no vector-space tab.
 *
 * The centre is artwork where artwork exists for this lamina, and the lamina
 * map otherwise. The map is available either way, because it is the only view
 * that shows the model's shape rather than its values.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useCardioStream } from '../../hooks/useCardioStream'
import type { StreamTick } from '../../hooks/useCardioStream'
import { fetchSchema } from '../../utils/api'
import { indexLamina, fmtValue } from '../../twin/schema'
import type { LaminaIndex } from '../../twin/schema'
import { loadStage } from '../../twin/stageTemplate'
import type { LoadedStage } from '../../twin/stageTemplate'
import { artworkFor } from '../../twin/stageRegistry'
import { anyOutOfBand } from '../../twin/outcomes'
import { viewsFor, withinByOutcome } from '../../twin/views'
import { LaminaStage } from './LaminaStage'
import { LaminaMap } from './LaminaMap'
import { ProvenanceStrip } from './ProvenanceStrip'
import { InputRail } from './InputRail'
import { Panel, Chip } from './ui'

interface Props {
  onBack: () => void
}

/** Centre-stage options, assembled from what exists for this lamina. */
interface StageMode {
  id: string
  label: string
}

const MAP_MODE: StageMode = { id: 'map', label: 'Lamina map' }

export function TwinDashboard({ onBack }: Props) {
  // 300 ticks ≈ 30 s: long enough for a disturbance and the settling after it
  // to sit in the convergence window together.
  const { ticks, status, sendControl } = useCardioStream({ tickMs: 100, bufferSize: 300 })
  const latest: StreamTick | null = ticks.length > 0 ? ticks[ticks.length - 1] : null

  const [index, setIndex] = useState<LaminaIndex | null>(null)
  const [schemaError, setSchemaError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<LoadedStage | null>(null)
  const [paused, setPaused] = useState(false)
  /** What the reader picked, which may not exist for the lamina that loads. */
  const [chosen, setChosen] = useState<string | null>(null)
  const [chosenTab, setChosenTab] = useState<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  /** The map is the one view whose useful size is the lamina's size, not ours. */
  const [mapExpanded, setMapExpanded] = useState(false)

  // ── The model describes itself; everything below reads that description ───
  useEffect(() => {
    fetchSchema()
      .then((raw) => setIndex(indexLamina(raw)))
      .catch(() => setSchemaError('Schema failed to load — is the backend up on port 8000?'))
  }, [])

  const artwork = artworkFor(index?.schema.lamina_id)

  // Artwork is fetched at runtime, so bindings can change without a rebuild.
  // A lamina with no artwork is not an error; the map takes the centre. The
  // loaded template is only ever *used* through `stage` below, which is gated
  // on there being artwork at all, so no clearing pass is needed here.
  useEffect(() => {
    if (!artwork) return
    let live = true
    loadStage(artwork.dir)
      .then((s) => live && setLoaded(s))
      .catch(() => live && setLoaded(null))
    return () => {
      live = false
    }
  }, [artwork])
  const stage = artwork ? loaded : null

  const stageModes: StageMode[] = useMemo(() => {
    if (!artwork) return [MAP_MODE]
    return [
      { id: 'artwork', label: artwork.label },
      { id: 'schematic', label: 'Schematic' },
      ...artwork.alternates.map((a) => ({ id: a.id, label: a.label })),
      MAP_MODE,
    ]
  }, [artwork])

  const views = useMemo(() => (index ? viewsFor(index) : []), [index])

  // The selection is what the reader picked, *if* it still exists; otherwise
  // the first option. Derived rather than stored, because the available modes
  // and views are a function of the schema, which arrives after first render —
  // storing a default would mean writing state from an effect on every load.
  const mode = chosen && stageModes.some((m) => m.id === chosen) ? chosen : stageModes[0].id
  const tab = chosenTab && views.some((v) => v.id === chosenTab) ? chosenTab : (views[0]?.id ?? null)

  const togglePause = useCallback(() => {
    setPaused((was) => {
      sendControl({ type: was ? 'resume' : 'pause' })
      return !was
    })
  }, [sendControl])

  const handleReset = useCallback(() => {
    sendControl({ type: 'reset' })
    if (paused) sendControl({ type: 'resume' })
    setPaused(false)
  }, [sendControl, paused])

  const setSensor = useCallback(
    (id: string, value: number) => sendControl({ type: 'set_sensor', id, value }),
    [sendControl]
  )

  // The stage's entire data input: the computed half of the snapshot. Beat
  // timing included, via whichever attribute the template's rhythm binding
  // names. Sensors are absent by construction, not by omission.
  const modelValues = latest?.computed ?? {}
  const outcomes = latest?.beforeAfter ?? {}
  const alert = anyOutOfBand(outcomes)
  const within = withinByOutcome(latest)
  const activeView = views.find((v) => v.id === tab)

  if (schemaError) {
    return (
      <div className="h-screen flex flex-col items-center justify-center gap-4 bg-surface text-ink">
        <p className="font-mono text-[12px] readout text-crimson-container">{schemaError}</p>
        <button
          onClick={onBack}
          className="font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink"
        >
          ← Analysis
        </button>
      </div>
    )
  }

  if (!index) {
    return (
      <div className="h-screen flex items-center justify-center bg-surface">
        <p className="font-mono text-[12px] readout uppercase text-ink/40 animate-pulse">
          Reading the lamina…
        </p>
      </div>
    )
  }

  return (
    <div className="h-screen flex flex-col bg-surface text-ink font-body overflow-hidden">
      {/* ── Top bar — the lamina names itself ───────────────────────────── */}
      <header className="shrink-0 flex items-center gap-4 px-margin py-3 border-b border-white/10 bg-surface-low/70 backdrop-blur-lg">
        <button
          onClick={onBack}
          className="font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink transition-colors"
        >
          ← Analysis
        </button>

        <div className="flex items-baseline gap-2.5 pl-3 border-l border-white/10 min-w-0">
          <span className="font-display text-lg font-extrabold tracking-tight text-crimson-container truncate">
            {index.schema.lamina_name}
          </span>
          <span className="font-mono text-[10px] readout text-ink/30 truncate">
            {index.schema.lamina_id} · level {index.schema.lamina_level}
          </span>
        </div>

        <Chip tone={status === 'open' ? 'oxy' : 'crimson'} dot pulse={status !== 'open'}>
          {status === 'open' ? 'Live' : status === 'connecting' ? 'Reconnecting' : 'Offline'}
        </Chip>

        <div className="ml-auto flex items-center gap-3">
          <Readout label="Cycle" value={String(latest?.tick ?? 0)} />
          <Readout label="‖X″‖" value={(latest?.feedback_norm ?? 0).toFixed(4)} accent />
          <button
            onClick={togglePause}
            className="rounded-el border-2 border-oxy-container/60 px-3 py-1.5 font-mono text-[11px]
                       font-bold readout uppercase text-oxy hover:bg-oxy-container/15
                       hover:shadow-oxybloom transition-all"
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button
            onClick={handleReset}
            className="rounded-el border-2 border-white/15 px-3 py-1.5 font-mono text-[11px]
                       font-bold readout uppercase text-ink/60 hover:text-ink hover:border-white/30 transition-all"
          >
            ↺ Reset loop
          </button>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-[268px_minmax(0,1fr)_296px] gap-gutter px-margin py-gutter">
        {/* Left — the model's declared inputs */}
        <aside className="min-h-0 overflow-y-auto pr-1">
          <Panel
            className="!p-5"
            eyebrow={`${index.sensors.length} sensor attributes`}
            title="Model inputs"
          >
            <InputRail
              index={index}
              values={latest?.sensors ?? {}}
              disabled={paused}
              onChange={setSensor}
            />
          </Panel>
        </aside>

        {/* Centre — the stage */}
        <main className="min-h-0 flex flex-col gap-gutter">
          <div className="relative flex-1 min-h-0 rounded-card border border-white/10 shadow-inset1
                          bg-surface-lowest stage-grid overflow-hidden">
            <div className="absolute top-4 left-4 z-10">
              <Chip tone={paused ? 'warn' : 'oxy'} dot pulse={!paused}>
                {paused ? 'Paused' : 'Running'}
              </Chip>
            </div>
            <div className="absolute top-4 right-4 z-10">
              {/* The model's own verdict, not a range typed in here. */}
              <Chip tone={alert ? 'crimson' : 'neutral'}>
                {Object.keys(outcomes).length === 0
                  ? 'No outcomes declared'
                  : alert
                    ? 'Outcome outside tolerance'
                    : 'All outcomes in tolerance'}
              </Chip>
            </div>

            {stageModes.length > 1 && (
              <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex rounded-full
                              border border-white/10 bg-surface-lowest/80 p-0.5 backdrop-blur-sm">
                {stageModes.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setChosen(m.id)}
                    className={`rounded-full px-2.5 py-0.5 font-mono text-[10px] readout uppercase
                                transition-colors ${
                                  mode === m.id
                                    ? 'bg-white/10 text-ink'
                                    : 'text-ink/40 hover:text-ink/70'
                                }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            )}

            <div className={`absolute inset-0 flex items-center justify-center ${mode === 'map' ? 'p-4 pt-14' : 'p-10'}`}>
              {mode === 'map' ? (
                <LaminaMap
                  index={index}
                  computed={modelValues}
                  sensors={latest?.sensors ?? {}}
                  firing={latest?.tagsEmitted ?? []}
                  withinByOutcome={within}
                  expanded={false}
                  onToggleExpand={() => setMapExpanded(true)}
                />
              ) : (
                <div
                  className={`w-full h-full max-w-[440px] max-h-[440px] transition-[filter] duration-500 ${
                    mode !== 'artwork' && mode !== 'schematic' ? 'pixelated' : ''
                  } ${alert ? 'drop-shadow-[0_0_28px_rgba(255,82,95,0.45)]' : ''}`}
                >
                  {stage && (mode === 'artwork' || mode === 'schematic') ? (
                    <LaminaStage
                      stage={stage}
                      values={modelValues}
                      sources={index.sources}
                      paused={paused}
                      focus={focus}
                      mode={mode === 'schematic' ? 'schematic' : 'showcase'}
                    />
                  ) : (
                    artwork?.alternates
                      .find((a) => a.id === mode)
                      ?.render({ values: modelValues, paused, focus, alert }) ?? null
                  )}
                </div>
              )}
            </div>

            {/* Region legend, read off the template rather than a table of
                chamber names — the renderer does not know what it is drawing. */}
            {stage && mode !== 'map' && (
              <div className="absolute bottom-4 right-4 z-10 flex flex-col items-end gap-0.5">
                {stage.template.drawOrder
                  .filter((id) => stage.template.placeholders[id])
                  .map((id) => (
                    <button
                      key={id}
                      onMouseEnter={() => setFocus(id)}
                      onMouseLeave={() => setFocus(null)}
                      className={`rounded-full px-2 py-0.5 font-mono text-[10px] readout transition-colors ${
                        focus === id ? 'bg-white/10 text-ink' : 'text-ink/45 hover:bg-white/5'
                      }`}
                    >
                      {stage.template.placeholders[id].label}
                    </button>
                  ))}
              </div>
            )}

            {!latest && (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface/70 backdrop-blur-sm">
                <p className="font-mono text-[12px] readout uppercase text-ink/50 animate-pulse">
                  Waiting for twin data…
                </p>
              </div>
            )}
          </div>

          {/* Where the stage got its numbers — on screen in every artwork mode. */}
          {stage && mode !== 'map' && (
            <ProvenanceStrip stage={stage} sources={index.sources} />
          )}

          {/* Views the lamina earns, from the view registry. */}
          <Panel
            className="shrink-0"
            eyebrow={activeView?.eyebrow ?? ''}
            title={activeView?.title ?? ''}
            action={
              <span className="font-mono text-[10px] readout text-oxy/50 text-right leading-snug max-w-[260px]">
                Every value here is computed by the lamina — nothing is synthesised
              </span>
            }
          >
            <nav className="flex flex-wrap gap-1 mb-3 -mt-1">
              {views.map((v) => (
                <button
                  key={v.id}
                  onClick={() => setChosenTab(v.id)}
                  className={`rounded-el px-2.5 py-1 font-mono text-[10px] font-bold readout uppercase
                              transition-all border ${
                                tab === v.id
                                  ? 'bg-crimson-container/12 border-crimson-container/50 text-crimson'
                                  : 'border-transparent text-ink/40 hover:text-ink/75 hover:bg-white/5'
                              }`}
                >
                  {v.label}
                </button>
              ))}
            </nav>

            {activeView?.render({ index, ticks, latest }) ?? null}
          </Panel>
        </main>

        {/* Right — everything the model computed this cycle */}
        <aside className="min-h-0 overflow-y-auto flex flex-col gap-gutter pl-1">
          <Panel
            eyebrow={`${index.computed.length} computed attributes`}
            title="Model output"
          >
            <div className="space-y-1.5">
              {index.computed.map((attr) => {
                const outcome = (index.outcomesOfAttribute[attr.id] ?? [])
                  .map((o) => outcomes[o.id])
                  .find(Boolean)
                const xpp = latest?.computedFeedback[attr.id] ?? 0
                return (
                  <div key={attr.id} className="flex items-baseline gap-2" title={attr.description}>
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        outcome === undefined
                          ? 'bg-ink/15'
                          : outcome.within_after
                            ? 'bg-oxy-dim'
                            : 'bg-crimson-container'
                      }`}
                    />
                    <span className="font-mono text-[11px] font-bold readout text-ink/75">
                      {attr.id}
                    </span>
                    <span className="font-mono text-[9px] readout text-ink/25 truncate">
                      {attr.unit}
                    </span>
                    <span className="ml-auto font-mono text-[12px] font-bold tabular-nums text-ink shrink-0">
                      {fmtValue(latest?.computed[attr.id])}
                    </span>
                    {Math.abs(xpp) > 1e-4 && (
                      <span className="font-mono text-[9px] tabular-nums text-warn/70 shrink-0 w-[52px] text-right">
                        {xpp > 0 ? '+' : ''}
                        {xpp.toFixed(3)}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
            <p className="mt-3 font-mono text-[9px] readout text-ink/25 leading-snug">
              Dot is the model's own within-tolerance verdict; an attribute it declares no outcome
              for has no dot rather than a guessed one. The amber column is X″ — the part of the
              value the feedback loop is holding.
            </p>
          </Panel>

          <Panel eyebrow="Cycle report" title="This cycle">
            <div className="space-y-1.5 font-mono text-[10px] readout">
              <Line label="Tags fired">
                {latest?.tagsEmitted.length ? (
                  <span className="text-warn">{latest.tagsEmitted.join(', ')}</span>
                ) : (
                  <span className="text-ink/30">none</span>
                )}
              </Line>
              <Line label="Dead-zone snapped">
                {latest?.snapped.length ? (
                  <span className="text-ink/60">{latest.snapped.join(', ')}</span>
                ) : (
                  <span className="text-ink/30">none</span>
                )}
              </Line>
              <Line label="Circuit breaker">
                {latest?.diverged ? (
                  <span className="text-crimson-container">tripped — loop diverged</span>
                ) : (
                  <span className="text-oxy/60">holding</span>
                )}
              </Line>
              {(latest?.warnings.length ?? 0) > 0 && (
                <div className="pt-1.5 border-t border-white/10 space-y-0.5">
                  {latest!.warnings.slice(0, 4).map((w, i) => (
                    <p key={i} className="text-warn/70 leading-tight">
                      {w}
                    </p>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </aside>
      </div>

      {/* The expanded map covers the body rather than replacing it, so the
          reader lands back exactly where they were on shrink. */}
      {mapExpanded && (
        <div className="fixed inset-0 z-30 flex flex-col bg-surface/95 backdrop-blur-sm px-margin py-gutter">
          <div className="flex items-baseline gap-3 pb-3">
            <p className="font-mono text-[11px] font-bold readout uppercase text-oxy/55">
              {index.schema.lamina_id}
            </p>
            <h3 className="font-display text-base font-semibold text-ink">
              Everything the model declares, and how it is wired
            </h3>
            <button
              onClick={() => setMapExpanded(false)}
              className="ml-auto font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink"
            >
              ✕ Close
            </button>
          </div>
          <div className="flex-1 min-h-0 rounded-card border border-white/10 shadow-inset1
                          bg-surface-lowest stage-grid p-3">
            <LaminaMap
              index={index}
              computed={modelValues}
              sensors={latest?.sensors ?? {}}
              firing={latest?.tagsEmitted ?? []}
              withinByOutcome={within}
              expanded
              onToggleExpand={() => setMapExpanded(false)}
            />
          </div>
        </div>
      )}

      {/* ── Status line ─────────────────────────────────────────────────── */}
      <footer className="shrink-0 flex items-center gap-3 px-margin py-3 border-t border-white/10 bg-surface-lowest/80">
        <span className="font-mono text-[11px] readout text-oxy-container">{'>'}</span>
        <span className="font-mono text-[11px] readout text-ink/55 truncate">
          {index.sensors.length} inputs · {index.functions.length} functions ·{' '}
          {index.computed.length} computed · {index.outcomes.length} outcomes ·{' '}
          {index.tags.length} tags · {index.composites.length} composites · {index.gates.length}{' '}
          gates — all read from {index.schema.lamina_id}
        </span>
        <span className="ml-auto font-mono text-[10px] readout text-ink/25 shrink-0">
          {views.length} views apply to this lamina
        </span>
      </footer>
    </div>
  )
}

// ── Small pieces ──────────────────────────────────────────────────────────────

function Readout({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[10px] readout uppercase text-ink/30">{label}</span>
      <span
        className={`font-mono text-[13px] font-bold tabular-nums ${
          accent ? 'text-crimson-container' : 'text-ink/80'
        }`}
      >
        {value}
      </span>
    </span>
  )
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <p className="flex items-baseline gap-2">
      <span className="text-ink/30 shrink-0">{label}</span>
      <span className="ml-auto text-right truncate">{children}</span>
    </p>
  )
}
