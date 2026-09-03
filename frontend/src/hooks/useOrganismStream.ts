/**
 * useOrganismStream — the socket for a whole body.
 *
 * Stands beside useCardioStream rather than replacing it, which is the same
 * choice the backend made: `/ws/feedback` sends one lamina and `/ws/organism`
 * sends a body, and the two payloads are different shapes. A hook that tried
 * to be both would have to decide at runtime which it had received, and a
 * client discovering that from the answer is the kind of bug that looks like
 * it is working.
 *
 * What this hook keeps is deliberately small: the latest state of each gate,
 * a short history of the body-level norm, and per-lamina headline numbers.
 * The full per-lamina snapshot is on the wire and nested under its lamina id
 * — anything that wants to draw a whole lamina should read the schema and use
 * the single-lamina machinery, not a second copy of it here.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { pushRing } from '../utils/ringBuffer'
import type { InboundProvenance } from './useCardioStream'
import type { ChannelState } from '../twin/organism'

// ── Types ────────────────────────────────────────────────────────────────────

/** The headline of one lamina on a body tick. */
export interface LaminaTick {
  laminaId: string
  cycle: number
  feedbackNorm: number
  /** Every PRELIMINARY attribute by id. */
  computed: Record<string, number>
  /** Every SENSOR attribute by id. */
  sensors: Record<string, number>
  /** Inputs that crossed from another lamina, by id. */
  inbound: Record<string, number>
  /**
   * What the backend says about each of those crossings, by attribute id.
   *
   * Carried rather than derived, and never defaulted away: without it every
   * inbound value renders as "baseline (uncoupled)", which is a specific and
   * false claim about a number a gate is actively feeding. Measured on the
   * body screen before this was passed through — CO_ref read 9.55 L/min while
   * the label under it said the seam had never carried anything.
   */
  inboundProvenance: Record<string, InboundProvenance>
  tagsEmitted: string[]
  warnings: string[]
}

/** One tick of a body. */
export interface OrganismTick {
  tick: number
  organismId: string
  /** Every gate, declaration and live state together, in declaration order. */
  channels: ChannelState[]
  /** Sum of every lamina's own feedback norm — the body-level probe. */
  totalFeedbackNorm: number
  /**
   * True once the body-level breaker has fired. Every gate is shut and stays
   * shut until a reset; the laminae keep running on their own, because a
   * lamina's internal loop is its own business and what went wrong is the
   * coupling.
   */
  gatesLocked: boolean
  /** Where each lamina stands, so the map can lay the stack out vertically. */
  levels: Record<string, number>
  laminae: Record<string, LaminaTick>
  warnings: string[]
}

export type OrganismStatus = 'connecting' | 'open' | 'closed'

/**
 * Control messages carry a lamina, because on a body "set HR" is ambiguous
 * and guessing which lamina meant it is exactly the sort of thing that looks
 * like it works.
 */
export type OrganismControlMsg =
  | { type: 'set_sensor'; lamina: string; id: string; value: number }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'reset' }

export interface UseOrganismStreamOptions {
  tickMs?: number
  bufferSize?: number
  /** Which organism file to stream; null takes the backend's default. */
  organism?: string | null
  /** Set false to leave the socket closed — for a screen that is not showing. */
  enabled?: boolean
}

export interface UseOrganismStreamResult {
  ticks: OrganismTick[]
  latest: OrganismTick | null
  status: OrganismStatus
  sendControl: (msg: OrganismControlMsg) => void
  lastTickAt: number | null
  closeReason: string | null
}

// ── Snapshot parsing ─────────────────────────────────────────────────────────

type AttrEntry = { value: number }
type RawInboundEntry = AttrEntry & { provenance?: InboundProvenance }
type RawLamina = {
  lamina_id?: string
  sensors?: Record<string, AttrEntry>
  inbound?: Record<string, RawInboundEntry>
  computed?: Record<string, AttrEntry>
  feedback_norm?: number
  warnings?: string[]
  cycle_report?: { cycle?: number; tags_emitted?: string[] }
}
type RawOrganism = {
  organism_id?: string
  channels?: ChannelState[]
  levels?: Record<string, number>
  laminae?: Record<string, RawLamina>
  organism_report?: {
    cycle?: number
    total_feedback_norm?: number
    gates_locked?: boolean
    warnings?: string[]
  }
}

function column(entries: Record<string, AttrEntry> | undefined): Record<string, number> {
  return Object.fromEntries(Object.entries(entries ?? {}).map(([id, a]) => [id, a.value]))
}

function parseSnapshot(raw: unknown): OrganismTick | null {
  try {
    const s = raw as RawOrganism
    const report = s.organism_report ?? {}
    const laminae: Record<string, LaminaTick> = {}
    for (const [laminaId, lamina] of Object.entries(s.laminae ?? {})) {
      laminae[laminaId] = {
        laminaId,
        cycle:        lamina.cycle_report?.cycle ?? 0,
        feedbackNorm: lamina.feedback_norm ?? 0,
        computed:     column(lamina.computed),
        sensors:      column(lamina.sensors),
        inbound:      column(lamina.inbound),
        inboundProvenance: Object.fromEntries(
          Object.entries(lamina.inbound ?? {}).map(([id, a]) => [
            id,
            a.provenance ?? { state: 'uncoupled' as const },
          ])
        ),
        tagsEmitted:  lamina.cycle_report?.tags_emitted ?? [],
        warnings:     lamina.warnings ?? [],
      }
    }
    return {
      tick:              report.cycle ?? 0,
      organismId:        s.organism_id ?? '',
      // Channels arrive already shaped for a reader — both ends and their
      // live state on one entry — so there is nothing to assemble here. If
      // that ever stops being true, the fix belongs in the backend: the
      // alternative is this file and the diagram each deciding what
      // "crossing" means, and two places computing one claim is how they
      // drift.
      channels:          s.channels ?? [],
      levels:            s.levels ?? {},
      totalFeedbackNorm: report.total_feedback_norm ?? 0,
      gatesLocked:       report.gates_locked ?? false,
      laminae,
      warnings:          report.warnings ?? [],
    }
  } catch {
    return null
  }
}

// ── Hook ─────────────────────────────────────────────────────────────────────

const MAX_BACKOFF_MS = 16_000

export function useOrganismStream({
  tickMs     = 100,
  bufferSize = 120,
  organism   = null,
  enabled    = true,
}: UseOrganismStreamOptions = {}): UseOrganismStreamResult {
  const [ticks, setTicks] = useState<OrganismTick[]>([])
  const [status, setStatus] = useState<OrganismStatus>('connecting')
  const [lastTickAt, setLastTickAt] = useState<number | null>(null)
  const [closeReason, setCloseReason] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Nothing to tear down and nothing to set: a disabled hook reports
    // 'closed' on the way out rather than storing it, so the effect never
    // writes state synchronously just to describe not doing anything.
    if (!enabled) return
    let cancelled = false
    let backoff = 1_000
    let reconnTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      setStatus('connecting')

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const query = new URLSearchParams({ tick_ms: String(tickMs) })
      if (organism) query.set('organism', organism)
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/organism?${query}`)
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }
        setStatus('open')
        setCloseReason(null)
        backoff = 1_000
      }

      ws.onmessage = (ev: MessageEvent<string>) => {
        if (cancelled) return
        try {
          const tick = parseSnapshot(JSON.parse(ev.data))
          if (tick) {
            setTicks((prev) => pushRing(prev, tick, bufferSize))
            setLastTickAt(Date.now())
          }
        } catch { /* malformed frame — skip */ }
      }

      ws.onerror = () => { /* onclose fires next */ }

      ws.onclose = (ev: CloseEvent) => {
        if (cancelled) return
        setStatus('closed')
        // 1008 is the server refusing what was asked for — an organism file
        // that does not exist or does not parse. Retrying cannot fix either,
        // and the reason is worth showing rather than hiding behind an
        // endless "Reconnecting".
        if (ev.code === 1008) {
          setCloseReason(ev.reason || 'refused by the server')
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
  }, [tickMs, bufferSize, organism, enabled])

  const sendControl = useCallback((msg: OrganismControlMsg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  return {
    ticks,
    latest: ticks.length > 0 ? ticks[ticks.length - 1] : null,
    status: enabled ? status : 'closed',
    sendControl,
    lastTickAt,
    closeReason,
  }
}
