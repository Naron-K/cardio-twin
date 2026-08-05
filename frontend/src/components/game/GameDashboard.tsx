/**
 * GameDashboard — the 2D interactive-game view of the circulatory twin.
 *
 * Same data path as the streaming dashboard (useCardioStream → /ws/feedback →
 * the real lamina + adaptive feedback loop); what changes is the framing: the
 * player gets three physiological "commands" instead of ten sliders, and a
 * mission that only completes if the twin actually settles inside a target
 * band.  Sliders are still one click away in the streaming view.
 *
 * Layout follows DESIGN.md: 32px page margin, 24px gutter, card-centric with
 * 24px safe areas, tonal layers + glows instead of drop shadows.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useCardioStream } from '../../hooks/useCardioStream'
import type { StreamTick } from '../../hooks/useCardioStream'
import { fetchSchema, uploadXML } from '../../utils/api'
import type { Schema } from '../../utils/api'
import { PixelHeart } from './PixelHeart'
import { AnatomicalHeart } from './AnatomicalHeart'
import { EcgStrip } from './EcgStrip'
import { Panel, Chip, VitalCard, CommandButton } from './ui'
import { COMMANDS, MISSIONS, VITAL_RANGE } from '../../game/protocol'
import type { Command } from '../../game/protocol'
import { CHAMBER_LABEL, CHAMBER_SWATCH } from '../../game/heartSprite'
import type { Chamber } from '../../game/heartSprite'

interface Props {
  onBack: () => void
}

type Tab = 'diagnostics' | 'telemetry' | 'log'
type LogTone = 'info' | 'good' | 'warn' | 'cmd'
interface LogEntry {
  id: number
  at: string
  text: string
  tone: LogTone
}

const LEGEND: Chamber[] = ['RA', 'RV', 'PA', 'LA', 'LV', 'AO']

type HeartModel = 'anatomical' | 'pixel'
const HEART_MODELS: { id: HeartModel; label: string }[] = [
  { id: 'anatomical', label: 'Anatomical' },
  { id: 'pixel', label: '16-bit' },
]

const TABS: { id: Tab; label: string }[] = [
  { id: 'diagnostics', label: 'Diagnostics' },
  { id: 'telemetry', label: 'Telemetry' },
  { id: 'log', label: 'Mission Log' },
]

export function GameDashboard({ onBack }: Props) {
  const { ticks, status, sendControl } = useCardioStream({ tickMs: 100, bufferSize: 60 })
  const latest: StreamTick | null = ticks.length > 0 ? ticks[ticks.length - 1] : null

  const [schema, setSchema] = useState<Schema | null>(null)
  const [values, setValues] = useState<Record<string, number>>({})
  const [paused, setPaused] = useState(false)
  const [tab, setTab] = useState<Tab>('diagnostics')
  const [focus, setFocus] = useState<Chamber | null>(null)
  const [heartModel, setHeartModel] = useState<HeartModel>('anatomical')

  const [missionIdx, setMissionIdx] = useState(0)
  const [progress, setProgress] = useState(0)
  const [score, setScore] = useState(0)
  const [cleared, setCleared] = useState(0)
  const [log, setLog] = useState<LogEntry[]>([])
  /** Command id → milliseconds of cooldown left; ticked down by the game loop. */
  const [cooldowns, setCooldowns] = useState<Record<string, number>>({})
  /** Seconds since the run started — counted by the game loop, not Date.now(). */
  const [elapsed, setElapsed] = useState(0)
  const logId = useRef(0)
  const latestRef = useRef<StreamTick | null>(null)
  const valuesRef = useRef<Record<string, number>>({})
  const pausedRef = useRef(false)
  const missionIdxRef = useRef(0)
  const progressRef = useRef(0)
  const seeded = useRef(false)
  const prevTags = useRef<string>('')
  const prevDiverged = useRef(false)

  // Mirrors for the 10 Hz mission loop and the keyboard handler, which read
  // the newest values without being re-created on every tick.
  useEffect(() => {
    latestRef.current = latest
  }, [latest])
  useEffect(() => {
    valuesRef.current = values
  }, [values])
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  const mission = MISSIONS[missionIdx]

  const pushLog = useCallback((text: string, tone: LogTone = 'info') => {
    const at = new Date().toLocaleTimeString('en-GB', { hour12: false })
    setLog((prev) => [{ id: logId.current++, at, text, tone }, ...prev].slice(0, 60))
  }, [])

  // ── Schema + initial sensor mirror ────────────────────────────────────────
  // Sensors that appear in the stream (HR/SBP/DBP) are seeded from the first
  // tick so a command nudges the value the backend actually holds; the rest
  // fall back to physiological midpoints, same as the streaming view.
  useEffect(() => {
    fetchSchema()
      .then((s) => {
        setSchema(s)
        const defaults: Record<string, number> = {}
        for (const [id, attr] of Object.entries(s.attributes)) {
          if (attr.source === 'SENSOR') defaults[id] = (attr.physio_min + attr.physio_max) / 2
        }
        setValues(defaults)
      })
      .catch(() => pushLog('Schema failed to load — is the backend up on port 8000?', 'warn'))
  }, [pushLog])

  // Load a scenario preset and push every sensor to the backend at once.
  // The game always starts from `normal` so mission 1 begins from a healthy
  // baseline rather than whatever the session happened to be left at.
  const applyBaseline = useCallback(async () => {
    const res = await fetch('/presets/normal.xml')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const file = new File([await res.text()], 'normal.xml', { type: 'text/xml' })
    const results = await uploadXML(file)
    const next: Record<string, number> = {}
    for (const [id, attr] of Object.entries(results.sensors)) next[id] = attr.value
    setValues(next)
    for (const [id, value] of Object.entries(next)) {
      sendControl({ type: 'set_sensor', id, value })
    }
  }, [sendControl])

  // Wait for the first tick — the WebSocket has to be open before set_sensor
  // messages go anywhere.  This effect exists precisely to push state *out* to
  // an external system (the socket); the local mirror it also sets is a
  // consequence of that, so the set-state-in-effect rule doesn't apply.
  useEffect(() => {
    if (seeded.current || !latest || !schema) return
    seeded.current = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    applyBaseline()
      .then(() => pushLog('Twin connected — "normal" baseline loaded', 'good'))
      .catch(() => pushLog('Baseline preset failed to load — keeping current state', 'warn'))
  }, [latest, schema, applyBaseline, pushLog])

  // ── Game loop — runtime clock, command cooldowns, mission progress ────────
  useEffect(() => {
    const DT = 0.1
    const t = setInterval(() => {
      setElapsed((e) => e + DT)
      setCooldowns((prev) => {
        const ids = Object.keys(prev)
        if (ids.length === 0) return prev
        const next: Record<string, number> = {}
        for (const id of ids) {
          const left = prev[id] - DT * 1000
          if (left > 0) next[id] = left
        }
        return next
      })

      const tick = latestRef.current
      if (!tick || pausedRef.current) return
      const m = MISSIONS[missionIdxRef.current]
      const v = m.metric === 'map' ? tick.map : m.metric === 'co' ? tick.co : tick.hr
      const inBand = v >= m.lo && v <= m.hi

      if (inBand) setScore((s) => s + 1)

      // In-band fills; out-of-band drains at half speed so a brief excursion
      // costs progress without wiping the run.
      const next = progressRef.current + (inBand ? DT / m.holdSec : -DT / (m.holdSec * 2))

      if (next >= 1) {
        progressRef.current = 0
        setProgress(0)
        setScore((s) => s + m.reward)
        setCleared((c) => c + 1)
        pushLog(`✔ Objective cleared: ${m.brief} (+${m.reward})`, 'good')
        missionIdxRef.current = (missionIdxRef.current + 1) % MISSIONS.length
        setMissionIdx(missionIdxRef.current)
      } else {
        progressRef.current = Math.max(0, Math.min(1, next))
        setProgress(progressRef.current)
      }
    }, 100)
    return () => clearInterval(t)
  }, [pushLog])

  // ── Surface the model's own feedback activity in the terminal ─────────────
  useEffect(() => {
    if (!latest) return
    const key = latest.tagsEmitted.join(',')
    if (key && key !== prevTags.current) {
      pushLog(`⟳ Body self-correcting — tags: ${latest.tagsEmitted.join(', ')}`, 'info')
    }
    prevTags.current = key
    // Only log the divergence edge — the flag stays true for many ticks.
    if (latest.diverged && !prevDiverged.current) {
      pushLog('⚠ Feedback loop diverged — circuit breaker tripped', 'warn')
    }
    prevDiverged.current = latest.diverged
  }, [latest, pushLog])

  // ── Commands ──────────────────────────────────────────────────────────────
  const fire = useCallback(
    (cmd: Command) => {
      if (!schema) return
      if ((cooldowns[cmd.id] ?? 0) > 0) return

      const next = { ...valuesRef.current }
      const applied: string[] = []
      for (const [id, frac] of Object.entries(cmd.deltas)) {
        const attr = schema.attributes[id]
        if (!attr) continue
        const span = attr.physio_max - attr.physio_min
        const cur = next[id] ?? (attr.physio_min + attr.physio_max) / 2
        const v = clamp(cur + frac * span, attr.physio_min, attr.physio_max)
        next[id] = v
        sendControl({ type: 'set_sensor', id, value: v })
        applied.push(`${id}→${v.toFixed(2)}`)
      }
      setValues(next)
      setCooldowns((prev) => ({ ...prev, [cmd.id]: cmd.cooldownMs }))
      pushLog(`▶ ${cmd.log} [${applied.join(' ')}]`, 'cmd')
    },
    [schema, cooldowns, sendControl, pushLog]
  )

  const togglePause = useCallback(() => {
    const next = !pausedRef.current
    setPaused(next)
    sendControl({ type: next ? 'pause' : 'resume' })
    pushLog(next ? '⏸ Simulation paused' : '▶ Simulation resumed', 'info')
  }, [sendControl, pushLog])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      const cmd = COMMANDS.find((c) => c.hotkey === e.key)
      if (cmd) {
        e.preventDefault()
        fire(cmd)
        return
      }
      if (e.code === 'Space') {
        e.preventDefault()
        togglePause()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fire, togglePause])

  const handleReset = useCallback(() => {
    // Backend reset() only wipes the feedback kernel — it leaves the sensors
    // where the player pushed them — so replay the baseline preset too.
    sendControl({ type: 'reset' })
    if (paused) sendControl({ type: 'resume' })
    setPaused(false)
    setCooldowns({})
    progressRef.current = 0
    setProgress(0)
    setScore(0)
    setCleared(0)
    missionIdxRef.current = 0
    setMissionIdx(0)
    setElapsed(0)
    applyBaseline().catch(() => pushLog('Baseline preset failed to reload', 'warn'))
    pushLog('↺ Session reset — twin returned to baseline', 'info')
  }, [sendControl, applyBaseline, paused, pushLog])

  // ── Derived vitals ────────────────────────────────────────────────────────
  const hr = latest?.hr ?? 72
  const map = latest?.map ?? 85
  const co = latest?.co ?? 5
  const sv = latest?.sv ?? 70
  const sbp = latest?.sbp ?? 120
  const dbp = latest?.dbp ?? 80

  const missionValue = mission.metric === 'map' ? map : mission.metric === 'co' ? co : hr
  const inBand = latest !== null && missionValue >= mission.lo && missionValue <= mission.hi
  const alert =
    latest !== null &&
    (map < VITAL_RANGE.map.safeLo ||
      map > VITAL_RANGE.map.safeHi ||
      hr > VITAL_RANGE.hr.safeHi ||
      hr < VITAL_RANGE.hr.safeLo)

  const runtime = fmtClock(elapsed)

  return (
    <div className="h-screen flex flex-col bg-surface text-ink font-body overflow-hidden">
      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <header className="shrink-0 flex items-center gap-4 px-margin py-3 border-b border-white/10 bg-surface-low/70 backdrop-blur-lg">
        <button
          onClick={onBack}
          className="font-mono text-[11px] readout uppercase text-ink/45 hover:text-ink transition-colors"
        >
          ← Analysis
        </button>

        <div className="flex items-center gap-2.5 pl-3 border-l border-white/10">
          <MiniHeart beating={!paused && status === 'open'} />
          <span className="font-display text-lg font-extrabold tracking-tight text-crimson-container">
            CARDIO_TWIN
          </span>
          <span className="font-mono text-[10px] readout text-ink/30">2D&nbsp;SIM v1.0</span>
        </div>

        <Chip tone={status === 'open' ? 'oxy' : 'crimson'} dot pulse={status !== 'open'}>
          {status === 'open' ? 'Live' : status === 'connecting' ? 'Reconnecting' : 'Offline'}
        </Chip>

        <div className="ml-auto flex items-center gap-3">
          <Readout label="Runtime" value={runtime} />
          <Readout label="Score" value={String(score)} accent />
          <Readout label="Cleared" value={String(cleared)} />
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
            ↺ Reset
          </button>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-[268px_minmax(0,1fr)_324px] gap-gutter px-margin py-gutter">
        {/* Left — operator + vitals */}
        <aside className="min-h-0 overflow-y-auto flex flex-col gap-gutter pr-1">
          <Panel className="!p-5">
            <p className="font-display text-base font-semibold text-ink leading-tight">PILOT_01</p>
            <p className="font-mono text-[11px] readout text-ink-variant/70 mt-0.5">
              Circulatory Lead
            </p>
            <nav className="mt-4 flex flex-col gap-1">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`text-left rounded-el px-3 py-2 font-mono text-[11px] font-bold readout
                              uppercase transition-all border-l-2 ${
                                tab === t.id
                                  ? 'bg-crimson-container/12 border-crimson-container text-crimson'
                                  : 'border-transparent text-ink/40 hover:text-ink/75 hover:bg-white/5'
                              }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
          </Panel>

          <div className="flex flex-col gap-3">
            <VitalCard
              sensorId="SNS-01"
              label="BPM"
              value={hr}
              unit="bpm"
              {...VITAL_RANGE.hr}
            />
            <VitalCard
              sensorId="SNS-02"
              label="BP"
              value={sbp}
              unit="mmHg"
              sub={`${sbp.toFixed(0)} / ${dbp.toFixed(0)} systolic / diastolic`}
              {...VITAL_RANGE.sbp}
            />
            <VitalCard
              sensorId="CMP-01"
              label="MAP"
              value={map}
              unit="mmHg"
              {...VITAL_RANGE.map}
            />
            <VitalCard
              sensorId="CMP-02"
              label="Cardiac output"
              value={co}
              unit="L/min"
              decimals={2}
              {...VITAL_RANGE.co}
            />
          </div>
        </aside>

        {/* Centre — the stage */}
        <main className="min-h-0 flex flex-col gap-gutter">
          {/* No scanlines here on purpose — a 3px scanline period fights the
              sprite's ~14px pixel grid and reads as banding across the
              chambers.  The ECG strip keeps them. */}
          <div className="relative flex-1 min-h-0 rounded-card border border-white/10 shadow-inset1
                          bg-surface-lowest stage-grid overflow-hidden">
            {/* HUD overlays */}
            <div className="absolute top-4 left-4 z-10">
              <Chip tone={paused ? 'warn' : 'oxy'} dot pulse={!paused}>
                {paused ? 'Unit_paused' : 'Unit_active'}
              </Chip>
            </div>
            <div className="absolute top-4 right-4 z-10">
              <Chip tone={alert ? 'crimson' : 'neutral'}>
                Sim_mode: {alert ? 'Unstable' : 'Standard'}
              </Chip>
            </div>

            {/* Heart-model switch — the anatomical cross-section and the 16-bit
                sprite are driven by exactly the same bindings, so this is a
                straight A/B of the artwork. */}
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex rounded-full
                            border border-white/10 bg-surface-lowest/80 p-0.5 backdrop-blur-sm">
              {HEART_MODELS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setHeartModel(m.id)}
                  className={`rounded-full px-2.5 py-0.5 font-mono text-[10px] readout uppercase
                              transition-colors ${
                                heartModel === m.id
                                  ? 'bg-white/10 text-ink'
                                  : 'text-ink/40 hover:text-ink/70'
                              }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* The heart */}
            <div className="absolute inset-0 flex items-center justify-center p-10">
              <div
                className={`w-full h-full max-w-[440px] max-h-[440px] transition-[filter] duration-500 ${
                  heartModel === 'pixel' ? 'pixelated' : ''
                } ${alert ? 'drop-shadow-[0_0_28px_rgba(255,82,95,0.45)]' : ''}`}
              >
                {heartModel === 'pixel' ? (
                  <PixelHeart hr={hr} co={co} sv={sv} alert={alert} paused={paused} focus={focus} />
                ) : (
                  <AnatomicalHeart
                    hr={hr}
                    co={co}
                    sv={sv}
                    alert={alert}
                    paused={paused}
                    focus={focus}
                  />
                )}
              </div>
            </div>

            {/* Live corner readouts, like the reference HUD */}
            <div className="absolute bottom-4 left-4 z-10 font-mono text-[11px] readout space-y-0.5">
              <p className="text-ink/35">SV&nbsp;&nbsp;<span className="text-ink">{sv.toFixed(1)}</span> mL</p>
              <p className="text-ink/35">Q&nbsp;&nbsp;&nbsp;<span className="text-ink">{(latest?.q ?? 0).toFixed(2)}</span> L/min</p>
              <p className="text-ink/35">‖X″‖&nbsp;<span className="text-ink">{(latest?.feedback_norm ?? 0).toFixed(4)}</span></p>
            </div>

            {/* Chamber legend — hover to isolate a chamber in the sprite */}
            <div className="absolute bottom-4 right-4 z-10 flex flex-col items-end gap-1">
              {LEGEND.map((c) => (
                <button
                  key={c}
                  onMouseEnter={() => setFocus(c)}
                  onMouseLeave={() => setFocus(null)}
                  className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 transition-colors ${
                    focus === c ? 'bg-white/10' : 'hover:bg-white/5'
                  }`}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-[2px]"
                    style={{ background: CHAMBER_SWATCH[c] }}
                  />
                  <span className="font-mono text-[10px] readout text-ink/50">
                    {CHAMBER_LABEL[c]}
                  </span>
                </button>
              ))}
            </div>

            {!latest && (
              <div className="absolute inset-0 z-20 flex items-center justify-center bg-surface/70 backdrop-blur-sm">
                <p className="font-mono text-[12px] readout uppercase text-ink/50 animate-pulse">
                  Waiting for twin data…
                </p>
              </div>
            )}
          </div>

          {/* Tab panel under the stage */}
          <Panel
            className="shrink-0"
            eyebrow={tab === 'diagnostics' ? 'ECG · lead II' : tab === 'telemetry' ? 'Model readout' : 'Event stream'}
            title={
              tab === 'diagnostics'
                ? 'Electrocardiogram'
                : tab === 'telemetry'
                  ? 'Model parameters'
                  : 'Mission log'
            }
            action={
              tab === 'diagnostics' ? (
                <span className="font-mono text-[10px] readout text-warn/70 text-right leading-snug max-w-[230px]">
                  Waveform synthesised from HR — the lamina model emits no waveform
                </span>
              ) : null
            }
          >
            {tab === 'diagnostics' && <EcgStrip hr={hr} paused={paused} alert={alert} height={96} />}

            {tab === 'telemetry' && (
              <div className="grid grid-cols-4 gap-3">
                <Metric label="HR" value={hr.toFixed(0)} unit="bpm" />
                <Metric label="SBP" value={sbp.toFixed(0)} unit="mmHg" />
                <Metric label="DBP" value={dbp.toFixed(0)} unit="mmHg" />
                <Metric label="MAP" value={map.toFixed(1)} unit="mmHg" />
                <Metric label="SV" value={sv.toFixed(1)} unit="mL" />
                <Metric label="CO" value={co.toFixed(2)} unit="L/min" />
                <Metric label="Q" value={(latest?.q ?? 0).toFixed(2)} unit="L/min" />
                <Metric label="Cycle" value={String(latest?.tick ?? 0)} unit="tick" />
                <Metric label="CO X″" value={(latest?.co_feedback ?? 0).toFixed(4)} unit="L/min" />
                <Metric label="SV X″" value={(latest?.sv_feedback ?? 0).toFixed(4)} unit="mL" />
                <Metric label="‖X″‖" value={(latest?.feedback_norm ?? 0).toFixed(4)} unit="" />
                <Metric
                  label="Tags"
                  value={String(latest?.tagsEmitted.length ?? 0)}
                  unit="fired"
                />
              </div>
            )}

            {tab === 'log' && (
              <div className="h-[128px] overflow-y-auto font-mono text-[11px] readout space-y-1 pr-1">
                {log.length === 0 && <p className="text-ink/30">No events yet.</p>}
                {log.map((e) => (
                  <p key={e.id} className="animate-log-in">
                    <span className="text-ink/25">{e.at}</span>{' '}
                    <span className={LOG_TONE[e.tone]}>{e.text}</span>
                  </p>
                ))}
              </div>
            )}
          </Panel>
        </main>

        {/* Right — command uplink */}
        <aside className="min-h-0 overflow-y-auto flex flex-col gap-gutter pl-1">
          <Panel interactive eyebrow="Uplink · 3 slots" title="Command Uplink">
            <div className="flex flex-col gap-2.5">
              {COMMANDS.map((cmd) => {
                const remaining = cooldowns[cmd.id] ?? 0
                return (
                  <CommandButton
                    key={cmd.id}
                    label={cmd.label}
                    blurb={cmd.blurb}
                    hotkey={cmd.hotkey}
                    icon={<CommandIcon id={cmd.id} />}
                    variant={cmd.variant}
                    cooldown={remaining / cmd.cooldownMs}
                    disabled={!schema || paused}
                    onFire={() => fire(cmd)}
                  />
                )
              })}
            </div>
            <p className="mt-3 font-mono text-[10px] readout text-ink/30 leading-relaxed">
              Every command writes straight to a lamina sensor over the WebSocket.
              The two-timescale feedback loop pulls the readouts back toward their
              targets on its own — you nudge the system, you don't force the result.
            </p>
          </Panel>

          <Panel
            eyebrow={`Objective ${missionIdx + 1}/${MISSIONS.length}`}
            title="Current objective"
            action={
              <Chip tone={inBand ? 'oxy' : 'warn'} dot pulse={inBand}>
                {inBand ? 'In band' : 'Drifting'}
              </Chip>
            }
          >
            <p className="text-[14px] leading-relaxed text-ink/85">{mission.brief}</p>

            <div className="mt-4 flex items-baseline gap-2">
              <span
                className={`font-mono text-[26px] font-bold leading-none tabular-nums ${
                  inBand ? 'text-oxy-container' : 'text-crimson-container'
                }`}
              >
                {missionValue.toFixed(mission.metric === 'co' ? 2 : 0)}
              </span>
              <span className="font-mono text-[11px] readout text-ink/40">{mission.unit}</span>
              <span className="ml-auto font-mono text-[11px] readout text-ink/40">
                target {mission.lo}–{mission.hi}
              </span>
            </div>

            <div className="mt-3 h-3 rounded-full bg-surface-lowest overflow-hidden">
              <div
                className={`h-full rounded-full transition-[width] duration-100 ${
                  inBand ? 'bg-oxy-container shadow-oxybloom-sm' : 'bg-warn-strong'
                }`}
                style={{ width: `${(progress * 100).toFixed(1)}%` }}
              />
            </div>
            <p className="mt-1.5 font-mono text-[10px] readout text-ink/35">
              hold steady for {(mission.holdSec * (1 - progress)).toFixed(1)}s more · +{mission.reward} pts
            </p>
          </Panel>
        </aside>
      </div>

      {/* ── Terminal status line ────────────────────────────────────────── */}
      <footer className="shrink-0 flex items-center gap-3 px-margin py-3 border-t border-white/10 bg-surface-lowest/80">
        <span className="font-mono text-[11px] readout text-oxy-container">{'>'}</span>
        <span className={`font-mono text-[11px] readout truncate ${log[0] ? LOG_TONE[log[0].tone] : 'text-ink/40'}`}>
          {log[0]?.text ?? 'System stable… awaiting operator input'}
        </span>
        <span className="w-1.5 h-3.5 bg-oxy-container/70 animate-pulse shrink-0" />
        <span className="ml-auto font-mono text-[10px] readout text-ink/25 shrink-0">
          [1] [2] [3] commands · [Space] pause
        </span>
      </footer>
    </div>
  )
}

// ── Small pieces ──────────────────────────────────────────────────────────────

const LOG_TONE: Record<LogTone, string> = {
  info: 'text-ink/65',
  good: 'text-oxy-container',
  warn: 'text-crimson-container',
  cmd:  'text-ink-variant',
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

function Metric({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="rounded-el border border-white/10 bg-surface-lowest/60 px-3 py-2">
      <p className="font-mono text-[10px] readout uppercase text-ink/35">{label}</p>
      <p className="font-mono text-[15px] font-bold tabular-nums text-ink mt-0.5">
        {value}
        <span className="text-[10px] font-normal text-ink/35 ml-1">{unit}</span>
      </p>
    </div>
  )
}

function CommandIcon({ id }: { id: string }) {
  const common = { width: 18, height: 18, fill: 'none', stroke: 'currentColor', strokeWidth: 2 }
  if (id === 'adrenaline') {
    return (
      <svg viewBox="0 0 24 24" {...common} strokeLinejoin="round">
        <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z" fill="currentColor" stroke="none" />
      </svg>
    )
  }
  if (id === 'exercise') {
    return (
      <svg viewBox="0 0 24 24" {...common} strokeLinecap="round">
        <path d="M4 9v6M8 6v12M16 6v12M20 9v6M8 12h8" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" {...common} strokeLinecap="round">
      <path d="M3 8h10a3 3 0 1 0-3-3M3 16h12a3 3 0 1 1-3 3M3 12h17" />
    </svg>
  )
}

/** Tiny 7×6 pixel heart for the wordmark. */
function MiniHeart({ beating }: { beating: boolean }) {
  return (
    <svg viewBox="0 0 7 6" width={18} height={16} shapeRendering="crispEdges" className={beating ? 'animate-pulse' : ''}>
      {[
        '.X...X.',
        'XXX.XXX',
        'XXXXXXX',
        '.XXXXX.',
        '..XXX..',
        '...X...',
      ].map((row, y) =>
        row.split('').map((ch, x) =>
          ch === 'X' ? (
            <rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill="#ff525f" />
          ) : null
        )
      )}
    </svg>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v
}

function fmtClock(seconds: number) {
  const total = Math.max(0, Math.floor(seconds))
  const m = String(Math.floor(total / 60)).padStart(2, '0')
  const s = String(total % 60).padStart(2, '0')
  return `${m}:${s}`
}
