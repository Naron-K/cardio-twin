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
import { fetchLaminae, fetchSchema } from '../../utils/api'
import type { LaminaOption } from '../../utils/api'
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
  /** Lamina id to open, or null for whatever the backend defaults to. */
  lamina: string | null
  /** Report the lamina back up so it lands in the URL. */
  onLamina: (id: string) => void
  onBack: () => void
}

/** Centre-stage options, assembled from what exists for this lamina. */
interface StageMode {
  id: string
  label: string
}

const MAP_MODE: StageMode = { id: 'map', label: 'Lamina map' }

export function TwinDashboard({ lamina, onLamina, onBack }: Props) {
  // 300 ticks ≈ 30 s: long enough for a disturbance and the settling after it
  // to sit in the convergence window together.
  const { ticks, status, sendControl, lastTickAt, closeReason } = useCardioStream({
    tickMs: 100,
    bufferSize: 300,
    lamina,
  })
  const newest: StreamTick | null = ticks.length > 0 ? ticks[ticks.length - 1] : null

  /**
   * The structure, tagged with the lamina it was fetched for.
   *
   * Tagged rather than cleared, because "which lamina is this the shape of" is
   * the question the whole screen turns on. A structure whose tag no longer
   * matches the lamina being asked for is not this screen's structure, and is
   * not read — so no render passes through drawing one model over another's
   * numbers, which is the failure this file exists to make impossible.
   */
  const [structure, setStructure] = useState<
    { lamina: string | null; index: LaminaIndex } | null
  >(null)
  const [failure, setFailure] = useState<{ lamina: string | null; message: string } | null>(null)
  const [laminae, setLaminae] = useState<LaminaOption[]>([])

  const index = structure && structure.lamina === lamina ? structure.index : null
  const schemaError = failure && failure.lamina === lamina ? failure.message : null
  const [loaded, setLoaded] = useState<LoadedStage | null>(null)
  const [paused, setPaused] = useState(false)
  /** What the reader picked, which may not exist for the lamina that loads. */
  const [chosen, setChosen] = useState<string | null>(null)
  const [chosenTab, setChosenTab] = useState<string | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  /** The map is the one view whose useful size is the lamina's size, not ours. */
  const [mapExpanded, setMapExpanded] = useState(false)

  // ── The model describes itself; everything below reads that description ───
  //
  // Re-read on every lamina change, and clear the old index first. A page that
  // fetched its structure once and never again is how this went wrong: the old
  // lamina's shape stayed on screen over the new one's numbers, named the old
  // lamina in the header, and drew the old lamina's artwork — all of it looking
  // entirely correct.
  useEffect(() => {
    let live = true
    fetchSchema(lamina)
      .then((raw) => live && setStructure({ lamina, index: indexLamina(raw) }))
      .catch((e) =>
        live &&
        setFailure({
          lamina,
          message:
            e?.response?.status === 404
              ? `No lamina with id "${lamina}" — the backend does not serve one.`
              : 'Schema failed to load — is the backend up on port 8000?',
        })
      )
    return () => {
      live = false
    }
  }, [lamina])

  // What this backend can serve. The picker is built from the answer rather
  // than from a list typed in here, so dropping a lamina XML into `backend/`
  // is the whole of adding one.
  useEffect(() => {
    let live = true
    fetchLaminae()
      .then((r) => live && setLaminae(r.laminae))
      .catch(() => live && setLaminae([]))
    return () => {
      live = false
    }
  }, [])

  // ── The invariant: structure and values came from the same lamina ────────
  //
  // Checked every tick, because the ways it can break are not all things this
  // component did. Restarting the backend onto another lamina behind an open
  // tab is one — and is exactly how the bug was found. On a mismatch, no value
  // is rendered at all: a number drawn under the wrong model's labels is worse
  // than no number, and the effect below re-fetches the structure for whatever
  // the socket is actually sending, which converges without a reload.
  const streamLamina = newest?.laminaId ?? ''
  const mismatch = Boolean(index && streamLamina && streamLamina !== index.schema.lamina_id)

  useEffect(() => {
    if (mismatch && streamLamina) onLamina(streamLamina)
  }, [mismatch, streamLamina, onLamina])

  // Nothing downstream sees a tick from a lamina this screen was not drawn for.
  const latest: StreamTick | null = mismatch ? null : newest

  // ── A dead socket must not look like a live one ──────────────────────────
  //
  // When the socket is not open, every number on screen is a photograph of the
  // last tick. It does not dim, it does not stop, and the connection chip
  // flipping to Reconnecting is not what anyone is reading. So the value
  // columns are dimmed and the age of the last tick is stamped, on the same
  // rule the ECG and the simulated feed already follow.
  const stale = status !== 'open' && latest !== null
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!stale) return
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [stale])
  const staleAge = stale && lastTickAt ? Math.max(0, Math.round((now - lastTickAt) / 1000)) : null
  const dim = stale ? 'opacity-40 transition-opacity duration-500' : 'transition-opacity duration-500'

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
  const feed = latest?.source ?? { kind: 'unknown', detail: '' }

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
          <LaminaPicker
            laminae={laminae}
            current={index.schema.lamina_id}
            onPick={onLamina}
          />
          <span className="font-mono text-[10px] readout text-ink/30 truncate">
            {index.schema.lamina_id} · level {index.schema.lamina_level}
          </span>
        </div>

        <Chip tone={status === 'open' ? 'oxy' : 'crimson'} dot pulse={status !== 'open'}>
          {status === 'open' ? 'Streaming' : status === 'connecting' ? 'Reconnecting' : 'Offline'}
        </Chip>

        {/* The numbers are a photograph, and say so with their age. */}
        {staleAge !== null && (
          <Chip tone="crimson" title="The socket is not open — nothing on screen is updating.">
            Frozen · last tick {staleAge}s ago
          </Chip>
        )}

        {/* What is producing the readings, as the backend reports it. The
            socket being open says the connection is live; it says nothing
            about whether a patient is on the other end of it, and a screen of
            convincingly wobbling numbers should not leave that to be assumed. */}
        {feed.kind === 'simulated' && (
          <Chip tone="warn" title={feed.detail}>
            Simulated feed
          </Chip>
        )}

        <div className="ml-auto flex items-center gap-3">
          <span className={`flex items-center gap-3 ${dim}`}>
            <Readout label="Cycle" value={String(latest?.tick ?? 0)} />
            <Readout label="‖X″‖" value={(latest?.feedback_norm ?? 0).toFixed(4)} accent />
          </span>
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
            eyebrow={
              index.inbound.length > 0
                ? `${index.sensors.length} sensor · ${index.inbound.length} inbound`
                : `${index.sensors.length} sensor attributes`
            }
            title="Model inputs"
          >
            <InputRail
              index={index}
              values={latest?.sensors ?? {}}
              inbound={latest?.inbound ?? {}}
              inboundProvenance={latest?.inboundProvenance ?? {}}
              sourceKind={feed.kind}
              disabled={paused || status !== 'open'}
              onChange={setSensor}
            />
          </Panel>
        </aside>

        {/* Centre — the stage */}
        <main className="min-h-0 flex flex-col gap-gutter">
          <div className={`relative flex-1 min-h-0 rounded-card border border-white/10 shadow-inset1
                          bg-surface-lowest stage-grid overflow-hidden ${stale ? 'saturate-50' : ''}`}>
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

            <div className={`absolute inset-0 flex items-center justify-center ${dim} ${mode === 'map' ? 'p-4 pt-14' : 'p-10'}`}>
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
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2
                              bg-surface/80 backdrop-blur-sm px-8 text-center">
                {mismatch ? (
                  <>
                    <p className="font-mono text-[12px] font-bold readout uppercase text-crimson-container">
                      Stream changed lamina
                    </p>
                    <p className="font-mono text-[11px] readout text-ink/55 leading-relaxed max-w-[380px]">
                      This screen was drawn for <b>{index.schema.lamina_id}</b> and the socket is
                      sending <b>{streamLamina}</b>. Values are held back rather than shown under
                      the wrong model. Re-reading the structure for {streamLamina}…
                    </p>
                  </>
                ) : closeReason ? (
                  <>
                    <p className="font-mono text-[12px] font-bold readout uppercase text-crimson-container">
                      Stream refused
                    </p>
                    <p className="font-mono text-[11px] readout text-ink/55 max-w-[380px]">
                      {closeReason}
                    </p>
                  </>
                ) : (
                  <p className="font-mono text-[12px] readout uppercase text-ink/50 animate-pulse">
                    Waiting for twin data…
                  </p>
                )}
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

            <div className={dim}>{activeView?.render({ index, ticks, latest }) ?? null}</div>
          </Panel>
        </main>

        {/* Right — everything the model computed this cycle */}
        <aside className="min-h-0 overflow-y-auto flex flex-col gap-gutter pl-1">
          <Panel
            eyebrow={`${index.computed.length} computed attributes`}
            title="Model output"
          >
            <div className={`space-y-1.5 ${dim}`}>
              {index.computed.map((attr) => {
                const outcome = (index.outcomesOfAttribute[attr.id] ?? [])
                  .map((o) => outcomes[o.id])
                  .find(Boolean)
                const xpp = latest?.computedFeedback[attr.id] ?? 0
                // The backend says this one did not compute; the number beside
                // it is last cycle's. Dim it and say so, rather than letting a
                // frozen value sit here looking exactly as live as the rest.
                const staleReason = latest?.staleComputed[attr.id]
                return (
                  <div
                    key={attr.id}
                    className="flex items-baseline gap-2"
                    title={staleReason ? `${attr.id} — ${staleReason}` : attr.description}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        staleReason
                          ? 'bg-warn'
                          : outcome === undefined
                            ? 'bg-ink/15'
                            : outcome.within_after
                              ? 'bg-oxy-dim'
                              : 'bg-crimson-container'
                      }`}
                    />
                    <span
                      className={`font-mono text-[11px] font-bold readout ${
                        staleReason ? 'text-ink/35' : 'text-ink/75'
                      }`}
                    >
                      {attr.id}
                    </span>
                    <span className="font-mono text-[9px] readout text-ink/25 truncate">
                      {staleReason ? 'stale' : attr.unit}
                    </span>
                    <span
                      className={`ml-auto font-mono text-[12px] font-bold tabular-nums shrink-0 ${
                        staleReason ? 'text-ink/30 line-through decoration-warn/50' : 'text-ink'
                      }`}
                    >
                      {fmtValue(latest?.computed[attr.id])}
                    </span>
                    {!staleReason && Math.abs(xpp) > 1e-4 && (
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
              value the feedback loop is holding. A struck-through row did not compute this cycle:
              the number is the last one that did, and hovering says what broke.
            </p>
          </Panel>

          <Panel eyebrow="Cycle report" title="This cycle">
            <div className={`space-y-1.5 font-mono text-[10px] readout ${dim}`}>
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

/**
 * The lamina, as something you pick rather than something you restart into.
 *
 * The list is the backend's answer to "what can you serve", so a lamina that
 * exists shows up here without an edit. A lamina whose arithmetic nobody has
 * written is offered and marked, not hidden: it loads, draws its whole
 * structure and shows a dash on every computed node, which is a fair picture of
 * "declared but not implemented" and a reasonable thing to want to look at.
 *
 * Picking one is a single act upstream — the schema and the socket are both
 * reopened with that id, together or not at all. Falling back to a plain label
 * when the catalogue is unavailable keeps the header honest rather than
 * offering a choice that would not work.
 */
function LaminaPicker({
  laminae,
  current,
  onPick,
}: {
  laminae: LaminaOption[]
  current: string
  onPick: (id: string) => void
}) {
  const name = laminae.find((l) => l.id === current)?.name ?? current

  if (laminae.length < 2) {
    return (
      <span className="font-display text-lg font-extrabold tracking-tight text-crimson-container truncate">
        {name}
      </span>
    )
  }

  return (
    <label className="relative flex items-baseline group" title="Switch lamina">
      <select
        value={current}
        onChange={(e) => onPick(e.target.value)}
        className="appearance-none cursor-pointer bg-transparent pr-4 font-display text-lg font-extrabold
                   tracking-tight text-crimson-container outline-none
                   focus-visible:ring-2 focus-visible:ring-crimson-container/50 rounded-el"
      >
        {laminae.map((l) => (
          <option key={l.id} value={l.id} className="bg-surface-low text-ink font-body">
            {l.name}
            {l.implemented ? '' : ' — structure only'}
          </option>
        ))}
      </select>
      <span
        aria-hidden
        className="pointer-events-none absolute right-0 bottom-1 font-mono text-[9px] text-ink/35
                   group-hover:text-ink/70 transition-colors"
      >
        ▼
      </span>
    </label>
  )
}

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
