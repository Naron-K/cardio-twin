/**
 * animators — the registry that turns model quantities into motion.
 *
 * This is the only place allowed to know how a number becomes movement.  The
 * model emits state; the template says which placeholder reads which state and
 * names an animator; an animator here does the conversion.  The model never
 * learns that a screen exists.
 *
 * Mirrors the backend's registry pattern (`_gate_kernel_registry`,
 * `_emitter_registry`, and five more) — a new visual behaviour is a new entry
 * here plus a name in the template, not a change to the renderer.
 */
import type { EnvelopeId, Flow, Modulator, Motion } from './stageTemplate'

export interface AnimatorContext {
  /** Current 0→1 strength of a cardiac phase window. */
  envelope: (id: EnvelopeId) => number
  /** Live value of a model attribute, or undefined if the stage wasn't given it. */
  value: (attribute: string) => number | undefined
}

/**
 * How far a modulating attribute pushes an amplitude.  Missing attributes fall
 * back to 1× rather than freezing the stage — a binding the model can't satisfy
 * should look nominal, and Schematic mode is where the gap gets reported.
 */
export function modulatorGain(mod: Modulator | null, ctx: AnimatorContext): number {
  if (!mod) return 1
  const v = ctx.value(mod.attribute)
  if (v === undefined || !Number.isFinite(v) || mod.reference === 0) return 1
  const [lo, hi] = mod.range
  return Math.min(hi, Math.max(lo, v / mod.reference))
}

export type MotionAnimator = (motion: Motion, ctx: AnimatorContext) => number

export const MOTION_ANIMATORS: Record<string, MotionAnimator> = {
  /** Uniform scale about the placeholder's pivot, summed over its phase terms. */
  scale: (motion, ctx) => {
    const gain = modulatorGain(motion.modulator, ctx)
    let s = 1
    for (const term of motion.terms) s += term.amount * ctx.envelope(term.envelope) * gain
    return s
  },
}

export type FlowAnimator = (flow: Flow, ctx: AnimatorContext) => number

export const FLOW_ANIMATORS: Record<string, FlowAnimator> = {
  /**
   * Particles riding a vessel centreline.  Returns cycles per second: 5 L/min
   * ≈ one particle-cycle per 0.95 s, matching the rate the sprite used.
   */
  flow_along_path: (flow, ctx) => {
    const rate = ctx.value(flow.rateFrom) ?? 0
    return 0.28 + Math.min(12, Math.max(0, rate)) * 0.14
  },
}
