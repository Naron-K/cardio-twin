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
  /**
   * Every PRELIMINARY attribute by id.  Consumers that must not see raw data
   * (the stage) take this and nothing else, so a new model output reaches
   * them without touching this hook.
   */
  computed: Record<string, number>
  // ── Feedback corrections ──────────────────────────────────────────
  /**
   * The X = X' + X'' split for every PRELIMINARY attribute.  `computed`
   * above is X; these are the
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
  state: 'coupled' | 'held' | 'uncoupled' | 'decaying'
  detail?: string
  gate?: string
  /** Which channel put it there, once a crossing has two ends. */
  channel?: string
  from?: string
  age?: number
  open_fraction?: number
  /**
   * Something is on the wire that this lamina has not taken.
   *
   * A fact about the CHANNEL, carried here because a reader looking at the
   * value wants to know it. The value itself is still the held one — this is
   * an extra clause on that, never a replacement for its state.
   */
  offer_waiting?: boolean
}

/**
 * The connection lifecycle, plus one state the socket itself cannot express.
 *
 * `suspended` is not a network condition: the caller asked for no stream
 * (`enabled: false`) and the hook deliberately closed the socket.  Without a
 * word for that, "off on purpose" and "dropped, retrying" both read as
 * `closed`, and a screen ends up offering a retry for something the user just
 * switched off.
 */
export type StreamStatus = 'connecting' | 'open' | 'closed' | 'suspended'

// Control message shapes — mirrors the WebSocket protocol in main.py
export type ControlMsg =
  | { type: 'set_sensor'; id: string; value: number }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'reset' }
  /** Idle liveness frame — see KEEPALIVE_MS for why it exists. */
  | { type: 'keepalive' }

/**
 * A frame the backend sends instead of a snapshot when it refuses a control
 * message.  The codes are the backend's vocabulary (`unknown_input`,
 * `invalid_value`, `out_of_range`, `bad_message`), and `id` names the sensor
 * the refusal was about when there was one.
 *
 * This exists because the old hook could only report a close: a refused
 * slider move left the control looking accepted while the model ignored it.
 */
export interface ServerNotice {
  level: 'warning' | 'error'
  code: string
  id: string | null
  message: string
}

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
  /**
   * Whether the caller wants a stream at all (default true).  False closes the
   * socket and stops reconnecting — a caller switching the twin off is not a
   * network drop, and retrying on its behalf would fight the switch.  Turning
   * it back on connects immediately; the replayed controls make it look as
   * though the stream never left.
   */
  enabled?: boolean
  /** Every notice frame the backend sends, including those for refusals. */
  onNotice?: (n: ServerNotice) => void
  /**
   * The socket opened again after having been open before, for this lamina.
   * `restored` is how many sensor values were replayed onto the fresh session
   * so the caller can say the controls were carried over rather than reset.
   */
  onReconnect?: (restored: number) => void
}

export interface UseCardioStreamResult {
  ticks: StreamTick[]
  status: StreamStatus
  /** True when the message went onto an open socket; false when it was only recorded. */
  sendControl: (msg: ControlMsg) => boolean
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
  /**
   * Epoch ms of the next scheduled reconnect while status is 'closed';
   * null when open, connecting, suspended, or refused (1008 has no retry).
   * A countdown needs a deadline, not just "reconnecting".
   */
  retryAt: number | null
  /** Consecutive closes since the last successful open; 0 while open. */
  attempts: number
  /** The socket has opened at least once for the current lamina. */
  everOpened: boolean
  /** Mirrors navigator.onLine, so the screen can blame the network instead of us. */
  online: boolean
  /**
   * Skip the rest of the current backoff and connect now.  A no-op while open,
   * connecting or suspended — there is either nothing to hurry or nothing to
   * start.  Stable, so it can be passed straight to a button.
   */
  retryNow: () => void
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
      computed:         column(s.computed, 'value'),
      computedExternal: column(s.computed, 'value_external'),
      computedFeedback: column(s.computed, 'value_feedback'),
      staleComputed:    staleOf(s.computed),
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

// ── Notice frames ─────────────────────────────────────────────────────────────

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/**
 * A notice, or null when this frame is something else.
 *
 * Snapshot frames have no `type` key at all, so the tag is the only way to
 * tell the two apart.  Every field is defaulted or type-checked: a notice
 * missing `message` is still worth surfacing, and a notice with a number where
 * a string belongs must not take the whole socket down with it.
 */
function parseNotice(raw: unknown): ServerNotice | null {
  if (!isRecord(raw) || raw.type !== 'notice') return null
  return {
    level: raw.level === 'error' ? 'error' : 'warning',
    code: typeof raw.code === 'string' ? raw.code : '',
    id: typeof raw.id === 'string' ? raw.id : null,
    message: typeof raw.message === 'string' ? raw.message : '',
  }
}

// ── Hook ───────────────────────────────────────────────────────────────────────

const MAX_BACKOFF_MS = 16_000

/**
 * How often an open socket says something with no data in it.
 *
 * A host that sleeps idle services — Render's free plan is one — counts inbound
 * WebSocket messages as activity, and a screen someone is watching without
 * touching sends none.  Four minutes is well inside the usual idle window and
 * far cheaper than a reconnect every time someone reads a panel.
 */
const KEEPALIVE_MS = 4 * 60_000

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
  /**
   * Whether this lamina's socket has ever opened.  Carried in the tagged
   * buffer for the same reason as the ticks: a stale buffer is read as the
   * empty one, so a lamina switch resets this without a separate clearing
   * effect (and without a render-time setState).
   */
  everOpened: boolean
}

/** Stable identity, so a mismatched buffer does not re-render on every read. */
const EMPTY_BUFFER: StreamBuffer = {
  lamina: null,
  ticks: [],
  lastTickAt: null,
  closeReason: null,
  everOpened: false,
}

export function useCardioStream({
  tickMs    = 100,
  bufferSize = 120,
  lamina    = null,
  enabled   = true,
  onNotice,
  onReconnect,
}: UseCardioStreamOptions = {}): UseCardioStreamResult {
  const [buffer, setBuffer] = useState<StreamBuffer>(() => ({ ...EMPTY_BUFFER, lamina }))
  const [status, setStatus] = useState<StreamStatus>(enabled ? 'connecting' : 'suspended')
  const [retryAt, setRetryAt] = useState<number | null>(null)
  const [attempts, setAttempts] = useState(0)
  // Start "online": the first effect run below replaces this with the browser's
  // answer.  Reading navigator in render would be a side effect during render,
  // and a wrong value for one paint is less trouble than that.
  const [online, setOnline] = useState(true)
  const wsRef = useRef<WebSocket | null>(null)

  // Mirrors `status` for callbacks (retryNow, the online listener) that live
  // outside the effect owning the socket.  Kept in step by setPhase() inside
  // that effect rather than during render, so retryNow sees the phase the
  // socket is in now, not the one from whichever render created it.
  const statusRef = useRef<StreamStatus>(status)

  // Whether this lamina has ever opened.  A ref rather than state because
  // onReconnect is decided inside the socket callbacks, which must remember
  // opens across the effect re-runs that `enabled` and the tick settings cause.
  const everOpenedRef = useRef(false)

  // What to put back onto a fresh server session.  The backend starts every
  // connection from the lamina's baselines; the sliders on screen do not.  Hold
  // the user's inputs here so a reconnect does not silently snap every control
  // back to baseline while the rail still shows what they set.
  const replayRef = useRef<{
    lamina: string | null
    sensors: Record<string, number>
    paused: boolean
  }>({ lamina: null, sensors: {}, paused: false })

  // The online listener and retryNow reach the effect's connect() through this
  // ref.  A ref keeps retryNow stable and stops a re-created listener from
  // opening a second socket.
  const retryNowRef = useRef<(() => void) | null>(null)

  const onNoticeRef = useRef(onNotice)
  const onReconnectRef = useRef(onReconnect)

  // Latest-callback refs, refreshed after every render.  An effect rather than
  // a render-time assignment so changing either callback cannot change what
  // this hook renders; no dependency array so it is never stale.
  useEffect(() => {
    onNoticeRef.current = onNotice
    onReconnectRef.current = onReconnect
  })

  // Derived on read, not cleared on change: the moment `lamina` differs, the
  // buffer built for the previous one stops being this hook's answer.  No
  // render passes through holding another model's numbers.
  const own = buffer.lamina === lamina ? buffer : EMPTY_BUFFER

  useEffect(() => {
    // A new lamina means none of the old lamina's controls mean anything on it,
    // and its first open is not "again" for this lamina.  Compare against the
    // ref's tag so a re-run for `enabled` or the tick settings keeps the replay
    // and the reopen memory intact.
    if (replayRef.current.lamina !== lamina) {
      replayRef.current = { lamina, sensors: {}, paused: false }
      everOpenedRef.current = false
    }

    /** Set both the rendered status and the ref retryNow reads, in one place. */
    const setPhase = (next: StreamStatus) => {
      statusRef.current = next
      setStatus(next)
    }

    if (!enabled) {
      const suspend = () => {
        setPhase('suspended')
        setRetryAt(null)
      }
      suspend()
      retryNowRef.current = null
      return
    }

    let cancelled  = false
    let backoff    = 1_000
    let reconnTimer: ReturnType<typeof setTimeout> | null = null
    let keepaliveTimer: ReturnType<typeof setInterval> | null = null

    const stopKeepalive = () => {
      if (keepaliveTimer) {
        clearInterval(keepaliveTimer)
        keepaliveTimer = null
      }
    }

    /** Write into this lamina's buffer, starting a fresh one if it is stale. */
    const record = (patch: (prev: StreamBuffer) => StreamBuffer) =>
      setBuffer((prev) =>
        patch(prev.lamina === lamina ? prev : { ...EMPTY_BUFFER, lamina })
      )

    const connect = () => {
      if (cancelled) return

      // Whatever we were waiting for, we are now connecting: no retry deadline.
      setRetryAt(null)
      setPhase('connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const query = new URLSearchParams({ tick_ms: String(tickMs) })
      if (lamina) query.set('lamina', lamina)
      const url = `${protocol}//${window.location.host}/ws/feedback?${query}`
      const ws  = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }

        // Read the reopen flag before marking it: this open is the first for
        // the lamina when the ref was still false, and a reopen otherwise.
        const reopened = everOpenedRef.current
        everOpenedRef.current = true
        setPhase('open')
        setAttempts(0)
        setRetryAt(null)
        record((prev) => ({ ...prev, everOpened: true, closeReason: null }))
        backoff = 1_000   // reset on successful connect

        // The sliders still hold the user's values, but this session started
        // from the lamina's baselines.  Put the recorded controls back before
        // the first snapshot can paint over them.
        const replay = replayRef.current
        let restored = 0
        for (const [id, value] of Object.entries(replay.sensors)) {
          try {
            ws.send(JSON.stringify({ type: 'set_sensor', id, value }))
            restored += 1
          } catch { /* socket went away mid-replay; the next open retries it */ }
        }
        if (replay.paused) {
          try {
            ws.send(JSON.stringify({ type: 'pause' }))
          } catch { /* same as above */ }
        }
        if (reopened) onReconnectRef.current?.(restored)

        // An idle screen sends no data, and some hosts count that as no
        // activity.  Say something before they decide we have gone.
        stopKeepalive()
        keepaliveTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({ type: 'keepalive' }))
            } catch { /* closed between the check and the send */ }
          }
        }, KEEPALIVE_MS)
      }

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (cancelled) return
        try {
          const frame: unknown = JSON.parse(ev.data)
          // Notices are refusals, not readings: hand them to the caller and
          // leave the buffer untouched.  parseNotice defaults every missing or
          // mistyped field, so a bad notice cannot crash the socket.
          const notice = parseNotice(frame)
          if (notice) {
            onNoticeRef.current?.(notice)
            return
          }
          const tick = parseSnapshot(frame)
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
        stopKeepalive()
        setPhase('closed')
        // 1008 is the server refusing what was asked for — an unknown lamina,
        // today.  Retrying cannot fix that, and the reason is worth showing
        // rather than hiding behind an endless "Reconnecting".
        if (ev.code === 1008) {
          const reason = ev.reason || 'refused by the server'
          record((prev) => ({ ...prev, closeReason: reason }))
          setRetryAt(null)
          return
        }
        // Record the delay actually used before doubling, so a countdown can
        // point at the same moment the timer will.
        const delay = backoff
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
        setAttempts((n) => n + 1)
        setRetryAt(Date.now() + delay)
        reconnTimer = setTimeout(() => {
          reconnTimer = null
          connect()
        }, delay)
      }
    }

    // Manual retry is only meaningful between closes: while open there is
    // nothing to hurry, while connecting there is already one in flight, and
    // while suspended the caller asked for no stream at all.
    retryNowRef.current = () => {
      if (cancelled || statusRef.current !== 'closed') return
      if (reconnTimer) {
        clearTimeout(reconnTimer)
        reconnTimer = null
      }
      connect()
    }

    connect()

    return () => {
      cancelled = true
      retryNowRef.current = null
      if (reconnTimer) clearTimeout(reconnTimer)
      stopKeepalive()
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [tickMs, bufferSize, lamina, enabled])

  // Network reachability is a fact about the browser, not the socket, and a
  // 'closed' socket on an offline machine is not worth the same retry as a
  // server that dropped us.  The online event also runs the retry path so
  // reconnecting need not wait out the rest of a backoff.
  useEffect(() => {
    const sync = () => setOnline(navigator.onLine)
    const goOnline = () => {
      sync()
      retryNowRef.current?.()
    }
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', sync)
    sync()
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', sync)
    }
  }, [])

  const sendControl = useCallback((msg: ControlMsg): boolean => {
    // Record intent even when the socket is down: a slider moved while
    // reconnecting should survive, not be dropped because it was early.
    if (msg.type === 'set_sensor') replayRef.current.sensors[msg.id] = msg.value
    else if (msg.type === 'pause') replayRef.current.paused = true
    else if (msg.type === 'resume') replayRef.current.paused = false

    const ws = wsRef.current
    if (ws?.readyState !== WebSocket.OPEN) return false
    try {
      ws.send(JSON.stringify(msg))
      return true
    } catch {
      return false
    }
  }, [])

  const retryNow = useCallback(() => {
    retryNowRef.current?.()
  }, [])

  return {
    ticks:       own.ticks,
    status,
    sendControl,
    lastTickAt:  own.lastTickAt,
    closeReason: own.closeReason,
    retryAt,
    attempts,
    everOpened: own.everOpened,
    online,
    retryNow,
  }
}
