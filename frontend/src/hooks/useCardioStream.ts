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
   * Which lamina produced this snapshot.  A page fetches its structure once
   * and reads values off this socket forever, so without the stream saying
   * what it is, a backend restarted onto another lamina keeps streaming into
   * a screen still drawn for the old one — and looks entirely correct.  The
   * dashboard compares this against the schema it loaded on every tick.
   */
  laminaId: string
  /**
   * Every SENSOR attribute by id.  Raw input: this is the half of the snapshot
   * the stage is never handed.  It exists so a control rail can be generated
   * from the schema rather than from a list of ids typed into a component.
   */
  sensors: Record<string, number>
  /**
   * Inputs that crossed from another lamina, by id. Separate from `sensors`
   * because they are a different claim about where a number came from: a
   * sensor was measured, this was computed somewhere else and carried here.
   */
  inbound: Record<string, number>
  /**
   * Per inbound attribute, what the backend says about the crossing. `state` is
   * `"uncoupled"` while the attribute is resting on its declared baseline with
   * no gate feeding it, and `"coupled"` once one does — with the gate id and
   * source lamina alongside. Without this a placeholder baseline and a live
   * coupled value are the same number on screen.
   */
  inboundProvenance: Record<string, InboundProvenance>
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
  /**
   * Attributes that did not compute on the last pass, id → the reason the
   * backend gave.  The value in `computed` for one of these is last cycle's,
   * or absent — never this cycle's.  A failed computation used to be
   * indistinguishable from a healthy one on screen, because a stale number
   * and a fresh one are the same number; only the backend knows which is
   * which, and this is it saying so.
   */
  staleComputed: Record<string, string>
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

/**
 * What the backend says about one inter-lamina value's journey here.
 *
 * Three states, not two. `held` was missing while no gate could open, and
 * anything that is not `coupled` read as "baseline (uncoupled)" — so the
 * first time a gate opened and shut again, the far side showed a value a
 * gate had carried, under a label saying no gate had ever fed it. Measured
 * on the body screen: CO_ref reading 5.20 L/min beside "baseline
 * (uncoupled)" while the seam itself said "held 76 cycles".
 */
export interface InboundProvenance {
  state: 'coupled' | 'held' | 'uncoupled'
  detail?: string
  gate?: string
  from?: string
  age?: number
  open_fraction?: number
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
  /**
   * Which lamina to stream, by id.  Null takes whatever the backend defaults
   * to.  Changing it reopens the socket and empties the buffer: ticks from the
   * lamina you just left are not history of the one you arrived at, and
   * leaving them in the ring would draw one model's past under another's
   * present.
   */
  lamina?: string | null
}

export interface UseCardioStreamResult {
  ticks: StreamTick[]
  status: StreamStatus
  sendControl: (msg: ControlMsg) => void
  /**
   * When the last tick arrived, as epoch ms — null before the first one.
   *
   * A socket that dies leaves its final tick on screen, and a frozen number
   * is indistinguishable from a live one that happens not to be moving.  This
   * is what lets the screen say how old what it is showing actually is.
   */
  lastTickAt: number | null
  /** Why the server closed the socket, when it said — e.g. an unknown lamina. */
  closeReason: string | null
}

// ── Snapshot parsing ───────────────────────────────────────────────────────────

type AttrEntry = {
  value: number
  value_external: number
  value_feedback: number
  /** Only on computed attributes, and only from a backend new enough to send it. */
  stale?: boolean
  error?: string | null
}
type RawCycleReport = {
  cycle: number
  tags_emitted?: string[]
  deltas_per_attr?: Record<string, number>
  snapped?: string[]
  diverged?: boolean
  adaptation?: Record<string, Adaptation>
}
type RawInboundEntry = AttrEntry & { provenance?: InboundProvenance }
type RawSnapshot = {
  lamina_id?: string
  sensors: Record<string, AttrEntry>
  inbound?: Record<string, RawInboundEntry>
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
  field: 'value' | 'value_external' | 'value_feedback'
): Record<string, number> {
  return Object.fromEntries(Object.entries(entries).map(([id, a]) => [id, a[field]]))
}

/**
 * The attributes the backend says did not compute, id → reason.  Absent flags
 * mean a backend that predates the field, which reads as "nothing is stale" —
 * the same picture that backend could ever draw, rather than a screen full of
 * warnings it never sent.
 */
function staleOf(entries: Record<string, AttrEntry>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(entries)
      .filter(([, a]) => a.stale)
      .map(([id, a]) => [id, a.error ?? 'did not compute this cycle'])
  )
}

function parseSnapshot(raw: unknown): StreamTick | null {
  try {
    const s = raw as RawSnapshot
    const r = s.cycle_report
    return {
      tick:          r.cycle,
      laminaId:      s.lamina_id                       ?? '',
      sensors:       column(s.sensors, 'value'),
      inbound:       column(s.inbound ?? {}, 'value'),
      inboundProvenance: Object.fromEntries(
        Object.entries(s.inbound ?? {}).map(([id, a]) => [
          id,
          a.provenance ?? { state: 'uncoupled' as const },
        ])
      ),
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
      staleComputed:    staleOf(s.computed),
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

/**
 * Everything the socket has produced, and which lamina produced it.
 *
 * The three fields are one piece of state rather than three because they are
 * only meaningful together: a tick, when it arrived, and what it was a tick
 * *of*.  Tagging them with the lamina is also what makes switching safe without
 * clearing anything — a buffer whose tag no longer matches simply is not this
 * lamina's, and the empty one is read instead.  Ticks from the lamina you just
 * left are not history of the one you arrived at.
 */
interface StreamBuffer {
  lamina: string | null
  ticks: StreamTick[]
  lastTickAt: number | null
  closeReason: string | null
}

/** Stable identity, so a mismatched buffer does not re-render on every read. */
const EMPTY_BUFFER: StreamBuffer = {
  lamina: null,
  ticks: [],
  lastTickAt: null,
  closeReason: null,
}

export function useCardioStream({
  tickMs    = 100,
  bufferSize = 120,
  lamina    = null,
}: UseCardioStreamOptions = {}): UseCardioStreamResult {
  const [buffer, setBuffer] = useState<StreamBuffer>(() => ({ ...EMPTY_BUFFER, lamina }))
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)

  // Derived on read, not cleared on change: the moment `lamina` differs, the
  // buffer built for the previous one stops being this hook's answer.  No
  // render passes through holding another model's numbers.
  const own = buffer.lamina === lamina ? buffer : EMPTY_BUFFER

  useEffect(() => {
    let cancelled  = false
    let backoff    = 1_000
    let reconnTimer: ReturnType<typeof setTimeout> | null = null

    /** Write into this lamina's buffer, starting a fresh one if it is stale. */
    const record = (patch: (prev: StreamBuffer) => StreamBuffer) =>
      setBuffer((prev) =>
        patch(prev.lamina === lamina ? prev : { ...EMPTY_BUFFER, lamina })
      )

    const connect = () => {
      if (cancelled) return

      setStatus('connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const query = new URLSearchParams({ tick_ms: String(tickMs) })
      if (lamina) query.set('lamina', lamina)
      const url = `${protocol}//${window.location.host}/ws/feedback?${query}`
      const ws  = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }
        setStatus('open')
        record((prev) => (prev.closeReason === null ? prev : { ...prev, closeReason: null }))
        backoff = 1_000   // reset on successful connect
      }

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (cancelled) return
        try {
          const tick = parseSnapshot(JSON.parse(ev.data))
          if (tick) {
            record((prev) => ({
              ...prev,
              ticks: pushRing(prev.ticks, tick, bufferSize),
              lastTickAt: Date.now(),
            }))
          }
        } catch { /* malformed frame — skip */ }
      }

      ws.onerror = () => { /* onclose fires next; nothing extra needed */ }

      ws.onclose = (ev: CloseEvent) => {
        if (cancelled) return
        setStatus('closed')
        // 1008 is the server refusing what was asked for — an unknown lamina,
        // today.  Retrying cannot fix that, and the reason is worth showing
        // rather than hiding behind an endless "Reconnecting".
        if (ev.code === 1008) {
          const reason = ev.reason || 'refused by the server'
          record((prev) => ({ ...prev, closeReason: reason }))
          return
        }
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
  }, [tickMs, bufferSize, lamina])

  const sendControl = useCallback((msg: ControlMsg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return {
    ticks:       own.ticks,
    status,
    sendControl,
    lastTickAt:  own.lastTickAt,
    closeReason: own.closeReason,
  }
}
