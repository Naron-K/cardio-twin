/**
 * Dashboard — the one screen, read left to right the way the data travels.
 *
 *   1 Data sources   how measurements enter the twin, grouped by the channel
 *                    the lamina maps each input to
 *   2 Digital twin   what the model computes from them, as an animation, a
 *                    set of trends, or a table — the presenter picks
 *   3 Outcomes       the model's verdict against the targets it declares
 *   4 Over time      distance from those targets, with and without the loop
 *
 * Everything technical (functions with live values, segments, tags, the
 * composites, the pipeline configuration, the lamina map) sits behind Inspect,
 * so the audience sees the story and a reviewer can still reach the machinery.
 *
 * The rules of the twin screen hold here unchanged, and through the same code:
 * structure from the schema, values from the tick, nothing from a constant in a
 * component; the stage is handed computed values only; a tick from another
 * lamina is never drawn under this one's labels; a dead socket says so.
 */
import { useState } from 'react'
import { useLaminaTwin } from '../../hooks/useLaminaTwin'
import { anyOutOfBand } from '../../twin/outcomes'
import { LaminaStage } from '../twin/LaminaStage'
import { LaminaMap } from '../twin/LaminaMap'
import { ProvenanceStrip } from '../twin/ProvenanceStrip'
import { InputRail } from '../twin/InputRail'
import { LaminaPicker } from '../twin/LaminaPicker'
import { ConvergenceChart } from '../twin/ConvergenceChart'
import { Chip, Panel } from '../twin/ui'
import { withinByOutcome } from '../../twin/views'
import { OutcomeTiles } from './OutcomeTiles'
import { TrendGrid } from './TrendGrid'
import { StateTable } from './StateTable'
import { InspectDrawer } from './InspectDrawer'
import { TWIN_FORMS } from './forms'
import type { OtherScreen, TwinForm } from './forms'


interface Props {
  /** Lamina id to open, or null for whatever the backend defaults to. */
  lamina: string | null
  onLamina: (id: string) => void
  form: TwinForm
  onForm: (form: TwinForm) => void
  onOpen: (screen: OtherScreen) => void
}

export function Dashboard({ lamina, onLamina, form, onForm, onOpen }: Props) {
  const twin = useLaminaTwin({ lamina, onLamina })
  const { index, latest, ticks, status, stale, staleAge, stage, artwork, paused } = twin
  const [inspecting, setInspecting] = useState(false)

  if (twin.schemaError) {
    return (
      <div className="h-screen flex flex-col items-center justify-center gap-4 bg-surface text-ink">
        <p className="font-mono text-[12px] readout text-crimson-container">{twin.schemaError}</p>
        <button
          onClick={() => onOpen('analysis')}
          className="font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink"
        >
          Open the analysis screen
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

  const dim = stale ? 'opacity-40 transition-opacity duration-500' : 'transition-opacity duration-500'
  const feed = latest?.source ?? { kind: 'unknown', detail: '' }
  const outcomes = latest?.beforeAfter ?? {}
  const alert = anyOutOfBand(outcomes)
  const modelValues = latest?.computed ?? {}
  const formLabel: Record<TwinForm, string> = {
    // A lamina with no artwork has no animation; its map takes that slot.
    animation: artwork ? 'Animation' : 'Map',
    graph: 'Graph',
    table: 'Table',
  }

  return (
    <div className="h-screen flex flex-col bg-surface text-ink font-body overflow-hidden">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="shrink-0 flex items-center gap-4 px-margin py-3 border-b border-white/10 bg-surface-low/70 backdrop-blur-lg">
        <span className="font-display text-lg font-extrabold tracking-tight text-ink">
          CardioTwin
        </span>
        <div className="flex items-baseline gap-2.5 pl-3 border-l border-white/10 min-w-0">
          <LaminaPicker laminae={twin.laminae} current={index.schema.lamina_id} onPick={onLamina} />
          <span className="font-mono text-[10px] readout text-ink/30 truncate">
            {index.schema.lamina_id} · level {index.schema.lamina_level}
          </span>
        </div>

        <Chip tone={status === 'open' ? 'oxy' : 'crimson'} dot pulse={status !== 'open'}>
          {status === 'open' ? 'Live' : status === 'connecting' ? 'Reconnecting' : 'Offline'}
        </Chip>
        {staleAge !== null && (
          <Chip tone="crimson" title="The socket is not open, so nothing on screen is updating.">
            Frozen · last tick {staleAge}s ago
          </Chip>
        )}
        {/* What is producing the readings, as the backend reports it. */}
        {feed.kind === 'simulated' && (
          <Chip tone="warn" title={feed.detail}>
            Simulated feed · no device connected
          </Chip>
        )}

        <div className="ml-auto flex items-center gap-3">
          <span className={`flex items-baseline gap-1.5 ${dim}`}>
            <span className="font-mono text-[10px] readout uppercase text-ink/30">Cycle</span>
            <span className="font-mono text-[13px] font-bold tabular-nums text-ink/80">
              {latest?.tick ?? 0}
            </span>
          </span>
          <HeaderButton onClick={twin.togglePause} accent>
            {paused ? '▶ Resume' : '⏸ Pause'}
          </HeaderButton>
          <HeaderButton onClick={twin.reset}>↺ Reset loop</HeaderButton>
          <HeaderButton onClick={() => setInspecting(true)}>Inspect ▸</HeaderButton>
        </div>
      </header>

      {/* ── Body: sources | twin | outcomes, with time underneath ──────── */}
      <div
        className="flex-1 min-h-0 grid gap-gutter px-margin py-gutter
                   grid-cols-[300px_minmax(0,1fr)_360px] grid-rows-[minmax(0,1fr)_auto]"
      >
        {/* 1 — Data sources */}
        <Panel
          className="row-span-2 min-h-0 overflow-y-auto !p-5"
          eyebrow="1 · Data sources"
          title="How measurements enter the twin"
        >
          <InputRail
            index={index}
            values={latest?.sensors ?? {}}
            inbound={latest?.inbound ?? {}}
            inboundProvenance={latest?.inboundProvenance ?? {}}
            sourceKind={feed.kind}
            disabled={paused || status !== 'open'}
            groupBy="channel"
            onChange={twin.setSensor}
          />
        </Panel>

        {/* 2 — Digital twin */}
        <Panel
          className="min-h-0 flex flex-col !p-5"
          eyebrow="2 · Digital twin"
          title="What the model computes from them, every cycle"
          action={
            <div className="flex rounded-full border border-white/10 bg-surface-lowest/80 p-0.5">
              {TWIN_FORMS.map((f) => (
                <button
                  key={f}
                  onClick={() => onForm(f)}
                  className={`rounded-full px-3 py-1 font-mono text-[11px] readout uppercase transition-colors ${
                    form === f ? 'bg-white/10 text-ink' : 'text-ink/40 hover:text-ink/70'
                  }`}
                >
                  {formLabel[f]}
                </button>
              ))}
            </div>
          }
        >
          <div
            className={`relative flex-1 min-h-0 rounded-card border border-white/10 shadow-inset1
                        bg-surface-lowest overflow-hidden ${form === 'animation' ? 'stage-grid' : ''}
                        ${stale ? 'saturate-50' : ''}`}
          >
            <div className="absolute top-3 right-3 z-10">
              {/* The model's own verdict, not a range typed in here. */}
              <Chip tone={alert ? 'crimson' : 'neutral'}>
                {Object.keys(outcomes).length === 0
                  ? 'No outcomes yet'
                  : alert
                    ? 'Outcome outside tolerance'
                    : 'All outcomes in tolerance'}
              </Chip>
            </div>

            <div className={`absolute inset-0 ${dim} ${form === 'animation' ? 'flex items-center justify-center p-8' : 'p-4 pt-12'}`}>
              {form === 'graph' ? (
                <TrendGrid index={index} ticks={twin.mismatch ? [] : ticks} />
              ) : form === 'table' ? (
                <StateTable index={index} latest={latest} />
              ) : artwork ? (
                <div
                  className={`w-full h-full max-w-[540px] max-h-[540px] transition-[filter] duration-500 ${
                    alert ? 'drop-shadow-[0_0_28px_rgba(255,82,95,0.45)]' : ''
                  }`}
                >
                  {stage && (
                    <LaminaStage
                      stage={stage}
                      values={modelValues}
                      sources={index.sources}
                      paused={paused}
                      mode="showcase"
                    />
                  )}
                </div>
              ) : (
                <LaminaMap
                  index={index}
                  computed={modelValues}
                  sensors={latest?.sensors ?? {}}
                  firing={latest?.tagsEmitted ?? []}
                  withinByOutcome={withinByOutcome(latest)}
                  expanded={false}
                  onToggleExpand={() => setInspecting(true)}
                />
              )}
            </div>

            {!latest && (
              <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-surface/80 backdrop-blur-sm px-8 text-center">
                {twin.mismatch ? (
                  <p className="font-mono text-[11px] readout text-ink/55 max-w-[380px] leading-relaxed">
                    This screen was drawn for <b>{index.schema.lamina_id}</b> and the socket is
                    sending <b>{twin.streamLamina}</b>. Values are held back rather than shown under
                    the wrong model. Re-reading the structure…
                  </p>
                ) : twin.closeReason ? (
                  <p className="font-mono text-[11px] readout text-crimson-container max-w-[380px]">
                    Stream refused: {twin.closeReason}
                  </p>
                ) : (
                  <p className="font-mono text-[12px] readout uppercase text-ink/50 animate-pulse">
                    Waiting for twin data…
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Where the stage got its numbers, whenever the stage is showing. */}
          {form === 'animation' && stage && (
            <div className="shrink-0 mt-3">
              <ProvenanceStrip stage={stage} sources={index.sources} />
            </div>
          )}
        </Panel>

        {/* 3 — Outcomes */}
        <Panel
          className={`row-span-2 min-h-0 flex flex-col !p-5 ${dim}`}
          eyebrow="3 · Outcomes"
          title="Against the targets the model declares"
        >
          <OutcomeTiles index={index} latest={latest} />
        </Panel>

        {/* 4 — Over time */}
        <Panel
          className={`!p-5 ${dim}`}
          eyebrow="4 · Over time"
          title="Distance from the targets, with and without the feedback loop"
        >
          <ConvergenceChart ticks={twin.mismatch ? [] : ticks} height={150} />
        </Panel>
      </div>

      {/* ── Status line ─────────────────────────────────────────────────── */}
      <footer className="shrink-0 flex items-center gap-3 px-margin py-2.5 border-t border-white/10 bg-surface-lowest/80">
        <span className="font-mono text-[11px] readout text-oxy-container">{'>'}</span>
        <span className="font-mono text-[11px] readout text-ink/55 truncate">
          {index.sensors.length} inputs · {index.functions.length} functions ·{' '}
          {index.computed.length} computed · {index.outcomes.length} outcomes, all read from{' '}
          {index.schema.lamina_id}
        </span>
        <span className="ml-auto flex items-center gap-3 font-mono text-[10px] readout uppercase text-ink/30 shrink-0">
          Other screens
          {(['twin', 'body', 'stream', 'analysis'] as OtherScreen[]).map((s) => (
            <button key={s} onClick={() => onOpen(s)} className="text-ink/45 hover:text-ink">
              {s}
            </button>
          ))}
        </span>
      </footer>

      {inspecting && (
        <InspectDrawer
          index={index}
          ticks={twin.mismatch ? [] : ticks}
          latest={latest}
          onClose={() => setInspecting(false)}
        />
      )}
    </div>
  )
}

function HeaderButton({
  children,
  onClick,
  accent,
}: {
  children: React.ReactNode
  onClick: () => void
  accent?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-el border-2 px-3 py-1.5 font-mono text-[11px] font-bold readout uppercase transition-all ${
        accent
          ? 'border-oxy-container/60 text-oxy hover:bg-oxy-container/15 hover:shadow-oxybloom'
          : 'border-white/15 text-ink/60 hover:text-ink hover:border-white/30'
      }`}
    >
      {children}
    </button>
  )
}
