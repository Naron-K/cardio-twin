/**
 * The plan view: the setup card for one subject, with the plan kept in the
 * URL, and the projection the server returns when Run is pressed.
 *
 * Nothing is computed while the sliders move.  A run replaces the result and
 * plays it from the first waking minute; any later edit dims that result and
 * offers "Run again" rather than rerunning by itself.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { PlanEditor } from './PlanEditor'
import { PlanEmpty, PlanResult } from './PlanResult'
import type { Plan, PlanOptions, PlannedExtras } from '../../twin/planDay'
import {
  controlForField,
  decodePlan,
  encodePlan,
  planBody,
  planFromOptions,
} from '../../twin/planDay'
import type { DaySummary } from '../../twin/dayView'
import { PLAY_SPEEDS, advanceMinute, clock } from '../../twin/dayView'
import type { SourcesResponse } from '../../twin/sources'
import { subjectLabel } from '../../twin/sources'
import {
  PlanOptionsError,
  PlanRefusedError,
  failureMessage,
  fetchPlanOptions,
  fetchSources,
  findPlanLamina,
  runPlan,
} from '../../utils/api'

interface Ready {
  lamina: string
  subject: string
  sources: SourcesResponse
  options: PlanOptions
  plan: Plan
  notice: string | null
}

type Boot =
  | { status: 'loading' }
  | { status: 'no-lamina' }
  | { status: 'no-templates'; label: string | null }
  | { status: 'error'; message: string }
  | ({ status: 'ready' } & Ready)

type Phase = 'idle' | 'running' | 'ready' | 'refused' | 'failed'

interface Result {
  day: DaySummary
  extras: PlannedExtras
  awake: [number, number]
}

const RETRY_CLASS =
  'min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-4 ' +
  'font-mono text-[13px] font-bold readout uppercase text-ink/70 transition-colors hover:text-ink'

const NOTICE =
  'The plan in the link could not be read; showing a typical day'

const MAX_FRAME_MS = 250
const PAINT_MS = 50

export function PlanPage() {
  const [attempt, setAttempt] = useState(0)
  const [boot, setBoot] = useState<Boot>({ status: 'loading' })
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<Result | null>(null)
  const [stale, setStale] = useState(false)
  const [refused, setRefused] = useState<{
    control: string | null
    message: string
  } | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [cursor, setCursor] = useState(0)
  const [speed, setSpeed] = useState<number>(PLAY_SPEEDS[1])
  const minuteRef = useRef(0)
  const runRef = useRef(0)
  const editRef = useRef(0)

  useEffect(() => {
    let live = true

    const load = async () => {
      try {
        const lamina = await findPlanLamina()
        if (!live) return
        if (!lamina) {
          setBoot({ status: 'no-lamina' })
          return
        }

        const sources = await fetchSources(lamina)
        if (!live) return

        const names = Object.keys(sources.replay?.subjects ?? {})
        if (names.length === 0) {
          setBoot({ status: 'no-templates', label: null })
          return
        }

        let failure: unknown = null
        let requestFailed = false

        for (const subject of names) {
          try {
            const options = await fetchPlanOptions(lamina, subject)
            if (!live) return

            const wanted = new URLSearchParams(window.location.search).get('plan')
            let plan = planFromOptions(options)
            let notice: string | null = null
            if (wanted !== null) {
              const decoded = decodePlan(wanted, options)
              if (decoded) plan = decoded
              else notice = NOTICE
            }

            setBoot({
              status: 'ready',
              lamina,
              subject,
              sources,
              options,
              plan,
              notice,
            })
            return
          } catch (error) {
            if (!live) return
            failure = error
            // A subject with no templates is not a reason to stop asking the
            // next subject; anything else is a request worth retrying.
            if (!(error instanceof PlanOptionsError) || !error.notFound) {
              requestFailed = true
              break
            }
          }
        }

        if (!live) return
        if (requestFailed) {
          setBoot({ status: 'error', message: failureMessage(failure) })
        } else {
          setBoot({ status: 'no-templates', label: subjectLabel(sources, names[0]) })
        }
      } catch (error) {
        if (!live) return
        setBoot({ status: 'error', message: failureMessage(error) })
      }
    }

    void load()
    return () => {
      live = false
    }
  }, [attempt])

  const ready = boot.status === 'ready' ? boot : null

  // The settle tables depend on the day's level and temperature.  After the
  // reader stops moving either, ask again; the editor keeps working with the
  // last good tables until the answer arrives, and a stale answer is ignored.
  // The options say which level and temperature their tables were built at,
  // so a link that names other values asks again as soon as it opens.
  const laminaId = ready ? ready.lamina : null
  const subjectId = ready ? ready.subject : null
  const level = ready ? ready.plan.level : null
  const ambient = ready ? ready.plan.ambient : null
  const builtAt = ready ? ready.options.day.settle_at : null
  const planKey = level !== null && ambient !== null ? `${level}\u0000${ambient}` : null
  const tableKey =
    builtAt !== null ? `${builtAt.level}\u0000${builtAt.ambient}` : null

  useEffect(() => {
    if (
      laminaId === null ||
      subjectId === null ||
      level === null ||
      ambient === null ||
      planKey === null ||
      tableKey === null ||
      planKey === tableKey
    ) {
      return
    }

    let live = true
    const timer = window.setTimeout(() => {
      fetchPlanOptions(laminaId, subjectId, level, ambient)
        .then((options) => {
          if (!live) return
          setBoot((current) => {
            if (current.status !== 'ready') return current
            if (
              current.lamina !== laminaId ||
              current.subject !== subjectId
            ) {
              return current
            }
            return { ...current, options }
          })
        })
        .catch(() => {
          // The editor stays usable with the settle tables it already has.
        })
    }, 300)

    return () => {
      live = false
      window.clearTimeout(timer)
    }
  }, [laminaId, subjectId, level, ambient, planKey, tableKey])

  const encoded = ready ? encodePlan(ready.plan) : null
  useEffect(() => {
    if (encoded === null) return
    const query = new URLSearchParams(window.location.search)
    query.set('view', 'plan')
    query.set('plan', encoded)
    const next = `${window.location.pathname}?${query.toString()}`
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (current !== next) window.history.replaceState(null, '', next)
  }, [encoded])

  const changePlan = useCallback(
    (plan: Plan) => {
      editRef.current += 1
      setBoot((current) =>
        current.status === 'ready' ? { ...current, plan } : current,
      )
      setRefused(null)
      if (result) {
        setStale(true)
        setPlaying(false)
        if (phase === 'refused') setPhase('ready')
      } else if (phase === 'refused') {
        setPhase('idle')
      }
    },
    [result, phase],
  )

  // The day is already here; playing it only moves the cursor, frame by frame,
  // from the first waking minute and stops at the end of the waking window.
  const playable = result !== null && phase === 'ready' && !stale
  useEffect(() => {
    if (!playing || !playable || !result) return
    const end = result.awake[1]
    let frame = 0
    let last = performance.now()
    let painted = last
    const step = (now: number) => {
      const dt = Math.min(MAX_FRAME_MS, Math.max(0, now - last))
      last = now
      const next = advanceMinute(minuteRef.current, speed, dt, end)
      minuteRef.current = next
      const ended = next >= end
      if (ended || now - painted >= PAINT_MS) {
        painted = now
        setCursor(next)
        if (ended) setPlaying(false)
      }
      if (!ended) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, playable, result, speed])

  const run = useCallback(
    async (plan: Plan) => {
      if (!ready) return
      const id = ++runRef.current
      const editsAtStart = editRef.current
      setPhase('running')
      setPlaying(false)
      setRefused(null)
      setFailure(null)

      try {
        const answer = await runPlan(
          ready.lamina,
          planBody(plan, ready.subject, ready.options),
        )
        if (runRef.current !== id) return
        setResult({
          day: answer.day,
          extras: answer.extras,
          awake: [plan.awake[0], plan.awake[1]],
        })
        setPhase('ready')
        const changed = editRef.current !== editsAtStart
        setStale(changed)
        minuteRef.current = plan.awake[0]
        setCursor(plan.awake[0])
        setPlaying(!changed)
      } catch (error) {
        if (runRef.current !== id) return
        if (error instanceof PlanRefusedError) {
          setRefused({
            control: error.field === null ? null : controlForField(error.field),
            message: error.message,
          })
          setPhase('refused')
          setPlaying(false)
          return
        }
        setFailure(failureMessage(error))
        setPhase('failed')
        setPlaying(false)
      }
    },
    [ready],
  )

  const togglePlay = useCallback(() => {
    if (!result || stale || phase !== 'ready') return
    if (playing) {
      setPlaying(false)
      return
    }
    if (minuteRef.current < result.awake[0] || minuteRef.current >= result.awake[1]) {
      minuteRef.current = result.awake[0]
      setCursor(result.awake[0])
    }
    setPlaying(true)
  }, [result, stale, phase, playing])

  const seek = useCallback(
    (minute: number) => {
      if (!result) return
      const clamped = Math.max(
        result.awake[0],
        Math.min(result.awake[1], minute),
      )
      minuteRef.current = clamped
      setCursor(clamped)
    },
    [result],
  )

  const status = (() => {
    if (phase === 'running') return 'Running…'
    if (phase === 'refused') return 'Refused'
    if (phase === 'failed') return 'Failed'
    if (!result) return 'Not run'
    if (stale) return 'Setup changed'
    if (playing) return `Playing ${clock(cursor)} · ×${speed}`
    if (cursor >= result.awake[1]) return 'Done'
    return `Paused ${clock(cursor)}`
  })()

  const dimmed =
    result !== null && (stale || phase === 'refused' || phase === 'running')
  const overlay = stale && phase !== 'running' && phase !== 'failed'

  return (
    <>
      {/* The selected tab already reads "Plan a day", and the approved layout
          needs the chart above the fold at 1920x1080, so the page title is for
          screen readers only and the subject's name sits in the Setup card. */}
      <h1 className="sr-only">Plan a day</h1>

      <main className="flex-1 p-4 wide:px-margin wide:py-gutter">
        {boot.status === 'loading' ? (
          <p className="font-mono text-[13px] readout uppercase text-ink/60 animate-pulse">
            Loading…
          </p>
        ) : boot.status === 'no-lamina' ? (
          <p className="font-body text-[15px] text-ink/80">
            No lamina with a plan view.
          </p>
        ) : boot.status === 'no-templates' ? (
          <p className="font-body text-[15px] text-ink/80">
            {boot.label
              ? `No activity templates for ${boot.label}.`
              : 'No activity templates.'}
          </p>
        ) : boot.status === 'error' ? (
          <div className="flex flex-col items-start gap-3">
            <p className="font-body text-[15px] text-crimson-container">
              {boot.message}
            </p>
            <button
              type="button"
              onClick={() => {
                setBoot({ status: 'loading' })
                setAttempt((value) => value + 1)
              }}
              className={RETRY_CLASS}
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            {boot.notice && (
              <p className="mb-3 rounded-el border border-warn-strong/60 bg-warn-strong/10 px-3 py-2 font-body text-[13px] text-warn">
                {boot.notice}
              </p>
            )}
            <PlanEditor
              options={boot.options}
              plan={boot.plan}
              onChange={changePlan}
              onRun={(plan) => void run(plan)}
              running={phase === 'running'}
              status={status}
              refused={refused}
            />

            <div className="relative mt-4">
              {failure ? (
                <section className="rounded-card border border-crimson-container/50 bg-surface-low/80 p-5">
                  <p className="font-body text-[15px] text-crimson-container">
                    {failure}
                  </p>
                  <button
                    type="button"
                    onClick={() => void run(boot.plan)}
                    className={`${RETRY_CLASS} mt-3`}
                  >
                    Retry
                  </button>
                </section>
              ) : result ? (
                <>
                  <PlanResult
                    day={result.day}
                    extras={result.extras}
                    options={boot.options}
                    awake={result.awake}
                    cursor={cursor}
                    playing={playing}
                    speed={speed}
                    onTogglePlay={togglePlay}
                    onSpeed={setSpeed}
                    onSeek={seek}
                    dimmed={dimmed}
                  />
                  {overlay && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center rounded-card bg-surface/35">
                      <button
                        type="button"
                        onClick={() => void run(boot.plan)}
                        className="min-h-[52px] rounded-el border border-transparent bg-oxy-container px-5 text-[16px] font-bold text-[#04202a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oxy-container"
                      >
                        Run again
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <PlanEmpty running={phase === 'running'} />
              )}
            </div>
          </>
        )}
      </main>
    </>
  )
}
