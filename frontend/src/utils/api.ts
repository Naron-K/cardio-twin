import axios from 'axios'
import type { LaminaSchema } from '../twin/schema'

// The schema payload is described once, in twin/schema.ts, because the
// dashboard is built entirely out of it and a second partial copy here is how
// the two drift apart.
export type Schema = LaminaSchema

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
