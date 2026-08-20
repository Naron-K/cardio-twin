/**
 * useCardioStream — Phase 3/4 WebSocket hook.
 *
 * Connects to /ws/feedback (proxied by Vite → backend), maintains a
 * ring-buffer of parsed tick data, and exposes a sendControl() helper
 * for setting sensors, pause/resume, and reset.
 *
 * Auto-reconnects with exponential backoff (1 s → 2 s → 4 s → 16 s max).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { pushRing } from '../utils/ringBuffer'

// ── Types ──────────────────────────────────────────────────────────────────────

/**
 * One outcome's before/after the feedback loop (from the backend
 * shadow-pass).  `before` is the value the chain would produce with
 * X''=0 everywhere; `after` is the current settled value.  Self-contained
 * (target/tolerance/physio range) so the panel needs nothing else.
 */
export interface BeforeAfter {
  attribute_id: string
  unit: string
  target: number
  tolerance: number
  physio_min: number
  physio_max: number
  before: number
  after: number
  x_pp: number          // value_feedback on this outcome's attribute (X'')
  within_after: boolean
}

/** One slow-loop adaptation record (only present on slow-loop ticks). */
export interface Adaptation {
  gain: number
  operating_point: number
  perf_ewma: number
  settled: boolean
  updates: number
}

/** One outcome as the model evaluated it this cycle, before the shadow pass. */
export interface OutcomeEvaluation {
  outcome_id: string
  attribute_id?: string
  target?: number
  actual?: number
  deviation?: number
  deviation_pct?: number
  within_tolerance?: boolean
  status?: string
}

/** One tick of streaming data extracted from a backend snapshot. */
export interface StreamTick {
  tick: number          // cycle counter from cycle_report.cycle
  /**
   * Every SENSOR attribute by id.  Raw input: this is the half of the snapshot
   * the stage is never handed.  It exists so a control rail can be generated
   * from the schema rather than from a list of ids typed into a component.
   */
  sensors: Record<string, number>
  // ── Named conveniences for the circulatory analysis views ────────
  // StreamingDashboard and the charts beside it are explicitly a
  // circulatory read-out and address these directly.  The 2D twin view
  // uses the maps above and below instead, and names no attribute at all.
  hr: number            // sensors.HR.value  (bpm)
  sbp: number           // sensors.SBP.value (mmHg)
  dbp: number           // sensors.DBP.value (mmHg)
  co: number            // computed.CO.value  (L/min, X' + X'')
  sv: number            // computed.SV.value  (mL)
  map: number           // computed.MAP.value (mmHg)
  q: number             // computed.Q.value   (L/min)
  /**
   * Every PRELIMINARY attribute by id — including ones with no named field
   * above, such as `T_cycle`, `T_sys` and `lambda`.  Consumers that must not
   * see raw data (the stage) take this and nothing else, so a new model
   * output reaches them without touching this hook.
   */
  computed: Record<string, number>
  // ── Feedback corrections ──────────────────────────────────────────
  /**
   * The X = X' + X'' split for every PRELIMINARY attribute, not just the two
   * that happened to get named fields.  `computed` above is X; these are the
   * two halves it was built from, so a panel can show what the loop is
   * holding on any attribute the model computes.
   */
  computedExternal: Record<string, number>   // X'
  computedFeedback: Record<string, number>   // X''
  co_feedback: number   // computed.CO.value_feedback  (X'')
  sv_feedback: number   // computed.SV.value_feedback  (X'')
  feedback_norm: number // top-level L2 norm of all value_feedback
  // ── Cycle report (the 7-step cycle's per-tick log, previously dropped) ─
  tagsEmitted: string[]               // tag ids that fired this cycle
  deltasPerAttr: Record<string, number> // signed X'' applied per attribute
  snapped: string[]                   // attrs dead-zone snapped to 0
  diverged: boolean                   // circuit breaker tripped
  adaptation: Record<string, Adaptation> // slow-loop records, keyed by outcome
  // ── Before vs after the loop (shadow-pass), keyed by outcome id ────
  beforeAfter: Record<string, BeforeAfter>
  // ── Composite vector space ────────────────────────────────────────
  /**
   * Per composite, its members' current normalised values, and the same
   * weighted by the composite's absorption vector.  The snapshot has carried
   * both since v1 and no view has ever drawn them: a composite is the address
   * a tag fans a correction into, so this is where the loop's arithmetic
   * actually lands.  Keyed by composite id, then attribute id.
   */
  vectors: Record<string, Record<string, number>>
  absorption: Record<string, Record<string, number>>
  /** The model's raw outcome evaluations, keyed by segment id. */
  outcomes: Record<string, OutcomeEvaluation[]>
  /** Gate failures the twin logged this cycle. */
  warnings: string[]
  /**
   * What is producing these readings.  Reported by the backend rather than
   * assumed here: today every reading on this socket is generated, and a
   * screen full of convincingly wobbling numbers should say so rather than
   * leave a viewer to work it out.
   */
  source: { kind: string; detail: string }
}

export type StreamStatus = 'connecting' | 'open' | 'closed'

// Control message shapes — mirrors the WebSocket protocol in main.py
export type ControlMsg =
  | { type: 'set_sensor'; id: string; value: number }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'reset' }

export interface UseCardioStreamOptions {
  /** Tick interval in ms (default 100 = 10 Hz). */
  tickMs?: number
  /** Ring-buffer capacity — ticks beyond this drop the oldest (default 120). */
  bufferSize?: number
}

export interface UseCardioStreamResult {
  ticks: StreamTick[]
  status: StreamStatus
  sendControl: (msg: ControlMsg) => void
}

// ── Snapshot parsing ───────────────────────────────────────────────────────────

type AttrEntry = { value: number; value_external: number; value_feedback: number }
type RawCycleReport = {
  cycle: number
  tags_emitted?: string[]
  deltas_per_attr?: Record<string, number>
  snapped?: string[]
  diverged?: boolean
  adaptation?: Record<string, Adaptation>
}
type RawSnapshot = {
  sensors: Record<string, AttrEntry>
  computed: Record<string, AttrEntry>
  feedback_norm: number
  cycle_report: RawCycleReport
  before_after?: Record<string, BeforeAfter>
  vectors?: Record<string, Record<string, number>>
  absorption?: Record<string, Record<string, number>>
  outcomes?: Record<string, OutcomeEvaluation[]>
  warnings?: string[]
  source?: { kind: string; detail: string }
}

/** Attribute map over one half of the snapshot, picking one of the X columns. */
function column(
  entries: Record<string, AttrEntry>,
  field: keyof AttrEntry
): Record<string, number> {
  return Object.fromEntries(Object.entries(entries).map(([id, a]) => [id, a[field]]))
}

function parseSnapshot(raw: unknown): StreamTick | null {
  try {
    const s = raw as RawSnapshot
    const r = s.cycle_report
    return {
      tick:          r.cycle,
      sensors:       column(s.sensors, 'value'),
      hr:            s.sensors.HR?.value              ?? 0,
      sbp:           s.sensors.SBP?.value             ?? 0,
      dbp:           s.sensors.DBP?.value             ?? 0,
      co:            s.computed.CO?.value              ?? 0,
      sv:            s.computed.SV?.value              ?? 0,
      map:           s.computed.MAP?.value             ?? 0,
      q:             s.computed.Q?.value               ?? 0,
      computed:         column(s.computed, 'value'),
      computedExternal: column(s.computed, 'value_external'),
      computedFeedback: column(s.computed, 'value_feedback'),
      co_feedback:   s.computed.CO?.value_feedback     ?? 0,
      sv_feedback:   s.computed.SV?.value_feedback     ?? 0,
      feedback_norm: s.feedback_norm                   ?? 0,
      tagsEmitted:   r.tags_emitted                    ?? [],
      deltasPerAttr: r.deltas_per_attr                 ?? {},
      snapped:       r.snapped                         ?? [],
      diverged:      r.diverged                        ?? false,
      adaptation:    r.adaptation                      ?? {},
      beforeAfter:   s.before_after                    ?? {},
      vectors:       s.vectors                         ?? {},
      absorption:    s.absorption                      ?? {},
      outcomes:      s.outcomes                        ?? {},
      warnings:      s.warnings                        ?? [],
      source:        s.source ?? { kind: 'unknown', detail: '' },
    }
  } catch {
    return null
  }
}

// ── Hook ───────────────────────────────────────────────────────────────────────

const MAX_BACKOFF_MS = 16_000

export function useCardioStream({
  tickMs    = 100,
  bufferSize = 120,
}: UseCardioStreamOptions = {}): UseCardioStreamResult {
  const [ticks,  setTicks]  = useState<StreamTick[]>([])
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled  = false
    let backoff    = 1_000
    let reconnTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return

      setStatus('connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const url = `${protocol}//${window.location.host}/ws/feedback?tick_ms=${tickMs}`
      const ws  = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }
        setStatus('open')
        backoff = 1_000   // reset on successful connect
      }

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (cancelled) return
        try {
          const tick = parseSnapshot(JSON.parse(ev.data))
          if (tick) {
            setTicks(prev => pushRing(prev, tick, bufferSize))
          }
        } catch { /* malformed frame — skip */ }
      }

      ws.onerror = () => { /* onclose fires next; nothing extra needed */ }

      ws.onclose = () => {
        if (cancelled) return
        setStatus('closed')
        reconnTimer = setTimeout(() => {
          backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
          connect()
        }, backoff)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnTimer) clearTimeout(reconnTimer)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [tickMs, bufferSize])

  const sendControl = useCallback((msg: ControlMsg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return { ticks, status, sendControl }
}
