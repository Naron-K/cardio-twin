import axios from 'axios'

// ── Schema types (from GET /api/schema) ───────────────────────────────────────

export interface AttributeSchema {
  id: string
  name: string
  unit: string
  source: 'SENSOR' | 'PRELIMINARY'
  physio_min: number
  physio_max: number
  description: string
  computed_by: string | null
  depends_on: string[]
}

export interface CompositeSchema {
  id: string
  name: string
  attribute_ids: string[]
  description: string
}

export interface FunctionSchema {
  id: string
  name: string
  step: number
  formula: string
  inputs: string[]
  output: string
  description: string
}

export interface Schema {
  lamina_name: string
  attributes: Record<string, AttributeSchema>
  composites: Record<string, CompositeSchema>
  functions: FunctionSchema[]
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

export async function fetchSchema(): Promise<Schema> {
  const res = await axios.get<Schema>('/api/schema')
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
