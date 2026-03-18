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

// ── Result types (from POST /api/compute or /api/upload) ──────────────────────

export interface AttributeResult {
  value: number
  normalised: number
  unit: string
  name: string
}

export interface SimulationResults {
  sensors: Record<string, AttributeResult>
  computed: Record<string, AttributeResult>
  vectors: Record<string, Record<string, number>>
  warnings: string[]
  log: string[]
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
