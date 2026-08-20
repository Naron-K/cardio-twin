/**
 * schema — the lamina, as the model describes itself.
 *
 * `/api/schema` is the backend reading the lamina XML and handing back
 * everything it found: attributes and where each one comes from, the functions
 * that compute them and their formulae, the composites that group them, the
 * segments that own them, the behavioural outcomes that judge them, the tags
 * that wire deviations back into the loop, the permeability gates, and the
 * registry of mechanisms the engine offers for the XML to choose from.
 *
 * This module is the *only* place that knows the shape of that payload, and it
 * knows nothing else.  There is no attribute id in this file, no unit, no
 * threshold and no clinical word — a lamina describing a kidney, a battery or a
 * water network parses here unchanged.  Everything downstream reads the index
 * built below rather than the raw payload, so a view can ask "which function
 * produces this attribute" without every view re-deriving it.
 *
 * The rule the whole visualiser rests on: **structure comes from here, values
 * come from the tick, and nothing comes from a constant typed into a component.**
 */

// ── Wire types — one per XML element the backend serialises ──────────────────

export type Source = 'SENSOR' | 'PRELIMINARY'

export interface AttributeSchema {
  id: string
  name: string
  unit: string
  source: Source
  physio_min: number
  physio_max: number
  description: string
  /** Function id that produces this attribute; null for a raw input. */
  computed_by: string | null
  depends_on: string[]
}

export interface CompositeSchema {
  id: string
  name: string
  attribute_ids: string[]
  description: string
  /** Learning weights (frozen in v1) and gate-fanout multipliers. */
  absorption_vector: number[] | null
  distribution_vector: number[] | null
}

export interface FunctionSchema {
  id: string
  name: string
  /** Ordering key from the XML — a string, because steps like "3a" exist. */
  step: string
  formula: string
  inputs: string[]
  output: string
  description: string
}

export interface OutcomeSchema {
  id: string
  name: string
  attribute_id: string
  target_value: number
  tolerance: number
  unit: string
  description: string
}

export interface SegmentSchema {
  id: string
  name: string
  attribute_ids: string[]
  composite_ids: string[]
  function_ids: string[]
  description: string
  behavioural_outcomes: OutcomeSchema[]
}

export interface TagTargetSchema {
  address: string
  weight: number
}

export interface TagSchema {
  id: string
  outcome: string
  deviation_type: string
  emitter: string
  gate_kernel: string
  /** −1 corrective, +1 amplifying, 0 monitor-only. */
  polarity: number
  targets: TagTargetSchema[]
  params: Record<string, number>
}

export interface GateSchema {
  attribute: string
  gate_type: string
  min: number | null
  max: number | null
  tolerance: number | null
  compare: string[] | null
  action_on_fail: string
  flag: string
  steepness: number
}

export interface FeedbackConfig {
  coupling_type: string
  behaviour_solver_type: string
  behaviour_solver_dt: number
  behaviour_solver_unit: string
  adaptation_kernel?: string
  slow_loop_cadence?: number
  adaptation_params?: Record<string, number>
}

/** Mechanism names the engine has registered, per pipeline slot. */
export type Registries = Record<string, string[]>

export interface LaminaSchema {
  lamina_name: string
  lamina_id: string
  lamina_level: number
  upper_lamina_id: string
  lower_lamina_id: string
  attributes: Record<string, AttributeSchema>
  composites: Record<string, CompositeSchema>
  functions: FunctionSchema[]
  segments: Record<string, SegmentSchema>
  channel_mappings: Record<string, string>
  feedback_config: FeedbackConfig
  tags: Record<string, TagSchema>
  gates: GateSchema[]
  registries: Registries
}

// ── Index — the derivations every view would otherwise redo ──────────────────

/**
 * A lamina with its cross-references resolved once.
 *
 * Optional blocks are normalised to empty rather than left undefined, so a
 * minimal lamina — attributes and functions, no composites, no tags, no
 * outcomes — flows through every view without a single existence check at the
 * call site.  A view that has nothing to draw says so by way of its
 * `applies()` predicate in the view registry, not by crashing here.
 */
export interface LaminaIndex {
  schema: LaminaSchema
  /** Raw inputs, in declaration order. */
  sensors: AttributeSchema[]
  /** Model-computed attributes, in the order their functions run. */
  computed: AttributeSchema[]
  attribute: (id: string) => AttributeSchema | undefined
  functions: FunctionSchema[]
  functionById: Record<string, FunctionSchema>
  /** attribute id → the function that produces it. */
  functionByOutput: Record<string, FunctionSchema>
  /** attribute id → functions that consume it. */
  functionsByInput: Record<string, FunctionSchema[]>
  segments: SegmentSchema[]
  /** attribute id → the segment that lists it, if any. */
  segmentOfAttribute: Record<string, SegmentSchema>
  composites: CompositeSchema[]
  /** attribute id → composites it belongs to. */
  compositesOfAttribute: Record<string, CompositeSchema[]>
  outcomes: OutcomeSchema[]
  outcomeById: Record<string, OutcomeSchema>
  /** attribute id → outcomes that judge it (usually 0 or 1). */
  outcomesOfAttribute: Record<string, OutcomeSchema[]>
  tags: TagSchema[]
  /** outcome id → tags that fire off it. */
  tagsOfOutcome: Record<string, TagSchema[]>
  /** composite id → tags that fan into it. */
  tagsIntoComposite: Record<string, TagSchema[]>
  gates: GateSchema[]
  /** attribute id → gates declared on it. */
  gatesOfAttribute: Record<string, GateSchema[]>
  /** attribute id → 'SENSOR' | 'PRELIMINARY', for the provenance rule. */
  sources: Record<string, string>
}

/** Steps sort as "1", "2", "3a", "3b" — lexicographic is the XML's own order. */
function byStep(a: FunctionSchema, b: FunctionSchema): number {
  return String(a.step).localeCompare(String(b.step), undefined, { numeric: true })
}

function push<T>(map: Record<string, T[]>, key: string, value: T): void {
  ;(map[key] ??= []).push(value)
}

export function indexLamina(raw: LaminaSchema): LaminaIndex {
  const attributes = raw.attributes ?? {}
  const functions = [...(raw.functions ?? [])].sort(byStep)
  const segments = Object.values(raw.segments ?? {})
  const composites = Object.values(raw.composites ?? {})
  const tags = Object.values(raw.tags ?? {})
  const gates = raw.gates ?? []

  const functionById: Record<string, FunctionSchema> = {}
  const functionByOutput: Record<string, FunctionSchema> = {}
  const functionsByInput: Record<string, FunctionSchema[]> = {}
  for (const fn of functions) {
    functionById[fn.id] = fn
    if (fn.output) functionByOutput[fn.output] = fn
    for (const input of fn.inputs ?? []) push(functionsByInput, input, fn)
  }

  const segmentOfAttribute: Record<string, SegmentSchema> = {}
  const outcomes: OutcomeSchema[] = []
  for (const seg of segments) {
    for (const id of seg.attribute_ids ?? []) segmentOfAttribute[id] ??= seg
    outcomes.push(...(seg.behavioural_outcomes ?? []))
  }

  const outcomeById: Record<string, OutcomeSchema> = {}
  const outcomesOfAttribute: Record<string, OutcomeSchema[]> = {}
  for (const o of outcomes) {
    outcomeById[o.id] = o
    push(outcomesOfAttribute, o.attribute_id, o)
  }

  const compositesOfAttribute: Record<string, CompositeSchema[]> = {}
  for (const c of composites) {
    for (const id of c.attribute_ids ?? []) push(compositesOfAttribute, id, c)
  }

  const tagsOfOutcome: Record<string, TagSchema[]> = {}
  const tagsIntoComposite: Record<string, TagSchema[]> = {}
  for (const t of tags) {
    push(tagsOfOutcome, t.outcome, t)
    for (const target of t.targets ?? []) push(tagsIntoComposite, target.address, t)
  }

  const gatesOfAttribute: Record<string, GateSchema[]> = {}
  for (const g of gates) push(gatesOfAttribute, g.attribute, g)

  const sources: Record<string, string> = {}
  for (const [id, a] of Object.entries(attributes)) sources[id] = a.source

  const all = Object.values(attributes)
  // Computed attributes read best in the order the chain runs them; ones no
  // function claims fall to the end rather than vanishing.
  const stepOf = (a: AttributeSchema) => {
    const fn = a.computed_by ? functionById[a.computed_by] : functionByOutput[a.id]
    return fn ? functions.indexOf(fn) : Number.MAX_SAFE_INTEGER
  }

  return {
    schema: raw,
    sensors: all.filter((a) => a.source === 'SENSOR'),
    computed: all.filter((a) => a.source !== 'SENSOR').sort((a, b) => stepOf(a) - stepOf(b)),
    attribute: (id: string) => attributes[id],
    functions,
    functionById,
    functionByOutput,
    functionsByInput,
    segments,
    segmentOfAttribute,
    composites,
    compositesOfAttribute,
    outcomes,
    outcomeById,
    outcomesOfAttribute,
    tags,
    tagsOfOutcome,
    tagsIntoComposite,
    gates,
    gatesOfAttribute,
    sources,
  }
}

// ── Small shared helpers ─────────────────────────────────────────────────────

/** Position of a value on an attribute's declared range, clamped, as a %. */
export function pctOfRange(attr: AttributeSchema | undefined, value: number): number {
  if (!attr) return 0
  const span = Math.max(1e-9, attr.physio_max - attr.physio_min)
  return Math.max(0, Math.min(100, ((value - attr.physio_min) / span) * 100))
}

/**
 * Enough significant figures to see a change, few enough to read.  Chosen from
 * the magnitude rather than a per-attribute table, because a per-attribute
 * table is exactly the kind of thing that would need editing per lamina.
 */
export function fmtValue(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1000) return v.toFixed(0)
  if (a >= 100) return v.toFixed(1)
  if (a >= 1) return v.toFixed(2)
  if (a === 0) return '0'
  return v.toFixed(3)
}

/** The XML's word for what a tag does to its targets. */
export function polarityLabel(polarity: number): string {
  if (polarity < 0) return 'corrective'
  if (polarity > 0) return 'amplifying'
  return 'monitor only'
}
