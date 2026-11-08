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
 * The rules that keep it honest live in useLaminaTwin: structure from the
 * schema, values from the tick, nothing from a constant in a component; the
 * stage is handed computed values only; a tick from another lamina is never
 * drawn under this one's labels; a dead socket says so.
 *
 * What happened to the stream is said out loud through useStatusNotices, a
 * screen nobody has touched lets the stream go and reopens it on the next
 * touch (useIdle, with `?idle=` in the URL), a hidden page does the same after
 * half a minute (usePageViewing), and the long press a finger
 * cannot hover shows the `title` text through TouchTooltip.
 */
import { useEffect, useRef, useState } from 'react'
import { useLaminaTwin } from '../../hooks/useLaminaTwin'
import { STREAM_LIMIT_CLOSE } from '../../hooks/useCardioStream'
import { idleMinutesFromUrl, useIdle } from '../../hooks/useIdle'
import { useWakeLock } from '../../hooks/useWakeLock'
import { usePageViewing } from '../../hooks/usePageViewing'
import { useStatusNotices, useStreamNoticeHandlers } from '../../hooks/useStatusNotices'
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
import type { TwinForm } from './forms'
import { NoticeContext, useNotices } from '../notices/useNotices'
import { NoticeStack } from '../notices/NoticeStack'
import { TouchTooltip } from '../TouchTooltip'

interface Props {
  /** Lamina id to open, or null for whatever the backend defaults to. */
  lamina: string | null
  onLamina: (id: string) => void
  form: TwinForm
  onForm: (form: TwinForm) => void
}

export function Dashboard({ lamina, onLamina, form, onForm }: Props) {
  const notices = useNotices()
  const streamHandlers = useStreamNoticeHandlers(notices)
  const [idleMinutes] = useState(() => idleMinutesFromUrl())
  const { idle, wake } = useIdle(idleMinutes)
  useWakeLock(!idle)
  const viewing = usePageViewing()

  const twin = useLaminaTwin({
    lamina,
    onLamina,
    enabled: !idle && viewing,
    onNotice: streamHandlers.onNotice,
    onReconnect: streamHandlers.onReconnect,
  })
  const { index, latest, ticks, status, stale, staleAge, stage, artwork, paused } = twin

  // The reset action is kept in a ref because confirmReset is the other value
  // from this same call: the notice hook needs resetLoop, and resetLoop must
  // also confirm that reset happened.
  const confirmResetRef = useRef<() => void>(() => {})
  const { confirmReset } = useStatusNotices(notices, {
    status: twin.status,
    everOpened: twin.everOpened,
    attempts: twin.attempts,
    retryAt: twin.retryAt,
    online: twin.online,
    closeReason: twin.closeReason,
    closeCode: twin.closeCode,
    retryNow: twin.retryNow,
    paused: twin.paused,
    resume: twin.togglePause,
    diverged: Boolean(twin.latest?.diverged),
    resetLoop: () => {
      twin.reset()
      confirmResetRef.current()
    },
  })
  useEffect(() => {
    confirmResetRef.current = confirmReset
  }, [confirmReset])

  const [inspecting, setInspecting] = useState(false)

  // A countdown clock that runs only while the schema retry has a deadline.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (twin.schemaRetryAt === null) return
    const id = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [twin.schemaRetryAt])

  // The loading screen is already up at first paint, so this waits the same
  // four seconds from when it first showed.
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const id = setTimeout(() => setSlow(true), 4_000)
    return () => clearTimeout(id)
  }, [])

  let content: React.ReactNode

  if (twin.schemaError) {
    const retryAt = twin.schemaRetryAt
    const seconds = retryAt !== null ? Math.max(0, Math.ceil((retryAt - now) / 1_000)) : null
    const notFound = twin.schemaAttempts === 0 || twin.schemaError.startsWith('No lamina')

    content = (
      <div className="h-app flex flex-col items-center justify-center gap-4 px-6 bg-surface text-ink">
        {notFound ? (
          <>
            <p className="font-mono text-[12px] readout text-crimson-container">{twin.schemaError}</p>
            <button
              onClick={() => window.location.reload()}
              className="font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink"
            >
              ↻ Reload
            </button>
          </>
        ) : (
          <>
            <p className="font-mono text-[12px] readout text-crimson-container">Can't load the model</p>
            <p className="font-body text-[13px] text-ink/60 max-w-md text-center leading-relaxed">
              {seconds !== null
                ? `The server did not answer. If it is starting up, this can take up to a minute — trying again in ${seconds}s.`
                : 'The server did not answer. Trying again…'}
            </p>
            <button
              onClick={twin.retrySchema}
              className="min-h-[44px] px-5 rounded-full border-2 border-white/15 font-mono text-[11px] readout uppercase text-ink/60 hover:text-ink"
            >
              ↻ Retry now
            </button>
          </>
        )}
      </div>
    )
  } else if (!index) {
    content = (
      <div className="h-app flex flex-col items-center justify-center px-6 bg-surface">
        <p className="font-mono text-[12px] readout uppercase text-ink/40 animate-pulse">
          Reading the lamina…
        </p>
        {slow && (
          <p className="mt-3 font-body text-[13px] text-ink/45 text-center max-w-md">
            Waiting for the server. If it is starting up, this can take up to a minute.
          </p>
        )}
      </div>
    )
  } else {
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
    const dataLimit = twin.closeCode === STREAM_LIMIT_CLOSE
    const statusChip =
      dataLimit
        ? { tone: 'warn' as const, pulse: false, label: 'Data limit reached' }
        : status === 'open'
        ? { tone: 'oxy' as const, pulse: false, label: 'Live' }
        : status === 'suspended'
          ? { tone: 'neutral' as const, pulse: false, label: 'Paused · idle' }
          : status === 'connecting'
            ? {
                tone: 'crimson' as const,
                pulse: true,
                label: twin.everOpened ? 'Reconnecting' : 'Connecting',
              }
            : { tone: 'crimson' as const, pulse: true, label: 'Offline' }

    content = (
      <div className="min-h-app fit:h-app flex flex-col bg-surface text-ink font-body fit:overflow-hidden">
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <header className="shrink-0 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 wide:px-margin py-3 border-b border-white/10 bg-surface-low/70 backdrop-blur-lg">
          <span className="font-display text-lg font-extrabold tracking-tight text-ink">
            CardioTwin
          </span>
          <div className="flex items-baseline gap-2.5 pl-3 border-l border-white/10 min-w-0">
            <LaminaPicker laminae={twin.laminae} current={index.schema.lamina_id} onPick={onLamina} />
            <span className="phone:hidden font-mono text-[10px] readout text-ink/30 truncate">
              {index.schema.lamina_id} · level {index.schema.lamina_level}
            </span>
          </div>

          <Chip tone={statusChip.tone} dot pulse={statusChip.pulse}>
            {statusChip.label}
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
            <HeaderButton
              onClick={() => {
                twin.reset()
                confirmReset()
              }}
            >
              ↺ Reset loop
            </HeaderButton>
            <HeaderButton onClick={() => setInspecting(true)}>Inspect ▸</HeaderButton>
          </div>
        </header>

        {/* ── Body: sources | twin | outcomes, with time underneath ────────
             The tier comes from display.ts. Wide: three columns, as designed.
             Tablet: inputs beside one scrolling column of twin, outcomes and
             time, so no panel is squeezed below what it needs. Phone: one
             column, and the page scrolls. */}
        <div
          className="grid gap-4 p-4 fit:flex-1 fit:min-h-0
                     tablet:grid-cols-[minmax(250px,300px)_minmax(0,1fr)] tablet:grid-rows-[minmax(0,1fr)]
                     wide:gap-gutter wide:px-margin wide:py-gutter
                     wide:grid-cols-[300px_minmax(0,1fr)_360px] wide:grid-rows-[minmax(0,1fr)_auto]"
        >
          {/* 1 — Data sources */}
          <Panel
            className="wide:row-span-2 fit:min-h-0 fit:overflow-y-auto !p-5"
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

          <div className="flex flex-col gap-4 tablet:min-h-0 tablet:overflow-y-auto tablet:pr-1 wide:contents">
          {/* 2 — Digital twin */}
          <Panel
            className="shrink-0 flex flex-col !p-5 h-[420px]
                       tablet:h-[clamp(360px,calc(var(--app-h)-180px),620px)]
                       wide:h-auto wide:min-h-0 wide:shrink"
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
                      {dataLimit ? 'Live data is off:' : 'Stream refused:'} {twin.closeReason}
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
            className={`shrink-0 wide:shrink wide:row-span-2 wide:min-h-0 flex flex-col !p-5 ${dim}`}
            eyebrow="3 · Outcomes"
            title="Against the targets the model declares"
          >
            <OutcomeTiles index={index} latest={latest} />
          </Panel>

          {/* 4 — Over time */}
          <Panel
            className={`shrink-0 !p-5 ${dim}`}
            eyebrow="4 · Over time"
            title="Distance from the targets, with and without the feedback loop"
          >
            <ConvergenceChart ticks={twin.mismatch ? [] : ticks} height={150} />
          </Panel>
          </div>
        </div>

        {/* ── Status line ─────────────────────────────────────────────────── */}
        <footer className="shrink-0 flex items-center gap-3 px-4 wide:px-margin py-2.5 border-t border-white/10 bg-surface-lowest/80">
          <span className="font-mono text-[11px] readout text-oxy-container">{'>'}</span>
          <span className="font-mono text-[11px] readout text-ink/55 truncate">
            {index.sensors.length} inputs · {index.functions.length} functions ·{' '}
            {index.computed.length} computed · {index.outcomes.length} outcomes, all read from{' '}
            {index.schema.lamina_id}
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

  return (
    <NoticeContext.Provider value={notices}>
      {content}
      {idle && <IdleOverlay idleMinutes={idleMinutes} wake={wake} />}
      <TouchTooltip />
      <NoticeStack api={notices} />
    </NoticeContext.Provider>
  )
}

/**
 * The dashboard lets go of a stream nobody is watching: a wall display left
 * untouched still costs a server session, and the host meters its bandwidth.
 * This says why the screen went quiet, and the next touch is the way back.
 */
function IdleOverlay({ idleMinutes, wake }: { idleMinutes: number; wake: () => void }) {
  return (
    <button
      type="button"
      onClick={wake}
      aria-label="Continue"
      className="fixed inset-0 z-40 flex items-center justify-center bg-surface/85 backdrop-blur-sm cursor-pointer"
    >
      <div className="max-w-xl rounded-card border-2 border-oxy-container/40 bg-surface-low/90 shadow-inset1 px-10 py-9 text-center">
        <p className="font-mono text-[11px] font-bold readout uppercase text-oxy/60">
          Paused to save bandwidth
        </p>
        <p className="font-display text-3xl font-extrabold text-ink mt-2">
          Touch anywhere to continue
        </p>
        <p className="mt-4 font-body text-[15px] leading-relaxed text-ink/65">
          No one has touched the screen for {idleMinutes} minute{idleMinutes === 1 ? '' : 's'}, so
          the live connection was closed. Touching reconnects it.
        </p>
      </div>
    </button>
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
