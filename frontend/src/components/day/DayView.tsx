/**
 * DayView — one recorded day, laid out for a specialist.
 *
 * Option C of the approved mockup: the day's KPIs on top, the whole day on
 * the left, the selected session enlarged on the right, and the session list
 * under it.  The endpoint is replayed once per (lamina, subject, date); picking
 * another session only changes what is drawn, never what is requested.
 *
 * Every attribute name, unit and colour group comes from the day summary and
 * the schema.  Nothing in this file names a measurement, and a malformed or
 * failed response becomes the error state rather than a half-drawn page.
 */
import { useEffect, useState } from 'react'
import { fetchDay } from '../../utils/api'
import type { DaySummary } from '../../twin/dayView'
import { clock, groupColourIndex, verdictText } from '../../twin/dayView'
import type { VerdictTone } from '../../twin/dayView'
import { Chip, Panel } from '../twin/ui'
import { DayChart } from './DayChart'
import { DayLegend } from './DayLegend'
import { RateStrip } from './RateStrip'

interface Props {
  lamina: string
  subject: string
  date: string
}

type LoadState =
  | { key: string; attempt: number; status: 'loading' }
  | { key: string; attempt: number; status: 'error'; message: string }
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

function sdFigure(sd: number): string {
  return Number.isInteger(sd) ? String(sd) : sd.toFixed(1)
}

export function DayView({ lamina, subject, date }: Props) {
  const key = `${lamina}\u0000${subject}\u0000${date}`
  const [attempt, setAttempt] = useState(0)
  const [load, setLoad] = useState<LoadState>({
    key: '',
    attempt: -1,
    status: 'loading',
  })
  const [selectedIndex, setSelectedIndex] = useState(0)

  useEffect(() => {
    let live = true

    fetchDay(lamina, subject, date)
      .then((day) => {
        if (!live) return
        setLoad({ key, attempt, status: 'ready', day })
        setSelectedIndex(0)
      })
      .catch((error: unknown) => {
        if (!live) return
        const message =
          error instanceof Error && error.message
            ? error.message
            : 'The day could not be loaded.'
        setLoad({ key, attempt, status: 'error', message })
      })

    return () => {
      live = false
    }
  }, [lamina, subject, date, attempt, key])

  // Tagged with its request, so a render between a change and the fetch that
  // answers it is loading — never the previous day drawn under new labels.
  const current = load.key === key && load.attempt === attempt ? load : null

  if (!current || current.status === 'loading') {
    return (
      <p className="rounded-card border border-white/10 bg-surface-low/80 px-5 py-4 font-mono text-[13px] readout uppercase text-ink/60 animate-pulse">
        Reading the day…
      </p>
    )
  }

  if (current.status === 'error') {
    // A day that does not exist is not fixed by retrying: say so in one line
    // (the server lists every available day, far too much to show) and point
    // at the picker. Anything else may be transient, so it keeps Retry.
    const missing = current.message.includes('Available:')
    const message = missing
      ? `${current.message.split('Available:')[0].trim()} Pick an available day above.`
      : current.message
    return (
      <div className="flex flex-col items-start gap-3 rounded-card border border-white/10 bg-surface-low/80 px-5 py-4">
        <p className={`font-body text-[15px] ${missing ? 'text-ink/80' : 'text-crimson-container'}`}>
          {message}
        </p>
        {!missing && <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          className="min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-4 font-mono text-[13px] font-bold readout uppercase text-ink/70 transition-colors hover:text-ink"
        >
          Retry
        </button>}
      </div>
    )
  }

  const day = current.day
  const sessions = day.sessions
  const selected =
    sessions.length === 0
      ? -1
      : Math.max(0, Math.min(selectedIndex, sessions.length - 1))
  const session = selected >= 0 ? sessions[selected] : null
  const modelNote = day.model.applies_to
    ? `Fitted for ${day.model.applies_to}`
    : 'Declared default coefficients — not fitted to this person'
  const verdict = session
    ? verdictText(session, day.model.sd, day.pair.unit)
    : null

  const wholeDay = (
    <Panel
      className="!p-5"
      eyebrow="Whole day"
      title={sessions.length > 0 ? 'Whole day — pick a session' : 'Whole day'}
    >
      <DayLegend day={day} />
      <div className="mt-2">
        {/* Full width when there is no session column beside it: a wider
            drawing keeps its labels at their set size instead of scaling up. */}
        <DayChart
          day={day}
          height={380}
          width={sessions.length > 0 ? 1000 : 1700}
          selected={selected >= 0 ? selected : null}
        />
      </div>
      <div className="mt-2">
        <RateStrip day={day} width={sessions.length > 0 ? 1000 : 1700} />
      </div>
    </Panel>
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="font-display text-[21px] font-semibold leading-snug text-ink">
            {day.summary}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {day.synthetic && <Chip tone="warn">Synthetic day</Chip>}
            <span className="font-body text-[13px] text-ink/70">{modelNote}</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          {day.kpis.map((kpi) => (
            <div
              key={kpi.key}
              className="min-w-[160px] flex-1 rounded-el border border-white/10 bg-surface-lowest/60 px-4 py-3"
            >
              <p className="flex items-baseline gap-1.5">
                <span className="font-mono text-[26px] font-bold leading-none tabular-nums text-ink">
                  {figure(kpi.value)}
                </span>
                {kpi.unit && (
                  <span className="font-mono text-[13px] readout text-ink/70">
                    {kpi.unit}
                  </span>
                )}
              </p>
              <p className="mt-1 font-body text-[13px] text-ink">{kpi.label}</p>
              {kpi.note && (
                <p className="mt-0.5 font-body text-[13px] text-ink/60">
                  {kpi.note}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {sessions.length === 0 ? (
        <>
          {wholeDay}
          <Panel className="!p-5" eyebrow="Sessions" title="Sessions">
            <p className="font-body text-[13px] text-ink/70">
              No session was recorded on this day
            </p>
          </Panel>
        </>
      ) : (
        <div className="grid gap-4 wide:grid-cols-[minmax(0,62fr)_minmax(0,38fr)]">
          {wholeDay}

          <div className="flex flex-col gap-4">
            {session && (
              <Panel
                className="!p-5"
                eyebrow="Selected session"
                title={`${session.label} · ${clock(session.start)}–${clock(session.end)}`}
              >
                <DayChart
                  day={day}
                  from={Math.max(0, session.start - 15)}
                  to={Math.min(day.n_minutes, session.end + 20)}
                  height={260}
                  width={640}
                  labels={false}
                />

                <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-body text-[13px]">
                  <dt className="text-ink/60">Average {day.pair.label.toLowerCase()}</dt>
                  <dd className="text-right font-mono tabular-nums text-ink">
                    {figure(session.mean_measured, day.pair.unit)}
                  </dd>
                  <dt className="text-ink/60">Model expected</dt>
                  <dd className="text-right font-mono tabular-nums text-ink">
                    {figure(session.mean_modelled, day.pair.unit)}
                  </dd>
                  <dt className="text-ink/60">Peak</dt>
                  <dd className="text-right font-mono tabular-nums text-ink">
                    {figure(session.peak_measured, day.pair.unit)}
                  </dd>
                  {day.rates.map((rate) => (
                    <FragmentRow
                      key={rate.attribute}
                      label={rate.label}
                      value={figure(session.rate_totals[rate.attribute], rate.unit)}
                    />
                  ))}
                </dl>

                {verdict && (
                  <p
                    className={`mt-3 font-body text-[13px] ${TONE_CLASS[verdict.tone]}`}
                  >
                    {verdict.text}
                  </p>
                )}
              </Panel>
            )}

            <Panel className="!p-5" eyebrow="Sessions" title="Sessions">
              <div className="flex flex-col gap-2">
                {sessions.map((entry, index) => (
                  <button
                    key={`${entry.start}-${entry.end}-${index}`}
                    type="button"
                    aria-pressed={selected === index}
                    onClick={() => {
                      if (index >= 0 && index < sessions.length) setSelectedIndex(index)
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
                      <span className="ml-auto font-mono tabular-nums text-ink/70">
                        avg {figure(entry.mean_measured, day.pair.unit)}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      )}

      <p className="font-body text-[13px] text-ink/60">
        Model estimate, not a clinical tool. Usual error ±{sdFigure(day.model.sd)}
        {day.pair.unit ? ` ${day.pair.unit}` : ''} ({day.model.sd_source}).
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
