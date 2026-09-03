/**
 * The body-level declaration, as the frontend reads it.
 *
 * `GET /api/organism` is to a body what `GET /api/schema` is to one lamina:
 * fetched once, entirely declared, and never a live number. Everything that
 * moves arrives on `/ws/organism` instead. The split is the whole reason the
 * diagram can be drawn before the first tick — a valve is a valve whether or
 * not anything has crossed it yet.
 *
 * Nothing here names an attribute, a lamina or a gate. A second organism with
 * three laminae and four seams draws itself from this file unchanged.
 *
 * ── What changed when the valve moved onto the membranes ────────────────────
 *
 * A crossing used to be one gate sitting between two laminae. It is now a
 * CHANNEL with gates on both ends: the sender's gates decide whether anything
 * is offered, the receiver's decide whether anything is taken, and the channel
 * holds what has been offered and not yet taken.
 *
 * For a screen that means three things it did not have to draw before:
 *   - two valves on one edge, not one in the middle;
 *   - a difference between an AUTO gate and a KEY gate, because one is a
 *     protection layer nobody may switch off and the other is a policy;
 *   - `waiting` — the sender has put something down and the receiver has not
 *     picked it up. Which is NOT `held`, and must not look like it.
 */

// ── The declaration (GET /api/organism) ──────────────────────────────────────

/** One lamina, as the body lists it — not its full schema. */
export interface OrganismLamina {
  id: string
  name: string
  /** Inputs this lamina measures for itself. */
  sensors: string[]
  /** Inputs that have to arrive from somewhere else (source INTER_LAMINA). */
  inbound: string[]
  composites: string[]
}

/** Which kind of gate, which is a difference in what it reads. */
export type GateKind = 'auto' | 'key'

/** Which membrane it sits on. */
export type GateSide = 'transmit' | 'receive'

/**
 * One gate, as the body declares it.
 *
 * `params` is deliberately untyped beyond this. A trigger and a key metric are
 * both registry entries, so the set of keys is open, and a UI that enumerated
 * them would have to be edited before a new one could be drawn at all.
 */
export interface GateSpec {
  id: string
  kind: GateKind
  side: GateSide
  description: string
  /** Rule 1. Always true, and shown rather than assumed. */
  starts_closed: boolean
  params: Record<string, number | string | unknown>
  learnables: { name: string; initial: number | null; min: number; max: number }[]
  /** Auto gates only: `threshold` or `pattern`. */
  trigger?: string
  /** Key gates only. */
  metric?: string
  weight?: number
  rate?: number
  on_close?: string
  confidence?: number
}

/** One declared crossing, and the gates on each of its two ends. */
export interface ChannelSpec {
  id: string
  /** `lamina:member` — kept because it is what the backend logs and warns with. */
  from: string
  to: string
  from_lamina: string
  from_member: string
  to_lamina: string
  to_member: string
  /** Which attribute of the source composite goes on the wire. */
  extract: string
  time_delay: number
  description: string
  /** Which way this wire climbs the stack, so a diagram need not recompute it. */
  direction: 'up' | 'down'
  transmit: GateSpec[]
  receive: GateSpec[]
}

/** One body this backend can serve, as `/api/organisms` lists it. */
export interface OrganismListing {
  id: string
  name: string
  file: string
  /** True for the body a request that names none will get. */
  default: boolean
  channels: number
}

export interface OrganismSchema {
  organism_id: string
  version: string
  name: string
  description: string
  laminae: OrganismLamina[]
  /** Where each lamina stands in the stack. A property of the BODY. */
  levels: Record<string, number>
  channels: ChannelSpec[]
}

// ── The live state (snapshot["channels"] on /ws/organism) ────────────────────

/**
 * What the receiving attribute says about the number sitting in it.
 *
 * `coupled`  — this channel put it there this cycle.
 * `held`     — this channel put it there, nothing is crossing now, and `age`
 *              is how many cycles ago that was. A held value is not a live
 *              one, and the whole reason this field exists is that on screen
 *              the two are the same number.
 * `decaying` — the same, but walking back toward the declared baseline.
 */
export interface ChannelProvenance {
  state?: 'coupled' | 'held' | 'decaying'
  channel?: string
  gate?: string
  from?: string
  age?: number
  open_fraction?: number
  target?: number
  rate?: number
  weight?: number
  flood?: boolean
  delay?: number
  reason?: string
}

/** One gate's live state, as the socket sends it. */
export interface GateState {
  id: string
  kind: GateKind
  side: GateSide
  description: string
  open: boolean
  open_fraction: number
  reason: string
  /** Whatever the trigger reported — `watch_value`, `match`, `drift`, … */
  state: Record<string, number | string | boolean | null>
  trigger?: string
  metric?: string
  weight?: number
  rate?: number
  on_close?: string
}

/** One channel's declaration and its current state, both ends. */
export interface ChannelState {
  id: string
  from: string
  to: string
  from_lamina: string
  to_lamina: string
  extract: string
  time_delay: number
  description: string
  transmit: GateState[]
  receive: GateState[]
  /** What the sender has put on the wire, whether or not it was taken. */
  offered: number | null
  /** How many cycles that offer has been sitting there unclaimed. */
  offered_age: number
  /** The last value that actually crossed — null if none ever has. */
  last_value: number | null
  /** What the container says this channel is doing. One claim, one source. */
  state?: string
  provenance: ChannelProvenance
}

/**
 * How a channel should be drawn, which is not the same question as "is a gate
 * open".
 *
 * `crossing` — both membranes are open and a value is moving.
 * `waiting`  — the sender has offered and the receiver has not taken. New with
 *              the two-sided design, and the one that must not be drawn as
 *              `held`: waiting is "outside the door", held is "came in a while
 *              ago and is going stale". Reading one as the other is the same
 *              family of mistake as reading a dead stream as a live one.
 * `held`     — nothing is crossing, and the far side is still holding the last
 *              value that did.
 * `decaying` — the same, walking back to the declared baseline.
 * `shut`     — nothing is crossing and nothing was ever carried.
 */
export type ChannelDisplayState =
  | 'crossing'
  | 'waiting'
  | 'held'
  | 'decaying'
  | 'shut'

/**
 * Read from the backend's own word rather than recomputed here.
 *
 * The container already decides this — it is the only thing that knows a band
 * refused a value while both gates were open — and two places computing the
 * same claim is how they drift.
 */
export function channelDisplayState(
  channel: ChannelState,
  reported?: string,
): ChannelDisplayState {
  if (
    reported === 'crossing' ||
    reported === 'waiting' ||
    reported === 'held' ||
    reported === 'decaying'
  ) {
    return reported
  }
  const provenance = channel.provenance?.state
  if (provenance === 'held' || provenance === 'decaying') return provenance
  return 'shut'
}

/** Every gate on a channel, sender's first — the order they are evaluated. */
export function channelGates(channel: ChannelState): GateState[] {
  return [...channel.transmit, ...channel.receive]
}

/**
 * One line saying what the seam is doing, built from the channel alone.
 *
 * Deliberately not a lookup table of ids: the sentence is assembled from the
 * addresses and the state the backend sent, so a seam nobody has written a
 * caption for still describes itself.
 */
export function channelSummary(
  channel: ChannelState,
  reported?: string,
): string {
  const age = channel.provenance?.age ?? 0
  switch (channelDisplayState(channel, reported)) {
    case 'crossing': {
      const open = channel.provenance?.open_fraction ?? 1
      return open < 1
        ? `carrying ${channel.extract} at ${Math.round(open * 100)}% open`
        : `carrying ${channel.extract}`
    }
    case 'waiting':
      return `offered — ${channel.extract} on the wire, not taken${
        channel.offered_age > 0 ? ` for ${channel.offered_age} cycles` : ''
      }`
    case 'held':
      return `shut — holding the last ${channel.extract} that crossed, ${age} cycles ago`
    case 'decaying':
      return `shut — the last ${channel.extract} is decaying back to baseline`
    default: {
      const why = channel.transmit.find((g) => !g.open)?.reason
      return why ? `shut — ${why}` : 'shut'
    }
  }
}

/** What one gate is doing, in a phrase. */
export function gateSummary(gate: GateState): string {
  const what = gate.kind === 'auto'
    ? `${gate.trigger ?? 'auto'} trigger`
    : `${gate.metric ?? 'key'} key`
  return gate.open ? `open · ${what}` : `shut · ${gate.reason || what}`
}
