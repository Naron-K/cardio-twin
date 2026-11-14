import axios from 'axios'
import { parseDaySummary } from '../twin/dayView'
import type { DaySummary } from '../twin/dayView'
import type { LaminaSchema } from '../twin/schema'
import { parseSources } from '../twin/sourceBar'
import type { SourcesResponse } from '../twin/sourceBar'

export type { PresetSource, ReplaySources, SourcesResponse } from '../twin/sourceBar'

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

/**
 * The server's own words for a refused day.  Both 400 and 404 carry their
 * reason under `detail`, sometimes as a string and sometimes as an object
 * whose `error` is the sentence worth showing.
 */
function dayMessage(data: unknown): string | null {
  if (typeof data !== 'object' || data === null) return null
  const detail = (data as Record<string, unknown>).detail
  if (typeof detail === 'string') return detail
  if (typeof detail === 'object' && detail !== null) {
    const error = (detail as Record<string, unknown>).error
    if (typeof error === 'string') return error
  }
  return null
}

/**
 * One recorded day, replayed by the server and checked field by field.  A
 * 400 (the lamina has no day view, or a bad parameter) and a 404 (no such
 * day) become an Error carrying the server's message, so the screen can
 * show the reason rather than a generic failure.
 */
export async function fetchDay(
  lamina: string,
  subject: string,
  date: string,
): Promise<DaySummary> {
  try {
    const res = await axios.get<unknown>('/api/day', {
      params: { lamina, subject, date },
    })
    return parseDaySummary(res.data)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      if (status === 400 || status === 404) {
        const message = dayMessage(error.response?.data)
        throw new Error(message ?? `The day could not be loaded (${status}).`)
      }
    }
    throw error
  }
}
