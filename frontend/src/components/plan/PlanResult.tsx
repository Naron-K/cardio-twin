/**
 * PlanResult — the projection's two cards: the chart and its playback on the
 * left, the limits, figures and session results on the right.
 *
 * Nothing here names an attribute, unit or kind: the title, legend, units and
 * labels come from the day summary and the options.  The chart is drawn to the
 * container's measured width so its 13 px labels keep their size.
 */
import { useEffect, useId, useRef, useState } from 'react'
import type { DaySummary } from '../../twin/dayView'
import {
  PLAY_SPEEDS,
  clock,
  groupColourIndex,
  totalTo,
  valueAt,
} from '../../twin/dayView'
import type { PlanOptions, PlannedExtras } from '../../twin/planDay'
import { unitText } from '../../twin/planDay'
import { DayChart } from '../day/DayChart'
import { RateStrip } from '../day/RateStrip'

interface Props {
  day: DaySummary
  extras: PlannedExtras
  options: PlanOptions
  awake: [number, number]
  cursor: number
  playing: boolean
  speed: number
  onTogglePlay: () => void
  onSpeed: (speed: number) => void
  onSeek: (minute: number) => void
  /** The setup changed since this result: draw it faintly. */
  dimmed?: boolean
}

const KIND_BORDER = [
  'border-day-g0',
  'border-day-g1',
  'border-day-g2',
  'border-day-g3',
] as const

const KIND_BG = [
  'bg-day-g0',
  'bg-day-g1',
  'bg-day-g2',
  'bg-day-g3',
] as const

const KIND_TEXT = [
  'text-day-g0',
  'text-day-g1',
  'text-day-g2',
  'text-day-g3',
] as const

const FOCUS_CLASS =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oxy-container'

function slot(day: DaySummary, group: string): number {
  return groupColourIndex(day, group)
}

function kindBorder(day: DaySummary, group: string): string {
  const index = slot(day, group)
  return index >= 0 && index < KIND_BORDER.length
    ? KIND_BORDER[index]
    : 'border-day-other'
}

function kindBackground(day: DaySummary, group: string): string {
  const index = slot(day, group)
  return index >= 0 && index < KIND_BG.length ? KIND_BG[index] : 'bg-day-other'
}

function kindText(day: DaySummary, group: string): string {
  const index = slot(day, group)
  return index >= 0 && index < KIND_TEXT.length ? KIND_TEXT[index] : 'text-day-other'
}

function figure(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const rounded =
    Math.abs(value) < 20 && !Number.isInteger(value)
      ? value.toLocaleString('en-GB', { maximumFractionDigits: 1 })
      : Math.round(value).toLocaleString('en-GB')
  return rounded
}

function amount(value: number | null | undefined, unit: string): string {
  const shown = unitText(unit)
  const number = figure(value)
  if (number === '—') return number
  return shown ? `${number} ${shown}` : number
}

function kpiValue(value: number | null, unit: string): string {
  const number = figure(value)
  if (number === '—') return number
  const shown = unitText(unit)
  return shown ? `${number} ${shown}` : number
}

/** The card before the first run: a faint day axis and the invitation. */
export function PlanEmpty({ running = false }: { running?: boolean }) {
  return (
    <section className="rounded-card border border-white/10 bg-surface-low/80 p-5">
      <h2 className="font-display text-[17px] font-semibold text-ink">
        Projection
      </h2>
      <div className="relative mt-3 h-[220px] overflow-hidden rounded-el border border-white/5 bg-surface-lowest/40">
        <div className="absolute inset-x-4 bottom-9 top-4 flex">
          {Array.from({ length: 24 }, (_, hour) => (
            <div
              key={hour}
              className="relative flex-1 border-l border-ink/10 first:border-l-0"
            />
          ))}
        </div>
        <div className="absolute inset-x-4 bottom-3 flex justify-between font-mono text-[13px] tabular-nums text-ink/30">
          <span>00:00</span>
          <span>06:00</span>
          <span>12:00</span>
          <span>18:00</span>
          <span>24:00</span>
        </div>
        <p className="absolute inset-0 flex items-center justify-center font-body text-[13px] text-ink/60">
          {running ? 'Running…' : 'Set up the day, then Run'}
        </p>
      </div>
    </section>
  )
}

export function PlanResult({
  day,
  extras,
  options,
  awake,
  cursor,
  playing,
  speed,
  onTogglePlay,
  onSpeed,
  onSeek,
  dimmed = false,
}: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const [limitsOpen, setLimitsOpen] = useState(false)
  const limitsId = useId()

  useEffect(() => {
    const node = host.current
    if (!node) return
    const measure = () => setWidth(node.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const W = Math.max(300, width || 720)
  const sd = amount(day.model.sd, day.pair.unit)
  const at = Math.min(
    Math.max(awake[0], awake[1] - 1),
    Math.max(awake[0], Math.floor(cursor)),
  )
  const inSession =
    day.sessions.find((entry) => at >= entry.start && at < entry.end) ?? null
  const kindLabel = inSession ? inSession.group_label || inSession.label : 'No session'
  const heartNow = valueAt(day.pair.modelled, at, 1)

  const energyKpi = day.kpis[0]
  const stepsKpi = day.kpis[1]
  const energyRate = energyKpi
    ? day.rates.find((rate) => rate.attribute === energyKpi.key)
    : undefined
  const stepsRate = stepsKpi
    ? day.rates.find((rate) => rate.attribute === stepsKpi.key)
    : undefined
  const energySoFar = energyRate ? totalTo(energyRate.values, at) : null
  const stepsSoFar = stepsRate ? totalTo(stepsRate.values, at) : null

  const readout = [
    clock(at),
    kindLabel,
    amount(heartNow, day.pair.unit),
    energySoFar === null ? '—' : amount(energySoFar, energyRate?.unit ?? ''),
    stepsSoFar === null ? '—' : amount(stepsSoFar, stepsRate?.unit ?? ''),
  ].join(' · ')

  const playLabel = playing
    ? 'Pause'
    : cursor >= awake[1]
      ? 'Play again'
      : 'Play'

  const limitButton = (
    <button
      type="button"
      aria-expanded={limitsOpen}
      aria-controls={limitsId}
      onClick={() => setLimitsOpen((open) => !open)}
      className={`min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-3 font-mono text-[13px] font-bold readout uppercase text-ink/70 transition-colors hover:text-ink ${FOCUS_CLASS}`}
    >
      Limits
    </button>
  )

  return (
    <div
      className={`grid gap-4 fit:grid-cols-[minmax(0,1.7fr)_minmax(360px,1fr)] ${
        dimmed ? 'pointer-events-none opacity-35' : ''
      }`}
    >
      <section className="rounded-card border border-white/10 bg-surface-low/80 p-5">
        <h2 className="font-display text-[17px] font-semibold text-ink">
          {day.pair.label} · projection
        </h2>

        <div className="my-2 flex flex-wrap items-center gap-x-[18px] gap-y-2 font-body text-[13px] text-ink/70">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0 w-[22px] border-t-[3px] border-dashed border-day-model align-middle" />
            Model projection
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-[22px] rounded-sm bg-day-band align-middle" />±{' '}
            {sd} usual error
          </span>
          {options.kinds.map((kind) => (
            <span key={kind.id} className="flex items-center gap-1.5">
              <span
                className={`inline-block h-3 w-[22px] rounded-sm align-middle ${kindBackground(day, kind.id)}`}
              />
              <span className={kindText(day, kind.id)}>{kind.label}</span>
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="plan-hatch inline-block h-3 w-[22px] rounded-sm border border-white/15 align-middle" />
            No projection
          </span>
        </div>

        <div ref={host}>
          <DayChart
            day={day}
            gapLabel="No projection"
            width={W}
            height={300}
            until={cursor}
          />
          <div className="mt-2">
            <RateStrip day={day} width={W} until={cursor} />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            onClick={onTogglePlay}
            className={`min-h-[44px] min-w-[104px] rounded-el border border-oxy-container/60 px-3 font-mono text-[13px] font-bold readout uppercase text-oxy transition-colors hover:bg-oxy-container/15 ${FOCUS_CLASS}`}
          >
            {playLabel}
          </button>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Playback speed">
            {PLAY_SPEEDS.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={speed === value}
                onClick={() => onSpeed(value)}
                className={`min-h-[44px] min-w-[52px] rounded-el border px-2 font-mono text-[13px] font-bold readout uppercase transition-colors ${FOCUS_CLASS} ${
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
            min={awake[0]}
            max={awake[1]}
            step={1}
            value={Math.max(awake[0], Math.min(awake[1], Math.floor(cursor)))}
            onChange={(event) => onSeek(Number(event.target.value))}
            className={`plan-range min-w-[140px] flex-1 ${FOCUS_CLASS}`}
          />
          <p className="min-h-[20px] flex-[1_0_100%] font-mono text-[13px] tabular-nums text-ink/70">
            {readout}
          </p>
        </div>
      </section>

      <section className="rounded-card border border-white/10 bg-surface-low/80 p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2.5 rounded-el border border-warn-strong px-3 py-2.5 font-body text-[13px] text-ink/70">
          <span>
            Projection from a plan · {day.subject_label}&apos;s model · not measured
          </span>
          {limitButton}
        </div>

        {limitsOpen && (
          <ul
            id={limitsId}
            className="mb-3 list-disc pl-5 font-body text-[13px] text-ink/70"
          >
            {extras.limits_text.map((line, index) => (
              <li key={`${line}-${index}`} className="my-0.5">
                {line}
              </li>
            ))}
          </ul>
        )}

        <div className="mb-4 grid grid-cols-2 gap-3">
          {day.kpis.map((kpi) => (
            <div key={kpi.key} className="rounded-el bg-surface-mid px-3.5 py-3">
              <b className="block font-mono text-[24px] font-bold leading-tight tabular-nums text-ink">
                {kpiValue(kpi.value, kpi.unit)}
              </b>
              <span className="font-body text-[13px] text-ink/70">{kpi.label}</span>
              {kpi.note && (
                <small className="block font-mono text-[13px] tabular-nums text-ink/50">
                  {kpi.note}
                </small>
              )}
            </div>
          ))}
        </div>

        <h2 className="mb-2.5 font-display text-[17px] font-semibold text-ink">
          Session results
        </h2>
        <div className="grid gap-2.5">
          {day.sessions.length === 0 ? (
            <p className="font-body text-[13px] text-ink/70">No sessions</p>
          ) : (
            day.sessions.map((session, index) => {
              const planned = extras.sessions.find(
                (entry) => entry.start === session.start,
              )
              return (
                <button
                  key={`${session.start}-${session.end}-${index}`}
                  type="button"
                  onClick={() => onSeek(session.start)}
                  className={`min-h-[64px] w-full rounded-el border border-l-[5px] border-white/10 bg-surface-mid px-3.5 py-3 text-left font-body text-[15px] text-ink transition-colors hover:bg-surface-high ${kindBorder(day, session.group)} ${FOCUS_CLASS}`}
                >
                  <h3 className="mb-1.5 font-display text-[15px] font-semibold text-ink">
                    {session.group_label || session.label} · {clock(session.start)}–
                    {clock(session.end)} · {session.minutes} min
                  </h3>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
                    <dt className="font-body text-[13px] text-ink/70">
                      Settles near
                    </dt>
                    <dd className="text-right font-mono text-[13px] font-bold tabular-nums text-ink">
                      {amount(planned?.target_set ?? null, day.pair.unit)}
                    </dd>
                    <dt className="font-body text-[13px] text-ink/70">
                      Model mean
                    </dt>
                    <dd className="text-right font-mono text-[13px] font-bold tabular-nums text-ink">
                      {amount(session.mean_modelled, day.pair.unit)}
                    </dd>
                    <dt className="font-body text-[13px] text-ink/70">
                      Model peak
                    </dt>
                    <dd className="text-right font-mono text-[13px] font-bold tabular-nums text-ink">
                      {amount(planned?.peak_modelled ?? null, day.pair.unit)}
                    </dd>
                    {energyRate && (
                      <>
                        <dt className="font-body text-[13px] text-ink/70">
                          {energyRate.label}
                        </dt>
                        <dd className="text-right font-mono text-[13px] font-bold tabular-nums text-ink">
                          {amount(
                            session.rate_totals[energyRate.attribute],
                            energyRate.unit,
                          )}
                        </dd>
                      </>
                    )}
                    {stepsRate && (
                      <>
                        <dt className="font-body text-[13px] text-ink/70">
                          {stepsRate.label}
                        </dt>
                        <dd className="text-right font-mono text-[13px] font-bold tabular-nums text-ink">
                          {amount(
                            session.rate_totals[stepsRate.attribute],
                            stepsRate.unit,
                          )}
                        </dd>
                      </>
                    )}
                  </dl>
                </button>
              )
            })
          )}
        </div>
      </section>
    </div>
  )
}
