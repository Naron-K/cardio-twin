import axios from 'axios'
import { parseDaySummary } from '../twin/dayView'
import type { DaySummary } from '../twin/dayView'
import { parseSources } from '../twin/sources'
import type { SourcesResponse } from '../twin/sources'

export type { DayRoute, ReplaySources, SourcesResponse } from '../twin/sources'

interface LaminaeResponse {
  laminae: { id: string }[]
  default: string
}

/**
 * The lamina whose XML declares a `<day_view>`, or null when none does.  The
 * page names no lamina itself: it asks each one, the backend's default first,
 * and takes the first that can describe a day.
 */
export async function findDayLamina(): Promise<string | null> {
  const { data } = await axios.get<LaminaeResponse>('/api/laminae')
  const ids = Array.isArray(data?.laminae)
    ? data.laminae
        .map((entry) => entry?.id)
        .filter((id): id is string => typeof id === 'string' && id.length > 0)
    : []
  const ordered = ids.includes(data.default)
    ? [data.default, ...ids.filter((id) => id !== data.default)]
    : ids

  const schemas = await Promise.all(
    ordered.map((id) =>
      axios
        .get<unknown>('/api/schema', { params: { lamina: id } })
        .then((res) => res.data)
        .catch(() => null),
    ),
  )
  const index = schemas.findIndex((schema) => {
    if (typeof schema !== 'object' || schema === null) return false
    const roles = (schema as Record<string, unknown>).day_view
    return typeof roles === 'object' && roles !== null
  })
  return index >= 0 ? ordered[index] : null
}

/** The recorded days one lamina can replay, checked field by field. */
export async function fetchSources(laminaId: string): Promise<SourcesResponse> {
  const res = await axios.get<unknown>('/api/sources', { params: { lamina: laminaId } })
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
 * A refused day.  `notFound` is a 404 (no such day, or no readings on it),
 * which retrying cannot change; anything else may be transient.
 */
export class DayError extends Error {
  readonly notFound: boolean

  constructor(message: string, notFound: boolean) {
    super(message)
    this.name = 'DayError'
    this.notFound = notFound
  }
}

/**
 * One recorded day, replayed by the server and checked field by field.  A
 * 400 (the lamina has no day view, or a bad parameter) and a 404 (no such
 * day, or nothing measured on it) become a DayError carrying the server's
 * message.
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
        throw new DayError(
          message ?? `The day could not be loaded (${status}).`,
          status === 404,
        )
      }
    }
    throw error
  }
}
