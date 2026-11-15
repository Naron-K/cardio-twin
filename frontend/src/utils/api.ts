import axios from 'axios'
import { parseDaySummary } from '../twin/dayView'
import type { DaySummary } from '../twin/dayView'
import { parsePlanOptions, parsePlannedDay } from '../twin/planDay'
import type { PlanOptions, PlannedExtras } from '../twin/planDay'
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

/**
 * The lamina whose XML declares a `<plan_view>`, or null when none does.  The
 * page names no lamina itself: it asks each one, the backend's default first,
 * and takes the first that can describe a plan.
 */
export async function findPlanLamina(): Promise<string | null> {
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
    const roles = (schema as Record<string, unknown>).plan_view
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

/** The server's sentence and field for a refused plan, when it names them. */
function planRefusal(data: unknown): {
  message: string | null
  field: string | null
} {
  if (typeof data !== 'object' || data === null) {
    return { message: null, field: null }
  }
  const detail = (data as Record<string, unknown>).detail
  if (typeof detail === 'string') return { message: detail, field: null }
  if (typeof detail !== 'object' || detail === null) {
    return { message: null, field: null }
  }
  const record = detail as Record<string, unknown>
  return {
    message: typeof record.error === 'string' ? record.error : null,
    field: typeof record.field === 'string' ? record.field : null,
  }
}

/** A plan this subject's options cannot accept, naming the field. */
export class PlanRefusedError extends Error {
  readonly field: string | null

  constructor(message: string, field: string | null) {
    super(message)
    this.name = 'PlanRefusedError'
    this.field = field
  }
}

/**
 * Words for a request that failed without a refusal.  A request that got no
 * answer at all reads as that rather than as axios's "Network Error"; an
 * answer with a status says which; our own errors keep their message.
 */
export function failureMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    return status ? `The server answered with an error (${status}).` : 'The server did not answer.'
  }
  return error instanceof Error && error.message ? error.message : 'The server did not answer.'
}

/** A plan the server could not run for a reason other than a refusal. */
export class PlanRunError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PlanRunError'
  }
}

/**
 * Run one plan and return the answer, checked field by field.  A 422 names
 * the field that was refused; a 400 or 404 keeps the server's own sentence;
 * anything else is rethrown for the page's failed state.
 */
export async function runPlan(
  lamina: string,
  body: unknown,
): Promise<{ day: DaySummary; extras: PlannedExtras }> {
  try {
    const res = await axios.post<unknown>('/api/day/plan', body, {
      params: { lamina },
    })
    return parsePlannedDay(res.data)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      const data = error.response?.data
      if (status === 422) {
        const refusal = planRefusal(data)
        // The server starts its message with the field path ("sessions[1].start:
        // …"); the editor already shows it under that field, so drop the path.
        const text = refusal.message ?? 'The plan was refused (422).'
        const prefix = refusal.field ? `${refusal.field}: ` : ''
        throw new PlanRefusedError(
          prefix && text.startsWith(prefix) ? text.slice(prefix.length) : text,
          refusal.field,
        )
      }
      if (status === 400 || status === 404) {
        throw new PlanRunError(
          dayMessage(data) ?? `The plan could not be run (${status}).`,
        )
      }
    }
    throw error
  }
}

/** The subjects a 404 offered, when its detail carries a list. */
function offeredSubjects(data: unknown): string[] {
  if (typeof data !== 'object' || data === null) return []
  const detail = (data as Record<string, unknown>).detail
  if (typeof detail !== 'object' || detail === null) return []
  const available = (detail as Record<string, unknown>).available
  return Array.isArray(available)
    ? available.filter((entry): entry is string => typeof entry === 'string')
    : []
}

/**
 * A refused plan options request.  `notFound` is a 404 (no such subject, or
 * no templates to plan from), which retrying cannot change; `available` lists
 * the subjects the server said can be planned.
 */
export class PlanOptionsError extends Error {
  readonly notFound: boolean
  readonly available: string[]

  constructor(message: string, notFound: boolean, available: string[] = []) {
    super(message)
    this.name = 'PlanOptionsError'
    this.notFound = notFound
    this.available = available
  }
}

/**
 * Everything the plan editor draws for one subject, checked field by field.
 * `level` and `ambient` ask for settle tables at those plan values; omitting
 * them lets the server use the subject's medians.  A 400 and a 404 carry the
 * server's message and become a PlanOptionsError.
 */
export async function fetchPlanOptions(
  lamina: string,
  subject: string,
  level?: number,
  ambient?: number,
): Promise<PlanOptions> {
  const params: Record<string, string | number> = { lamina, subject }
  if (level !== undefined) params.level = level
  if (ambient !== undefined) params.ambient = ambient

  try {
    const res = await axios.get<unknown>('/api/plan/options', { params })
    return parsePlanOptions(res.data)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status
      if (status === 400 || status === 404) {
        const message = dayMessage(error.response?.data)
        throw new PlanOptionsError(
          message ?? `The plan options could not be loaded (${status}).`,
          status === 404,
          offeredSubjects(error.response?.data),
        )
      }
    }
    throw error
  }
}
