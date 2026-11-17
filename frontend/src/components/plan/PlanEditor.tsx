/**
 * PlanEditor — the Day column, one column per session, the add column, the
 * timeline and the action row.
 *
 * Every control is a slider or a row of buttons at least 44 px high, and every
 * label, unit and kind comes from the options.  An edit that would overlap
 * another session or leave the waking hours stops under its own control and
 * says why; nothing is silently moved.
 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Chip } from '../ui'
import type { AssessmentOptions, Entries } from '../../twin/assessment'
import { DAYS_PER_WEEK_RANGE } from '../../twin/assessment'
import { HealthColumn } from './HealthColumn'
import type { Plan, PlanEdit, PlanOptions } from '../../twin/planDay'
import {
  AWAKE_END_RANGE,
  AWAKE_START_RANGE,
  addSession,
  planFromOptions,
  removeSession,
  sessionHour,
  setAwakeEnd,
  setAwakeStart,
  setCount,
  setDay,
  setIntensity,
  setKind,
  setLength,
  setStart,
  setTarget,
  targetOf,
  targetRange,
  unitText,
} from '../../twin/planDay'

interface Props {
  options: PlanOptions
  plan: Plan
  onChange: (plan: Plan) => void
  onRun: (plan: Plan) => void
  running: boolean
  status: string
  /** A refused plan, under the control its field maps to. */
  refused?: { control: string | null; message: string } | null
  /** The health column and its entries, when the lamina declares the view. */
  health?: {
    options: AssessmentOptions
    entries: Entries
    onEdit: () => void
    onFillExample: () => void
    onClear: () => void
  } | null
  /** Session days a week, when the assessment view is available. */
  daysPerWeek?: {
    value: number
    onChange: (value: number) => void
  } | null
}

const KIND_FILL = [
  'fill-day-g0',
  'fill-day-g1',
  'fill-day-g2',
  'fill-day-g3',
] as const

const KIND_BORDER = [
  'border-day-g0',
  'border-day-g1',
  'border-day-g2',
  'border-day-g3',
] as const

function kindSlot(options: PlanOptions, id: string): number {
  return options.kinds.findIndex((kind) => kind.id === id)
}

function kindFill(options: PlanOptions, id: string): string {
  const index = kindSlot(options, id)
  return index >= 0 && index < KIND_FILL.length ? KIND_FILL[index] : 'fill-day-other'
}

function kindBorder(options: PlanOptions, id: string): string {
  const index = kindSlot(options, id)
  return index >= 0 && index < KIND_BORDER.length
    ? KIND_BORDER[index]
    : 'border-day-other'
}

function kindLabel(options: PlanOptions, id: string): string {
  return options.kinds.find((kind) => kind.id === id)?.label ?? id
}

function hhmm(minute: number): string {
  const rounded = Math.round(minute)
  const hours = Math.floor(rounded / 60) % 24
  const minutes = ((rounded % 60) + 60) % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

function axisTime(minute: number): string {
  return minute >= 1440 ? '24:00' : hhmm(minute)
}

function figure(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString('en-GB')
    : value.toLocaleString('en-GB', { maximumFractionDigits: 1 })
}

function withUnit(value: string, unit: string): string {
  const shown = unitText(unit)
  return shown ? `${value} ${shown}` : value
}

function sessionsKeys(count: number): string[] {
  const keys: string[] = []
  for (let index = 0; index < count; index += 1) {
    keys.push(
      `s${index}-start`,
      `s${index}-len`,
      `s${index}-level`,
      `s${index}-target`,
      `s${index}-steps`,
      `s${index}-kind`,
    )
  }
  return keys
}

export const FOCUS_CLASS =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oxy-container'

interface SliderProps {
  label: string
  valueText: string
  min: number
  max: number
  step: number
  value: number
  onChange: (value: number) => void
  ariaLabel: string
  note?: string
  after?: ReactNode
  message?: string
}

/** One labelled slider, its note under it and its own status line. */
function Slider({
  label,
  valueText,
  min,
  max,
  step,
  value,
  onChange,
  ariaLabel,
  note,
  after,
  message,
}: SliderProps) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-[13px] text-ink/70">
        <span className="text-[13px]">{label}</span>
        <span className="text-right font-mono text-[13px] font-bold text-ink">
          {valueText}
        </span>
      </div>
      <input
        type="range"
        className={`plan-range ${FOCUS_CLASS}`}
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={ariaLabel}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {note && (
        <p className="-mt-1.5 mb-0.5 font-mono text-[13px] leading-[18px] text-ink/50">
          {note}
        </p>
      )}
      {after}
      <div
        role="status"
        className={`font-mono text-[13px] leading-[18px] text-warn-strong ${message ? '-mt-1 mb-1' : ''}`}
      >
        {message ?? ''}
      </div>
    </div>
  )
}

interface TimelineProps {
  options: PlanOptions
  plan: Plan
}

/** The day's waking hours and session bands, at the container's pixel width. */
function Timeline({ options, plan }: TimelineProps) {
  const host = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)

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

  const W = Math.max(240, width || 720)
  const H = 76
  const L = 8
  const R = 8
  const T = 6
  const B = 24
  const ph = H - T - B
  const x = (minute: number) => L + (minute / 1440) * (W - L - R)

  const ticks = [0, 3, 6, 9, 12, 15, 18, 21, 24]

  return (
    <div ref={host} className="mt-3.5">
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Plan timeline"
        className="block w-full"
      >
        <rect
          x={x(plan.awake[0])}
          y={T}
          width={Math.max(1, x(plan.awake[1]) - x(plan.awake[0]))}
          height={ph}
          className="fill-surface-mid stroke-white/15"
        />
        {ticks.map((hour) => {
          const minute = hour * 60
          return (
            <g key={hour}>
              <line
                x1={x(minute)}
                x2={x(minute)}
                y1={T}
                y2={H - B - 6}
                className="stroke-ink"
                strokeOpacity={0.15}
              />
              {(W >= 600 || hour % 6 === 0) && (
                <text
                  x={x(minute)}
                  y={H - 6}
                  fontSize={13}
                  textAnchor={hour === 0 ? 'start' : hour === 24 ? 'end' : 'middle'}
                  className="fill-ink"
                  fillOpacity={0.7}
                >
                  {axisTime(minute)}
                </text>
              )}
            </g>
          )
        })}
        {plan.sessions.map((session, index) => {
          const a = x(session.start)
          const b = x(session.start + session.minutes)
          const band = Math.max(2, b - a)
          const bandHeight = ph - 8
          const cy = T + 4 + bandHeight / 2
          const label = kindLabel(options, session.kind)
          const inside = band > label.length * 8 + 12
          return (
            <g key={`session-${index}`}>
              <rect
                x={a}
                y={T + 4}
                width={band}
                height={bandHeight}
                rx={3}
                className={kindFill(options, session.kind)}
              />
              {inside ? (
                <text
                  x={a + band / 2}
                  y={cy + 4}
                  fontSize={13}
                  fontWeight={600}
                  textAnchor="middle"
                  className="fill-[#04202a]"
                >
                  {label}
                </text>
              ) : b + label.length * 8 + 6 < W ? (
                <text x={b + 5} y={cy + 4} fontSize={13} className="fill-ink">
                  {label}
                </text>
              ) : (
                <text
                  x={a - 5}
                  y={cy + 4}
                  fontSize={13}
                  textAnchor="end"
                  className="fill-ink"
                >
                  {label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export function PlanEditor({
  options,
  plan,
  onChange,
  onRun,
  running,
  status,
  refused = null,
  health = null,
  daysPerWeek = null,
}: Props) {
  const [messages, setMessages] = useState<Record<string, string>>({})

  const change = (key: string, edit: PlanEdit) => {
    setMessages({ [key]: edit.message })
    onChange(edit.plan)
  }

  const refusedUnder = (key: string): string | undefined =>
    refused && refused.control === key ? refused.message : undefined

  const knownControls = new Set<string>([
    'awake-start',
    'awake-end',
    'ambient',
    'level',
    'count_outside',
    'add',
    ...sessionsKeys(plan.sessions.length),
  ])
  const refusedAtActionRow =
    refused !== null &&
    (refused.control === null || !knownControls.has(refused.control))

  const reset = () => {
    setMessages({})
    onChange(planFromOptions(options))
  }

  const ambient = options.day.ambient
  const level = options.day.level
  const countOutside = options.day.count_outside
  const countUnit = countOutside.unit
  const sessions = plan.sessions
  const trial = addSession(plan, options)
  const canAdd = trial.plan.sessions.length > sessions.length

  return (
    <section className="rounded-card border border-white/10 bg-surface-low/80 p-5 shadow-inset1">
      <div className="mb-2.5 flex flex-wrap items-center gap-3">
        <h2 className="font-display text-[17px] font-semibold text-ink">Setup</h2>
        <Chip tone="oxy">{options.subject_label}</Chip>
      </div>

      <div className="flex items-stretch gap-4 overflow-x-auto pb-1.5 phone:flex-col phone:overflow-visible">
        {health && (
          <HealthColumn
            options={health.options}
            entries={health.entries}
            onEdit={health.onEdit}
            onFillExample={health.onFillExample}
            onClear={health.onClear}
          />
        )}

        <div className="w-[440px] flex-none rounded-xl border border-white/10 bg-surface-mid px-4 pb-2 pt-3 phone:w-full">
          <div className="mb-1 flex min-h-[44px] items-center">
            <h3 className="font-display text-[16px] font-semibold text-ink">Day</h3>
          </div>
          <div className="grid grid-cols-2 gap-x-5 phone:grid-cols-1">
            <Slider
              label="Awake from"
              valueText={hhmm(plan.awake[0])}
              min={AWAKE_START_RANGE[0]}
              max={AWAKE_START_RANGE[1]}
              step={5}
              value={plan.awake[0]}
              ariaLabel="Awake from"
              message={refusedUnder('awake-start') ?? messages['awake-start']}
              onChange={(value) => change('awake-start', setAwakeStart(plan, value))}
            />
            <Slider
              label="Awake until"
              valueText={hhmm(plan.awake[1])}
              min={AWAKE_END_RANGE[0]}
              max={AWAKE_END_RANGE[1]}
              step={5}
              value={plan.awake[1]}
              ariaLabel="Awake until"
              message={refusedUnder('awake-end') ?? messages['awake-end']}
              onChange={(value) => change('awake-end', setAwakeEnd(plan, value))}
            />
            <Slider
              label={options.roles.ambient.label}
              valueText={withUnit(figure(plan.ambient), ambient.unit)}
              min={ambient.min}
              max={ambient.max}
              step={1}
              value={plan.ambient}
              ariaLabel={options.roles.ambient.label}
              message={refusedUnder('ambient')}
              onChange={(value) => change('ambient', setDay(plan, 'ambient', value, options))}
            />
            <Slider
              label={options.roles.level.label}
              valueText={withUnit(plan.level.toFixed(1), level.unit)}
              min={level.min}
              max={level.max}
              step={0.5}
              value={plan.level}
              ariaLabel={options.roles.level.label}
              message={refusedUnder('level')}
              note={
                level.recorded
                  ? `recorded ${figure(level.recorded[0])}–${figure(level.recorded[1])}`
                  : undefined
              }
              onChange={(value) => change('level', setDay(plan, 'level', value, options))}
            />
            <Slider
              label="Steps outside"
              valueText={withUnit(figure(plan.count_outside), countUnit)}
              min={countOutside.min}
              max={countOutside.max}
              step={100}
              value={plan.count_outside}
              ariaLabel="Steps outside sessions"
              message={refusedUnder('count_outside')}
              note={`p10 ${figure(countOutside.p10)} · p90 ${figure(countOutside.p90)}`}
              onChange={(value) =>
                change('count_outside', setDay(plan, 'count_outside', value, options))
              }
            />
          </div>
        </div>

        {sessions.map((session, index) => {
          const kind = options.kinds[kindSlot(options, session.kind)]
          const range = kind ? targetRange(kind, sessionHour(session)) : [0, 0]
          const target = targetOf(plan, index, options)
          const typical = kind && kind.intensity.p90 > kind.intensity.p10
            ? ((kind.intensity.p50 - kind.intensity.p10) /
                (kind.intensity.p90 - kind.intensity.p10)) *
              100
            : 50
          const typicalAt = Math.max(0, Math.min(100, typical))
          const stepsMax = kind
            ? Math.round(kind.steps_per_min * 180 * 1.5)
            : 0

          return (
            <div
              key={`session-${index}`}
              className="w-[440px] flex-none rounded-xl border border-l-[5px] border-white/10 bg-surface-mid px-4 pb-2 pt-3 phone:w-full"
            >
              <div className="mb-1 flex min-h-[44px] items-center justify-between gap-2">
                <h3 className="font-display text-[16px] font-semibold text-ink">
                  Session {index + 1}
                </h3>
                <button
                  type="button"
                  aria-label={`Remove session ${index + 1}`}
                  onClick={() => {
                    setMessages({})
                    onChange(removeSession(plan, index).plan)
                  }}
                  className={`min-h-[44px] min-w-[44px] rounded-el border border-white/10 bg-surface-low text-[22px] leading-none text-ink/70 transition-colors hover:text-ink ${FOCUS_CLASS}`}
                >
                  ×
                </button>
              </div>

              <div
                role="group"
                aria-label={`Kind of session ${index + 1}`}
                className="mb-1 flex flex-wrap gap-1.5"
              >
                {options.kinds.map((entry) => {
                  const selected = entry.id === session.kind
                  return (
                    <button
                      key={entry.id}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => {
                        setMessages({})
                        onChange(setKind(plan, index, entry.id, options).plan)
                      }}
                      className={`min-h-[44px] flex-1 rounded-el border px-2 text-[13px] transition-colors ${FOCUS_CLASS} ${
                        selected
                          ? `${kindBorder(options, entry.id)} bg-surface-high text-ink shadow-inset1`
                          : 'border-white/10 bg-surface-low text-ink/70 hover:text-ink'
                      }`}
                    >
                      {entry.label}
                    </button>
                  )
                })}
              </div>
              <div
                role="status"
                className="min-h-[18px] font-mono text-[13px] leading-[18px] text-warn-strong"
              >
                {refusedUnder(`s${index}-kind`) ?? ''}
              </div>

              <div className="grid grid-cols-2 gap-x-5 phone:grid-cols-1">
                <Slider
                  label="Start"
                  valueText={hhmm(session.start)}
                  min={plan.awake[0]}
                  max={plan.awake[1] - session.minutes}
                  step={5}
                  value={session.start}
                  ariaLabel={`Start of session ${index + 1}`}
                  message={refusedUnder(`s${index}-start`) ?? messages[`s${index}-start`]}
                  onChange={(value) =>
                    change(`s${index}-start`, setStart(plan, index, value))
                  }
                />
                <Slider
                  label="Length"
                  valueText={`${session.minutes} min`}
                  min={options.limits.session_minutes[0]}
                  max={Math.max(
                    options.limits.session_minutes[0],
                    Math.min(
                      options.limits.session_minutes[1],
                      plan.awake[1] - session.start,
                    ),
                  )}
                  step={5}
                  value={session.minutes}
                  ariaLabel={`Length of session ${index + 1}`}
                  message={refusedUnder(`s${index}-len`) ?? messages[`s${index}-len`]}
                  onChange={(value) =>
                    change(`s${index}-len`, setLength(plan, index, value, options))
                  }
                />

                <Slider
                  label={options.roles.intensity.label}
                  valueText={withUnit(session.intensity.toFixed(2), kind?.intensity.unit ?? '')}
                  min={kind?.intensity.p10 ?? 0}
                  max={kind?.intensity.p90 ?? 0}
                  step={0.01}
                  value={session.intensity}
                  ariaLabel={`${options.roles.intensity.label} of session ${index + 1}`}
                  message={refusedUnder(`s${index}-level`)}
                  after={
                    <div className="relative -mt-1.5 mb-1.5 flex justify-between px-0.5 text-[13px] text-ink/50">
                      <span>{typicalAt < 30 ? '' : 'light'}</span>
                      <span
                        className="absolute -translate-x-1/2 text-ink/70"
                        style={{ left: `${typicalAt}%` }}
                      >
                        typical
                      </span>
                      <span>{typicalAt > 70 ? '' : 'hard'}</span>
                    </div>
                  }
                  onChange={(value) =>
                    change(`s${index}-level`, setIntensity(plan, index, value, options))
                  }
                />

                <Slider
                  label={options.roles.settles.label}
                  valueText={withUnit(String(target), options.roles.settles.unit)}
                  min={range[0]}
                  max={range[1]}
                  step={1}
                  value={target}
                  ariaLabel={`${options.roles.settles.label} in session ${index + 1}`}
                  message={refusedUnder(`s${index}-target`)}
                  onChange={(value) =>
                    change(`s${index}-target`, setTarget(plan, index, value, options))
                  }
                />
                <Slider
                  label={options.roles.count.label}
                  valueText={withUnit(figure(session.count), countUnit)}
                  min={0}
                  max={stepsMax}
                  step={10}
                  value={session.count}
                  ariaLabel={`${options.roles.count.label} in session ${index + 1}`}
                  message={refusedUnder(`s${index}-steps`)}
                  note="no effect on heart rate"
                  onChange={(value) =>
                    change(`s${index}-steps`, setCount(plan, index, value, options))
                  }
                />
              </div>
            </div>
          )
        })}

        <div className="flex w-[220px] flex-none flex-col items-center justify-center gap-2.5 rounded-xl border-2 border-dashed border-white/15 p-3 phone:w-full">
          <button
            type="button"
            disabled={!canAdd}
            onClick={() => change('add', addSession(plan, options))}
            className={`min-h-[52px] w-full rounded-el border border-white/10 bg-surface-low px-3 text-[16px] font-semibold text-ink/80 transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_CLASS}`}
          >
            + Session
          </button>
          <p
            role="status"
            className="min-h-[18px] font-mono text-[13px] leading-[18px] text-warn-strong"
          >
            {refusedUnder('add') ?? trial.message}
          </p>
        </div>
      </div>

      <Timeline options={options} plan={plan} />

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => onRun(plan)}
          disabled={running}
          className={`min-h-[52px] min-w-[130px] rounded-el border border-transparent bg-oxy-container px-4 text-[16px] font-bold text-[#04202a] transition-opacity disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_CLASS}`}
        >
          Run
        </button>
        {daysPerWeek && (
          <>
            <span className="font-body text-[14px] text-ink/70">Repeat this day</span>
            <span className="inline-flex items-center gap-1.5">
              <button
                type="button"
                aria-label="One day fewer"
                disabled={daysPerWeek.value <= DAYS_PER_WEEK_RANGE[0]}
                onClick={() => daysPerWeek.onChange(daysPerWeek.value - 1)}
                className={`min-h-[44px] min-w-[44px] rounded-el border border-white/10 bg-surface-low text-[18px] font-bold leading-none text-ink/80 transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_CLASS}`}
              >
                −
              </button>
              <output className="min-w-[28px] text-center font-mono text-[18px] font-bold tabular-nums text-ink">
                {daysPerWeek.value}
              </output>
              <button
                type="button"
                aria-label="One day more"
                disabled={daysPerWeek.value >= DAYS_PER_WEEK_RANGE[1]}
                onClick={() => daysPerWeek.onChange(daysPerWeek.value + 1)}
                className={`min-h-[44px] min-w-[44px] rounded-el border border-white/10 bg-surface-low text-[18px] font-bold leading-none text-ink/80 transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_CLASS}`}
              >
                +
              </button>
            </span>
            <span className="font-body text-[14px] text-ink/70">days a week</span>
          </>
        )}
        <button
          type="button"
          onClick={reset}
          className={`min-h-[44px] rounded-el border border-white/10 bg-surface-low px-4 text-[14px] font-semibold text-ink/70 transition-colors hover:text-ink ${FOCUS_CLASS}`}
        >
          Reset to a typical day
        </button>
        <span role="status" className="font-mono text-[13px] readout text-ink/70">
          {status}
        </span>
      </div>
      {refusedAtActionRow && refused && (
        <p
          role="alert"
          className="mt-2 font-mono text-[13px] leading-[18px] text-warn-strong"
        >
          {refused.message}
        </p>
      )}
    </section>
  )
}
