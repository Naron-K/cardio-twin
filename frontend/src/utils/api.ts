import axios from 'axios'
import type { LaminaSchema } from '../twin/schema'
import { parseSources } from '../twin/sourceBar'
import type { SourcesResponse } from '../twin/sourceBar'

export type { ReplaySources, SourcesResponse } from '../twin/sourceBar'

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

/**
 * Which feeds one lamina can stream and which recorded days exist.  The body
 * is checked field by field before it is returned, so a malformed response is
 * an offer with nothing in it rather than a shape the bar reads blindly.
 */
export async function fetchSources(laminaId?: string | null): Promise<SourcesResponse> {
  const res = await axios.get<unknown>('/api/sources', {
    params: laminaId ? { lamina: laminaId } : undefined,
  })
  return parseSources(res.data)
}
