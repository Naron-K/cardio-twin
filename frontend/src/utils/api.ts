import axios from 'axios'
import type { LaminaSchema } from '../twin/schema'
import type { OrganismListing, OrganismSchema } from '../twin/organism'

// ── Schema types (from GET /api/schema) ───────────────────────────────────────
//
// The payload is described once, in twin/schema.ts, because the universal
// visualiser is built entirely out of it and a second partial copy here is how
// the two drift apart.  This file re-exports the pieces the older analysis
// views already import by these names.

export type {
  LaminaSchema,
  AttributeSchema,
  CompositeSchema,
  FunctionSchema,
  SegmentSchema,
  OutcomeSchema,
  TagSchema,
  GateSchema,
} from '../twin/schema'

export type Schema = LaminaSchema

// ── The body (GET /api/organism) ──────────────────────────────────────────────
//
// Described in twin/organism.ts for the same reason the lamina schema is
// described in twin/schema.ts: the diagram is built entirely out of the
// payload, and a second partial copy of the shape here is how the two drift.

export type {
  OrganismSchema,
  OrganismListing,
  OrganismLamina,
  GateSpec,
  GateState,
} from '../twin/organism'

/**
 * Every body this backend can serve, and which one is the default.
 *
 * The picker is built from this rather than from a list in the frontend: a
 * body is an XML file in `backend/`, and dropping one in should be enough.
 */
export async function fetchOrganisms(): Promise<{
  organisms: OrganismListing[]
  default: string
}> {
  const res = await axios.get<{ organisms: OrganismListing[]; default: string }>(
    '/api/organisms'
  )
  return res.data
}

/**
 * The body's declaration: which laminae, and the seams between them.
 *
 * `organism` names a file; omit it for the backend's default. The backend
 * loads the laminae to check the rules a gate can only break against them, so
 * a 400 here is a badly declared body rather than a missing one.
 */
export async function fetchOrganism(organism?: string | null): Promise<OrganismSchema> {
  const res = await axios.get<OrganismSchema>('/api/organism', {
    params: organism ? { organism } : undefined,
  })
  return res.data
}

// ── Result types (from POST /api/compute, /api/upload, /api/feedback/*) ───────

export interface AttributeResult {
  value: number
  normalised: number
  unit: string
  name: string
  // Phase A: X = X' + X'' decomposition. value_feedback is 0 from /api/compute
  // and non-zero after feedback cycles via /api/feedback/*.
  value_external?: number
  value_feedback?: number
}

export interface SimulationResults {
  sensors: Record<string, AttributeResult>
  computed: Record<string, AttributeResult>
  vectors: Record<string, Record<string, number>>
  warnings: string[]
  log?: string[]
  // Only present from /api/feedback/* responses.
  feedback_norm?: number
  outcomes?: Record<string, unknown>
}

// ── Feedback loop types (Phase D/F) ───────────────────────────────────────────

// Server-side kernel_state — opaque to FE, round-tripped verbatim.
// Keys are "tag_id|attr_id" strings (see backend _KSTATE_SEP).
export type KernelState = Record<string, Record<string, number>>

export interface FeedbackCycleReport {
  cycle: number
  tags_emitted: string[]
  deltas_per_attr: Record<string, number>
  feedback_norm: number
  feedback_norm_pre_recompute: number
  diverged: boolean
  snapped: string[]
  warnings: string[]
}

export interface FeedbackStepResponse {
  cycle: number
  cycle_report: FeedbackCycleReport
  state: SimulationResults
  kernel_state: KernelState
  diverged: boolean
}

export interface FeedbackRunResponse {
  cycles_run: number
  stopped_reason: 'settled' | 'max_cycles' | 'diverged'
  cycle: number
  trace: FeedbackCycleReport[]
  state: SimulationResults
  kernel_state: KernelState
  diverged: boolean
}

// ── API functions ──────────────────────────────────────────────────────────────

/**
 * One lamina this backend can serve.  `implemented` is false where the XML
 * declares a structure whose arithmetic nobody has written: it loads, draws its
 * whole shape, and shows a dash on every computed node.  That is a legitimate
 * thing to open, so it is offered and marked rather than hidden.
 */
export interface LaminaOption {
  id: string
  name: string
  level: number
  file: string
  implemented: boolean
}

export interface LaminaeResponse {
  laminae: LaminaOption[]
  /** The one a request naming no lamina will get. */
  default: string
}

export async function fetchLaminae(): Promise<LaminaeResponse> {
  const res = await axios.get<LaminaeResponse>('/api/laminae')
  return res.data
}

/**
 * The structure of one lamina.  Pass the id the socket was opened with, never
 * a different one and never nothing-when-the-socket-had-something: the guard in
 * the dashboard can only hold if both halves were told the same thing.
 */
export async function fetchSchema(laminaId?: string | null): Promise<Schema> {
  const res = await axios.get<Schema>('/api/schema', {
    params: laminaId ? { lamina: laminaId } : undefined,
  })
  return res.data
}

export async function computeResults(
  sensorData: Record<string, number>
): Promise<SimulationResults> {
  const res = await axios.post<SimulationResults>('/api/compute', {
    sensor_data: sensorData,
  })
  return res.data
}

export async function uploadXML(file: File): Promise<SimulationResults> {
  const form = new FormData()
  form.append('file', file)
  const res = await axios.post<SimulationResults>('/api/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

// ── Feedback loop API (Phase F) ───────────────────────────────────────────────

export async function feedbackStep(args: {
  sensorData: Record<string, number>
  kernelState: KernelState
  cycle: number
}): Promise<FeedbackStepResponse> {
  const res = await axios.post<FeedbackStepResponse>('/api/feedback/step', {
    sensor_data: args.sensorData,
    kernel_state: args.kernelState,
    cycle: args.cycle,
  })
  return res.data
}

export async function feedbackRun(args: {
  sensorData: Record<string, number>
  kernelState: KernelState
  cycle: number
  cycles: number
  settledThreshold?: number
  settledWindow?: number
}): Promise<FeedbackRunResponse> {
  const res = await axios.post<FeedbackRunResponse>('/api/feedback/run', {
    sensor_data: args.sensorData,
    kernel_state: args.kernelState,
    cycle: args.cycle,
    cycles: args.cycles,
    settled_threshold: args.settledThreshold,
    settled_window: args.settledWindow,
  })
  return res.data
}

// Download full simulation results as XML string
export async function downloadResultsXML(
  results: SimulationResults,
  name: string
): Promise<string> {
  const res = await axios.post<string>(
    '/api/download',
    { results, name },
    { responseType: 'text' }
  )
  return res.data
}
