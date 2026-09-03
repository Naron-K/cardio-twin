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

/** What crosses once the controller has opened the valve. */
export interface TransferSpec {
  mode: string
  rate: number
  time_delay: number
  on_close: string
  confidence: number
  band_min: number | null
  band_max: number | null
}

/** One declared crossing. */
export interface GateSpec {
  id: string
  /** `lamina:member` — kept because it is what the backend logs and warns with. */
  from: string
  to: string
  from_lamina: string
  from_member: string
  to_lamina: string
  to_member: string
  controller: string
  /** Which attribute of the source composite goes on the wire. */
  extract: string
  description: string
  /** Rule 1. Always true, and shown rather than assumed. */
  starts_closed: boolean
  /**
   * Whatever the declared controller needs — deliberately untyped beyond
   * this. A gate controller is a registry entry, so the set of keys is open,
   * and a UI that enumerated them would have to be edited before a new
   * controller could be drawn at all.
   */
  controller_params: Record<string, number | string | unknown>
  transfer: TransferSpec
  learnables: { name: string; initial: number | null; min: number; max: number }[]
}

/** One body this backend can serve, as `/api/organisms` lists it. */
export interface OrganismListing {
  id: string
  name: string
  file: string
  /** True for the body a request that names none will get. */
  default: boolean
  gates: number
}

export interface OrganismSchema {
  organism_id: string
  version: string
  name: string
  description: string
  laminae: OrganismLamina[]
  gates: GateSpec[]
}

// ── The live state (snapshot["gates"] on /ws/organism) ───────────────────────

/**
 * What the receiving attribute says about the number sitting in it.
 *
 * `coupled` — this gate put it there this cycle.
 * `held`    — this gate put it there, the gate has since shut, and `age` is
 *             how many cycles ago that was. A held value is not a live one,
 *             and the whole reason this field exists is that on screen the
 *             two are the same number.
 */
export interface GateProvenance {
  state?: 'coupled' | 'held'
  gate?: string
  from?: string
  age?: number
  open_fraction?: number
  target?: number
  rate?: number
  delay?: number
  reason?: string
}

/** One gate's declaration and its current state, as the socket sends it. */
export interface GateState {
  id: string
  from: string
  to: string
  from_lamina: string
  to_lamina: string
  controller: string
  extract: string
  mode: string
  description: string
  open: boolean
  open_fraction: number
  reason: string
  /** The number the controller's thresholds are comparing, in [0,1]. */
  watch_value: number | null
  /** The last value that actually crossed — null if none ever has. */
  last_value: number | null
  provenance: GateProvenance
}

/** How a gate should be drawn, which is not the same question as "is it open". */
export type GateDisplayState = 'open' | 'held' | 'shut'

/**
 * A gate has three states on screen and two in the model.
 *
 * Open and shut are the model's. `held` is the third thing the screen has to
 * say, and it is the one that has bitten this project before: a gate that
 * opened and then shut leaves the far side holding the last value that
 * crossed, and drawing that as a live coupling is drawing a reading from a
 * closed valve. It is shut — but shut with something of its own still on the
 * other side, which is different from shut having never carried anything.
 */
export function gateDisplayState(gate: GateState): GateDisplayState {
  if (gate.open) return 'open'
  return gate.provenance?.state === 'held' ? 'held' : 'shut'
}

/**
 * One line saying what the seam is doing, built from the gate alone.
 *
 * Deliberately not a lookup table of gate ids: the sentence is assembled from
 * the addresses and the state the backend sent, so a seam nobody has written
 * a caption for still describes itself.
 */
export function gateSummary(gate: GateState): string {
  switch (gateDisplayState(gate)) {
    case 'open':
      return gate.open_fraction < 1
        ? `carrying ${gate.extract} at ${Math.round(gate.open_fraction * 100)}% open`
        : `carrying ${gate.extract}`
    case 'held':
      return `shut — holding the last ${gate.extract} that crossed, ${gate.provenance.age ?? 0} cycles ago`
    default:
      return gate.reason ? `shut — ${gate.reason}` : 'shut'
  }
}
