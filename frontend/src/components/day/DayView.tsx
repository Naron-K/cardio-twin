/**
 * DayView — one recorded day, laid out for a specialist.
 *
 * Option C of the approved mockup: the day's figures on top, the whole day on
 * the left, the selected session enlarged on the right, and the session list
 * under it.  The endpoint is replayed once per (lamina, subject, date); picking
 * another session only changes what is drawn, never what is requested.
 *
 * Every attribute name, unit and colour group comes from the day summary.
 * Nothing in this file names a measurement, and a malformed or failed
 * response becomes the error state rather than a half-drawn page.
 */
import { useEffect, useRef, useState } from 'react'
import { DayError, fetchDay } from '../../utils/api'
import type { DaySummary } from '../../twin/dayView'
import {
  PLAY_SPEEDS,
  advanceMinute,
  clock,
  groupColourIndex,
  sessionAt,
  totalTo,
  valueAt,
  verdictText,
} from '../../twin/dayView'
import type { VerdictTone } from '../../twin/dayView'
import { Panel } from '../ui'
import { DayChart } from './DayChart'
import { DayLegend } from './DayLegend'
import { RateStrip } from './RateStrip'

interface Props {
  lamina: string
  subject: string
  date: string
  /** Told the loaded day, so the page header can show its zone and origin. */
  onDay?: (day: DaySummary) => void
}

type LoadState =
  | { key: string; attempt: number; status: 'loading' }
  | { key: string; attempt: number; status: 'error'; message: string; notFound: boolean }
  | { key: string; attempt: number; status: 'ready'; day: DaySummary }

const TONE_CLASS: Record<VerdictTone, string> = {
  ok: 'text-day-g0',
  slight: 'text-warn-strong',
  off: 'text-crimson-container',
  none: 'text-ink/60',
}

const GROUP_BORDER = [
  'border-day-g0',
  'border-day-g1',
  'border-day-g2',
  'border-day-g3',
] as const

function groupBorder(index: number): string {
  return index >= 0 && index < GROUP_BORDER.length
    ? GROUP_BORDER[index]
    : 'border-day-other'
}

function isNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function figure(value: number | null | undefined, unit = ''): string {
  if (!isNumber(value)) return '—'
  // A small fractional value keeps one decimal (13.5 h worn is not 14 h);
  // everything else reads as a whole number.
  const rounded =
    Math.abs(value) < 20 && !Number.isInteger(value)
      ? value.toLocaleString('en-GB', { maximumFractionDigits: 1 })
      : Math.round(value).toLocaleString('en-GB')
  return unit ? `${rounded} ${unit}` : rounded
}

/** Where the cursor is, and whether it is moving; null shows the whole day. */
interface Playback {
  minute: number
  running: boolean
}

/** A frame later than this (a hidden tab) moves the cursor this far only. */
const MAX_FRAME_MS = 250
/** Repaint at most this often; the cursor itself advances every frame. */
const PAINT_MS = 50

const CONTROL_CLASS =
  'min-h-[44px] rounded-el border px-3 font-mono text-[13px] font-bold readout uppercase transition-colors'

function sdFigure(sd: number): string {
  return Number.isInteger(sd) ? String(sd) : sd.toFixed(1)
}

/** A unit the label already says ("12,503" over "Steps") is left off. */
function kpiUnit(label: string, unit: string): string {
  return unit && !label.toLowerCase().includes(unit.toLowerCase()) ? unit : ''
}

export function DayView({ lamina, subject, date, onDay }: Props) {
  const key = `${lamina}\u0000${subject}\u0000${date}`
  const [attempt, setAttempt] = useState(0)
  const [load, setLoad] = useState<LoadState>({
    key: '',
    attempt: -1,
    status: 'loading',
  })
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [play, setPlay] = useState<Playback | null>(null)
  const [speed, setSpeed] = useState<number>(PLAY_SPEEDS[1])
  // The cursor between repaints; React state follows it at PAINT_MS.
  const minuteRef = useRef(0)

  useEffect(() => {
    let live = true

    fetchDay(lamina, subject, date)
      .then((day) => {
        if (!live) return
        setLoad({ key, attempt, status: 'ready', day })
        setSelectedIndex(0)
        setPlay(null)
        onDay?.(day)
      })
      .catch((error: unknown) => {
        if (!live) return
        const message =
          error instanceof Error && error.message
            ? error.message
            : 'The day could not be loaded.'
        const notFound = error instanceof DayError && error.notFound
        setLoad({ key, attempt, status: 'error', message, notFound })
      })

    return () => {
      live = false
    }
  }, [lamina, subject, date, attempt, key, onDay])

  const nMinutes = load.status === 'ready' ? load.day.n_minutes : 0
  const running = play?.running === true

  // The day is already here; playing it only moves the cursor, frame by
  // frame, and stops at the end of the day.
  useEffect(() => {
    if (!running || nMinutes <= 0) return
    let frame = 0
    let last = performance.now()
    let painted = last
    const step = (now: number) => {
      const dt = Math.min(MAX_FRAME_MS, Math.max(0, now - last))
      last = now
      const next = advanceMinute(minuteRef.current, speed, dt, nMinutes)
      minuteRef.current = next
      const ended = next >= nMinutes
      if (ended || now - painted >= PAINT_MS) {
        painted = now
        setPlay({ minute: next, running: !ended })
      }
      if (!ended) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [running, speed, nMinutes])

  // Tagged with its request, so a render between a change and the fetch that
  // answers it is loading — never the previous day drawn under new labels.
  const current = load.key === key && load.attempt === attempt ? load : null

  if (!current || current.status === 'loading') {
    return (
      <p className="rounded-card border border-white/10 bg-surface-low/80 px-5 py-4 font-mono text-[13px] readout uppercase text-ink/60 animate-pulse">
        Loading…
      </p>
    )
  }

  if (current.status === 'error') {
    // A missing or empty day is not fixed by retrying.  The server lists
    // every available day after "Available:", far too much to show.
    const missing = current.notFound
    const message = current.message.split('Available:')[0].trim()
    return (
      <div className="flex flex-col items-start gap-3 rounded-card border border-white/10 bg-surface-low/80 px-5 py-4">
        <p className={`font-body text-[15px] ${missing ? 'text-ink/80' : 'text-crimson-container'}`}>
          {message}
        </p>
        {!missing && (
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
            className="min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-4 font-mono text-[13px] font-bold readout uppercase text-ink/70 transition-colors hover:text-ink"
          >
            Retry
          </button>
        )}
      </div>
    )
  }

  const day = current.day
  const sessions = day.sessions
  const cursor = play ? play.minute : null
  // While the day plays, the enlarged session is the one the cursor is in or
  // has last passed; otherwise it is the one picked.
  const followed = cursor === null ? -1 : sessionAt(sessions, cursor)
  const selected =
    sessions.length === 0
      ? -1
      : followed >= 0
        ? followed
        : Math.max(0, Math.min(selectedIndex, sessions.length - 1))

  const seek = (minute: number) => {
    const clamped = Math.max(0, Math.min(day.n_minutes, minute))
    minuteRef.current = clamped
    setPlay((previous) => ({ minute: clamped, running: previous?.running === true }))
  }
  const togglePlay = () => {
    if (play?.running) {
      setPlay({ minute: minuteRef.current, running: false })
      return
    }
    const from = !play || minuteRef.current >= day.n_minutes ? 0 : minuteRef.current
    minuteRef.current = from
    setPlay({ minute: from, running: true })
  }
  const at = cursor === null ? null : Math.min(day.n_minutes - 1, Math.floor(cursor))
  const measuredNow = at === null ? null : valueAt(day.pair.measured, at, 5)
  const modelNow = at === null ? null : valueAt(day.pair.modelled, at, 1)
  const inSession =
    at === null ? null : sessions.find((entry) => at >= entry.start && at < entry.end) ?? null
  const session = selected >= 0 ? sessions[selected] : null
  const unit = day.pair.unit
  const verdict = session ? verdictText(session, day.model.sd, unit) : null
  const sd = `±${sdFigure(day.model.sd)}${unit ? ` ${unit}` : ''}`
  const modelLine = day.model.fitted
    ? `Model fitted on ${day.subject_label} only · residual SD ${sd}`
    : `Model with default coefficients · SD ${sd}`

  const playLabel = play?.running
    ? '⏸ Pause'
    : play && play.minute >= day.n_minutes
      ? '▶ Replay'
      : '▶ Play'

  const controls = (
    <div className="mb-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={togglePlay}
          className={`${CONTROL_CLASS} min-w-[104px] border-oxy-container/60 text-oxy hover:bg-oxy-container/15`}
        >
          {playLabel}
        </button>
        <div className="flex gap-1.5" role="group" aria-label="Playback speed">
          {PLAY_SPEEDS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={speed === value}
              onClick={() => setSpeed(value)}
              className={`${CONTROL_CLASS} min-w-[52px] px-2 ${
                speed === value
                  ? 'border-oxy-container/60 bg-oxy-container/15 text-oxy'
                  : 'border-white/10 bg-surface-lowest text-ink/60 hover:text-ink'
              }`}
            >
              ×{value}
            </button>
          ))}
        </div>
        <input
          type="range"
          aria-label="Time of day"
          min={0}
          max={day.n_minutes}
          step={1}
          value={cursor === null ? day.n_minutes : Math.floor(cursor)}
          onChange={(event) => seek(Number(event.target.value))}
          className="min-h-[44px] min-w-[140px] flex-1 accent-day-model"
        />
        {play && (
          <button
            type="button"
            onClick={() => setPlay(null)}
            className={`${CONTROL_CLASS} border-white/10 bg-surface-lowest text-ink/70 hover:text-ink`}
          >
            Whole day
          </button>
        )}
      </div>

      {at !== null && (
        <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 font-mono text-[13px] tabular-nums">
          <div className="flex items-baseline gap-2">
            <dt className="sr-only">Time</dt>
            <dd className="text-[22px] font-bold text-ink">{clock(at)}</dd>
          </div>
          {inSession && (
            <div className="flex items-baseline gap-1.5">
              <dt className="sr-only">Session</dt>
              <dd className="font-body font-semibold text-ink">{inSession.label}</dd>
            </div>
          )}
          <div className="flex items-baseline gap-1.5">
            <dt className="text-ink/60">Measured</dt>
            <dd className="text-day-measured">{figure(measuredNow, unit)}</dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="text-ink/60">Model</dt>
            <dd className="text-day-model">{figure(modelNow, unit)}</dd>
          </div>
          {measuredNow !== null && modelNow !== null && (
            <div className="flex items-baseline gap-1.5">
              <dt className="text-ink/60">Δ</dt>
              <dd className="text-ink">
                {measuredNow - modelNow >= 0 ? '+' : '−'}
                {Math.abs(measuredNow - modelNow).toFixed(1)}
              </dd>
            </div>
          )}
          {day.rates.map((rate) => (
            <div key={rate.attribute} className="flex items-baseline gap-1.5">
              <dt className="text-ink/60">{rate.label}</dt>
              <dd className="text-ink">{figure(totalTo(rate.values, at), rate.unit)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )

  const wholeDay = (
    <Panel className="!p-5" title="Whole day">
      {controls}
      <DayLegend day={day} />
      <div className="mt-2">
        {/* Full width when there is no session column beside it: a wider
            drawing keeps its labels at their set size instead of scaling up. */}
        <DayChart
          day={day}
          height={380}
          width={sessions.length > 0 ? 1000 : 1700}
          selected={selected >= 0 ? selected : null}
          until={cursor}
        />
      </div>
      <div className="mt-2">
        <RateStrip day={day} width={sessions.length > 0 ? 1000 : 1700} until={cursor} />
      </div>
    </Panel>
  )

  return (
    <div className="flex flex-col gap-4">
      <section className="flex flex-wrap gap-3 rounded-card border border-white/10 bg-surface-low/80 p-4">
        {day.kpis.map((kpi) => {
          const kpiShownUnit = kpiUnit(kpi.label, kpi.unit)
          return (
            <div
              key={kpi.key}
              className="min-w-[130px] flex-1 rounded-el bg-surface-lowest/60 px-4 py-3"
            >
              <p className="font-mono text-[26px] font-bold leading-none tabular-nums text-ink">
                {figure(kpi.value)}
                {kpiShownUnit && (kpiShownUnit === '%' ? '%' : ` ${kpiShownUnit}`)}
              </p>
              <p className="mt-2 font-body text-[13px] text-ink">{kpi.label}</p>
              {kpi.note && (
                <p className="mt-0.5 font-mono text-[12px] tabular-nums text-ink/60">
                  {kpi.note}
                </p>
              )}
            </div>
          )
        })}
      </section>

      {sessions.length === 0 ? (
        <>
          {wholeDay}
          <Panel className="!p-5" title="Sessions · 0">
            {null}
          </Panel>
        </>
      ) : (
        <div className="grid gap-4 wide:grid-cols-[minmax(0,62fr)_minmax(0,38fr)]">
          {wholeDay}

          <div className="flex flex-col gap-4">
            {session && (
              <Panel
                className="!p-5"
                title={`${session.label} · ${clock(session.start)}–${clock(session.end)}`}
              >
                {/* Before the cursor reaches the session's window there is
                    nothing to draw yet; empty axes would read as a fault. */}
                {cursor !== null && cursor < Math.max(0, session.start - 15) ? (
                  <div className="flex h-[260px] items-center justify-center rounded-el border border-white/10 bg-surface-lowest/40 font-mono text-[13px] tabular-nums text-ink/60">
                    Starts {clock(session.start)}
                  </div>
                ) : (
                  <DayChart
                    day={day}
                    from={Math.max(0, session.start - 15)}
                    to={Math.min(day.n_minutes, session.end + 20)}
                    height={260}
                    width={640}
                    labels={false}
                    until={cursor}
                  />
                )}

                <div
                  className={`mt-3 rounded-el border-l-[5px] bg-surface-lowest/60 px-4 py-3 ${groupBorder(groupColourIndex(day, session.group))}`}
                >
                  <p className="font-display text-[17px] font-semibold text-ink">
                    {session.label}
                  </p>
                  <p className="font-mono text-[13px] tabular-nums text-ink/60">
                    {clock(session.start)}–{clock(session.end)} · {session.minutes} min
                  </p>
                  <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-body text-[13px]">
                    <FragmentRow label="Mean" value={figure(session.mean_measured, unit)} />
                    <FragmentRow label="Model" value={figure(session.mean_modelled, unit)} />
                    {verdict && (
                      <>
                        <dt className="text-ink/60">Δ measured − model</dt>
                        <dd
                          className={`text-right font-mono font-bold tabular-nums ${TONE_CLASS[verdict.tone]}`}
                        >
                          {verdict.text}
                        </dd>
                      </>
                    )}
                    <FragmentRow label="Peak" value={figure(session.peak_measured, unit)} />
                    {day.rates.map((rate) => (
                      <FragmentRow
                        key={rate.attribute}
                        label={rate.label}
                        value={figure(session.rate_totals[rate.attribute], rate.unit)}
                      />
                    ))}
                  </dl>
                </div>
              </Panel>
            )}

            <Panel className="!p-5" title={`Sessions · ${sessions.length}`}>
              <div className="flex flex-col gap-2">
                {sessions.map((entry, index) => {
                  const delta = verdictText(entry, day.model.sd, '')
                  return (
                    <button
                      key={`${entry.start}-${entry.end}-${index}`}
                      type="button"
                      aria-pressed={selected === index}
                      onClick={() => {
                        if (index < 0 || index >= sessions.length) return
                        setSelectedIndex(index)
                        // While playing, picking a session jumps the cursor to it.
                        if (play) seek(entry.start)
                      }}
                      className={`min-h-[44px] w-full rounded-el border-l-[5px] px-3 py-2 text-left font-body text-[13px] transition-colors ${groupBorder(groupColourIndex(day, entry.group))} ${
                        selected === index
                          ? 'bg-white/5 ring-2 ring-day-model'
                          : 'bg-surface-lowest/60 hover:bg-white/5'
                      }`}
                    >
                      <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                        <span className="font-semibold text-ink">{entry.label}</span>
                        <span className="font-mono tabular-nums text-ink/60">
                          {clock(entry.start)}–{clock(entry.end)}
                        </span>
                        <span className="ml-auto font-mono tabular-nums text-ink/80">
                          {figure(entry.mean_measured, unit)}
                        </span>
                        <span
                          className={`min-w-[72px] text-right font-mono tabular-nums ${TONE_CLASS[delta.tone]}`}
                        >
                          {delta.tone === 'none' ? delta.text : `Δ ${delta.text.split(' · ')[0]}`}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </Panel>
          </div>
        </div>
      )}

      <p className="font-mono text-[12px] text-ink/50">
        {modelLine} · not for clinical use
      </p>
    </div>
  )
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink/60">{label}</dt>
      <dd className="text-right font-mono tabular-nums text-ink">{value}</dd>
    </>
  )
}
