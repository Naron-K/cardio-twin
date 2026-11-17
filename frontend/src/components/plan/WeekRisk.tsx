/**
 * WeekRisk — the week's activity, the risk figures and the flags, drawn from
 * the assessed answer.  Every figure, label and unit comes from the answer or
 * the options; the component holds nothing but the selected horizon and writes
 * nothing.
 *
 * When the answer carries horizons, the screen shows how the figures move over
 * them: one shared scale for every factor, the selected column repeated on the
 * risk cards, and the flags below the grid.  An answer without horizons draws
 * exactly the layout it drew before.
 */
import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type {
  AssessmentAnswer,
  AssessmentDose,
  AssessmentFlag,
  AssessmentMediatorOutcome,
  AssessmentNeed,
  AssessmentRange,
  AssessmentResult,
  HorizonChoice,
  StatusTone,
} from '../../twin/assessment'
import {
  changeText,
  decimalsFor,
  deltaText,
  displayUnit,
  figureText,
  horizonChoices,
  horizonShort,
  mediatorPoint,
  mediatorScale,
  needText,
  scaleTop,
  statusText,
  valueAtHorizon,
} from '../../twin/assessment'
import { FOCUS_CLASS } from './PlanEditor'

interface Props {
  answer: AssessmentAnswer
  onEnter: (attribute: string | null) => void
}

type SourceKind = 'measured' | 'projected' | 'population'

const SOURCE_GLYPH: Record<SourceKind, string> = {
  measured: '■',
  projected: '◆',
  population: '▲',
}

const SOURCE_TONE: Record<SourceKind, string> = {
  measured: 'text-ink',
  projected: 'text-day-model',
  population: 'text-warn-strong',
}

const SMALL_BUTTON =
  'min-h-[44px] rounded-el border border-white/10 bg-surface-low px-3 text-[13px] font-semibold text-ink/80 transition-colors hover:text-ink'

const MED_GRID =
  'grid grid-cols-[minmax(0,1fr)_56px_minmax(0,1fr)_60px] gap-2.5 min-[1100px]:grid-cols-[minmax(0,1.25fr)_64px_minmax(0,1.3fr)_70px]'

const PLACEHOLDER_BADGE =
  'inline-block whitespace-nowrap rounded-md border border-warn-strong/60 bg-warn-strong/10 px-2 py-0.5 text-[13px] font-semibold text-warn'

function percent(value: number, top: number): string {
  return `${(100 * value) / top}%`
}

function firstAttribute(needs: AssessmentNeed[]): string | null {
  for (const need of needs) {
    if ('attribute' in need) return need.attribute
  }
  return null
}

function signedMove(value: number, now: number, places: number): string {
  const delta = value - now
  if (delta === 0) return (0).toFixed(places)
  return `${delta < 0 ? '\u2212' : '+'}${Math.abs(delta).toFixed(places)}`
}

function marksText(choices: HorizonChoice[]): string {
  const marks: number[] = []
  for (const choice of choices) {
    if (!choice.settled && choice.weeks !== null && choice.weeks > 0) {
      marks.push(choice.weeks)
    }
  }
  return marks.length > 0
    ? `Now → settled (marks at ${marks.join(', ')} weeks)`
    : 'Now → settled'
}

function pointX(index: number, count: number): number {
  if (count <= 1) return 50
  return 4 + (92 * index) / (count - 1)
}

function pointY(point: number): number {
  return 17 - 14 * point
}

function SourceLabel({
  kind,
  children,
}: {
  kind: SourceKind
  children: ReactNode
}) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-white/10 px-2 py-0.5 text-[13px] font-semibold text-ink/70">
      <span aria-hidden="true" className={SOURCE_TONE[kind]}>
        {SOURCE_GLYPH[kind]}
      </span>
      {children}
    </span>
  )
}

function StatusBadge({ status }: { status: string | null }) {
  const { text, tone } = statusText(status)
  if (text === '') return null
  const skin = badgeSkin(tone)
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-md border px-2 py-0.5 text-[13px] font-semibold ${skin}`}
    >
      {text}
    </span>
  )
}

function badgeSkin(tone: StatusTone): string {
  if (tone === 'reviewed') {
    return 'border-day-g0/60 bg-day-g0/10 text-day-g0'
  }
  return 'border-warn-strong/60 bg-warn-strong/10 text-warn'
}

function NoticeBox({ children }: { children: ReactNode }) {
  return (
    <div className="mt-1.5 rounded-el border border-dashed border-white/15 px-3 py-2 text-[14px] text-ink/70">
      {children}
    </div>
  )
}

function NeedsBox({
  needs,
  fallback,
  onEnter,
}: {
  needs: AssessmentNeed[]
  fallback: string
  onEnter: (attribute: string | null) => void
}) {
  const labels = needs.map((need) => need.label)
  return (
    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 rounded-el border border-dashed border-white/15 px-3 py-2 text-[14px] text-ink/70">
      <span>
        <b className="font-semibold text-ink">Needs:</b>{' '}
        {labels.length > 0 ? labels.join(', ') : fallback}
      </span>
      {needs.length > 0 && (
        <button
          type="button"
          onClick={() => onEnter(firstAttribute(needs))}
          className={`${SMALL_BUTTON} ${FOCUS_CLASS}`}
        >
          Enter
        </button>
      )}
    </div>
  )
}

function ChangeChip({ result }: { result: AssessmentResult }) {
  const change = changeText(result.change)
  if (change.text === '') return null

  const glyph =
    change.direction === 'down' ? '▼' : change.direction === 'up' ? '▲' : '='
  const skin =
    change.direction === 'down'
      ? 'border-day-g0/50 text-day-g0'
      : change.direction === 'up'
        ? 'border-crimson-container/50 text-crimson'
        : 'border-white/10 text-ink/70'

  return (
    <span
      className={`rounded-el border px-2.5 py-1 font-mono text-[14px] font-bold tabular-nums ${skin}`}
    >
      <span aria-hidden="true">{glyph} </span>
      {change.text}
    </span>
  )
}

function RiskDelta({ value, now }: { value: number; now: number }) {
  const delta = deltaText(value, now)
  const glyph =
    delta.direction === 'down' ? '▼' : delta.direction === 'up' ? '▲' : '='
  const skin =
    delta.direction === 'down'
      ? 'border-day-g0/50 text-day-g0'
      : delta.direction === 'up'
        ? 'border-crimson-container/50 text-crimson'
        : 'border-white/10 text-ink/70'

  return (
    <span
      className={`rounded-el border px-2.5 py-1 font-mono text-[14px] font-bold tabular-nums ${skin}`}
    >
      <span aria-hidden="true">{glyph} </span>
      {delta.text}
    </span>
  )
}

function RiskHead({ result }: { result: AssessmentResult }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2">
      <h3 className="font-display text-[15px] font-semibold text-ink">
        {result.label}{' '}
        <span className="font-body text-[13px] font-normal text-ink/70">
          {result.period}
        </span>
      </h3>
      <StatusBadge status={result.status} />
    </div>
  )
}

function RiskDetails({ result }: { result: AssessmentResult }) {
  return (
    <details className="mt-1.5 text-[13px] text-ink/70">
      <summary
        className={`flex min-h-[44px] cursor-pointer items-center text-ink/70 ${FOCUS_CLASS}`}
      >
        What stands behind it ({result.models.length} steps)
      </summary>
      <div>
        {result.models.map((model) => (
          <div
            key={model.id}
            className="flex justify-between gap-3 border-t border-white/10 py-1 text-[13px]"
          >
            <span>
              {model.name}
              <br />
              <span className="text-ink/70">{model.source}</span>
            </span>
            <b className="font-mono font-bold text-ink">
              {model.status !== '' ? model.status : '–'}
            </b>
          </div>
        ))}
      </div>
    </details>
  )
}

function RiskBody({
  result,
  onEnter,
}: {
  result: AssessmentResult
  onEnter: (attribute: string | null) => void
}) {
  if (result.not_applicable !== null) {
    return <NoticeBox>{result.not_applicable}</NoticeBox>
  }

  if (result.now === null) {
    return (
      <NeedsBox
        needs={result.needs.now}
        fallback={result.reason ?? 'could not be computed'}
        onEnter={onEnter}
      />
    )
  }

  if (result.planned === null) {
    if (result.needs.planned.length > 0) {
      return (
        <NeedsBox
          needs={result.needs.planned}
          fallback={result.reason ?? 'could not be computed'}
          onEnter={onEnter}
        />
      )
    }
    return (
      <NoticeBox>
        <b className="font-semibold text-ink">With a plan:</b> press Run
      </NoticeBox>
    )
  }

  const unit = displayUnit(result.unit)
  return (
    <div className="mt-1.5 flex flex-wrap items-end gap-[18px]">
      <div className="min-w-[120px]">
        <span className="block text-[13px] text-ink/70">Now</span>
        <b className="font-mono text-[30px] font-bold leading-none tabular-nums text-ink">
          {figureText(result.now, 2)}
          {unit !== '' && (
            <small className="text-[16px] font-bold"> {unit}</small>
          )}
        </b>
      </div>
      <div className="min-w-[120px]">
        <span className="block text-[13px] text-ink/70">With this plan</span>
        <b className="font-mono text-[30px] font-bold leading-none tabular-nums text-day-model">
          {figureText(result.planned, 2)}
          {unit !== '' && (
            <small className="text-[16px] font-bold"> {unit}</small>
          )}
        </b>
      </div>
      <ChangeChip result={result} />
    </div>
  )
}

function RiskRow({
  result,
  onEnter,
}: {
  result: AssessmentResult
  onEnter: (attribute: string | null) => void
}) {
  const reasonInBody =
    result.not_applicable === null &&
    (result.now === null ||
      (result.now !== null &&
        result.planned === null &&
        result.needs.planned.length > 0))

  return (
    <div className="mt-2.5 border-t border-white/10 pt-3">
      <RiskHead result={result} />

      <RiskBody result={result} onEnter={onEnter} />

      {result.reason !== null && !reasonInBody && (
        <p className="mt-1.5 text-[13px] text-ink/70">{result.reason}</p>
      )}

      <RiskDetails result={result} />
    </div>
  )
}

function FlagRow({
  flag,
  onEnter,
  bordered = true,
}: {
  flag: AssessmentFlag
  onEnter: (attribute: string | null) => void
  bordered?: boolean
}) {
  const border = bordered ? 'border-t border-white/10 first:border-t-0' : ''
  const row = `flex gap-2.5 py-2.5 text-[14px] ${border}`

  if (flag.state === 'raised') {
    return (
      <div className={row}>
        <span
          aria-hidden="true"
          className="grid h-[26px] w-[26px] flex-none place-items-center rounded-md border border-warn-strong/60 bg-warn-strong/20 text-[13px] font-bold text-warn"
        >
          ▲
        </span>
        <div>
          <b className="block text-ink">{flag.label}</b>
          <span className="text-ink/70">{flag.text}</span>
          <div className="mt-1">
            <StatusBadge status={flag.status} />
          </div>
        </div>
      </div>
    )
  }

  if (flag.state === 'clear') {
    return (
      <div className={row}>
        <span
          aria-hidden="true"
          className="grid h-[26px] w-[26px] flex-none place-items-center rounded-md border border-day-g0/50 bg-day-g0/15 text-[13px] font-bold text-day-g0"
        >
          ✓
        </span>
        <div>
          <b className="block text-ink">{flag.topic}</b>
          <span className="text-ink/70">No flag from what you entered.</span>
        </div>
      </div>
    )
  }

  const labels = flag.needs.map((need) => need.label)
  return (
    <div className={row}>
      <span
        aria-hidden="true"
        className="grid h-[26px] w-[26px] flex-none place-items-center rounded-md border border-dashed border-white/15 text-[13px] font-bold text-ink/70"
      >
        ?
      </span>
      <div>
        <b className="block text-ink">{flag.topic}</b>
        <span className="text-ink/70">
          {labels.length > 0
            ? `Not answered. Needs: ${labels.join(', ')}`
            : 'Not answered.'}
        </span>
        {flag.needs.length > 0 && (
          <div className="mt-1">
            <button
              type="button"
              onClick={() => onEnter(firstAttribute(flag.needs))}
              className={`${SMALL_BUTTON} ${FOCUS_CLASS}`}
            >
              Enter
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function WeeklyPanel({
  dose,
  range,
}: {
  dose: AssessmentDose
  range: AssessmentRange | null
}) {
  const current = dose.current
  const planned = dose.planned
  const top = scaleTop(dose, range)
  const unit = displayUnit(dose.unit)
  const ticks = Array.from({ length: Math.floor(top / 5) + 1 }, (_, index) => index * 5)

  const spoken: string[] = []
  if (current !== null) {
    spoken.push(
      `Now ${figureText(current.p50)}, median of ${current.weeks} weeks`,
      `usual range ${figureText(current.p10)} to ${figureText(current.p90)}`,
    )
  }
  if (planned !== null) {
    spoken.push(`with this plan ${figureText(planned.value)}`)
  }
  if (range !== null) {
    spoken.push(`${range.label} ${figureText(range.low)} to ${figureText(range.high)}`)
  }
  const scaleLabel = `Weekly activity in ${unit !== '' ? unit : 'units'} from 0 to ${top}. ${spoken.join('. ')}`

  return (
    <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-[16px] font-semibold text-ink">
          Weekly activity
        </h3>
        <span className="font-mono text-[13px] text-ink/70">{unit}</span>
      </div>

      <div
        className="relative mx-2 mt-2 h-4 font-mono text-[13px] text-ink/70"
        aria-hidden="true"
      >
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute -translate-x-1/2"
            style={{ left: percent(tick, top) }}
          >
            {tick}
          </span>
        ))}
      </div>

      <div
        role="img"
        aria-label={scaleLabel}
        className="relative mx-2 mt-3.5 h-[112px]"
      >
        <div className="absolute inset-x-0 top-16 h-2.5 rounded-full bg-ink/10" />

        {range !== null && (
          <div
            className="absolute top-14 h-[26px] rounded-md border border-dashed border-day-g0/70 bg-day-g0/15"
            style={{
              left: percent(range.low, top),
              width: percent(range.high - range.low, top),
            }}
          />
        )}

        {current !== null && (
          <>
            <div
              className="absolute top-[67px] h-1 rounded-sm bg-ink/60"
              style={{
                left: percent(current.p10, top),
                width: percent(current.p90 - current.p10, top),
              }}
            />
            <div
              className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-center text-[13px] text-ink/70"
              style={{ left: percent(current.p50, top) }}
            >
              <span className="block">Now</span>
              <b className="block font-mono text-[15px] font-bold text-ink">
                {figureText(current.p50)}
              </b>
              <i className="mx-auto mt-0.5 block h-7 w-0.5 bg-ink/60" />
            </div>
          </>
        )}

        {planned !== null && (
          <div
            className="absolute -bottom-[22px] -translate-x-1/2 whitespace-nowrap text-center"
            style={{ left: percent(planned.value, top) }}
          >
            <i className="mx-auto mb-0.5 block h-[22px] w-[3px] bg-day-model" />
            <b className="block font-mono text-[15px] font-bold text-day-model">
              {figureText(planned.value)}
            </b>
            <span className="block text-[13px] text-ink/70">With this plan</span>
          </div>
        )}
      </div>

      <div className="mt-8">
        {current === null ? (
          <p className="py-1 text-[14px] text-ink/70">
            No full week in the recordings yet.
          </p>
        ) : (
          <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
            <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
              <SourceLabel kind="measured">Measured</SourceLabel>
              Now, median of {current.weeks} weeks
            </span>
            <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
              {figureText(current.p50)}{' '}
              <span className="font-normal text-ink/70">
                ({figureText(current.p10)}–{figureText(current.p90)})
              </span>
            </b>
          </div>
        )}

        {planned === null ? (
          <NoticeBox>
            {dose.reason ?? 'Press Run to project the week.'}
          </NoticeBox>
        ) : (
          <>
            <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
              <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
                <SourceLabel kind="projected">Projected</SourceLabel>
                Sessions, {planned.days_per_week} × {figureText(planned.session_day)}
              </span>
              <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
                {figureText(planned.from_sessions)}
              </b>
            </div>
            <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
              <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
                <SourceLabel kind="measured">Measured</SourceLabel>
                Everyday movement
              </span>
              <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
                {figureText(planned.from_everyday)}
              </b>
            </div>
            <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
              <span className="text-ink/80">With this plan</span>
              <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-day-model">
                {figureText(planned.value)}
              </b>
            </div>
          </>
        )}

        {range !== null && (
          <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
            <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-[22px] rounded-sm border border-dashed border-day-g0/70 bg-day-g0/15"
              />
              {range.label}
              <span className={PLACEHOLDER_BADGE}>Placeholder value</span>
            </span>
            <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
              {figureText(range.low)}–{figureText(range.high)}
            </b>
          </div>
        )}
      </div>

      {current !== null && current.rule !== '' && (
        <p className="mt-1.5 text-[13px] leading-[18px] text-ink/70">
          {current.rule}
        </p>
      )}
    </section>
  )
}

function WeeklyPanelAdaptive({
  dose,
  range,
}: {
  dose: AssessmentDose
  range: AssessmentRange | null
}) {
  const current = dose.current
  const planned = dose.planned
  const top = scaleTop(dose, range)
  const unit = displayUnit(dose.unit)
  const ticks = Array.from({ length: Math.floor(top / 5) + 1 }, (_, index) => index * 5)

  const spoken: string[] = []
  if (current !== null) {
    spoken.push(
      `Now ${figureText(current.p50)}, median of ${current.weeks} weeks`,
      `usual range ${figureText(current.p10)} to ${figureText(current.p90)}`,
    )
  }
  if (planned !== null) {
    spoken.push(`with this plan ${figureText(planned.value)}`)
  }
  if (range !== null) {
    spoken.push(`${range.label} ${figureText(range.low)} to ${figureText(range.high)}`)
  }
  const scaleLabel = `Weekly activity in ${unit !== '' ? unit : 'units'} from 0 to ${top}. ${spoken.join('. ')}`

  const added = planned !== null && current !== null ? planned.value - current.p50 : null

  return (
    <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-[16px] font-semibold text-ink">
          Weekly activity
        </h3>
        <span className="font-mono text-[13px] text-ink/70">{unit}</span>
      </div>

      <div
        className="relative mx-2 mt-2 h-4 font-mono text-[13px] text-ink/70"
        aria-hidden="true"
      >
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute -translate-x-1/2"
            style={{ left: percent(tick, top) }}
          >
            {tick}
          </span>
        ))}
      </div>

      <div
        role="img"
        aria-label={scaleLabel}
        className="relative mx-2 mt-3.5 h-[112px]"
      >
        <div className="absolute inset-x-0 top-16 h-2.5 rounded-full bg-ink/10" />

        {range !== null && (
          <div
            className="absolute top-14 h-[26px] rounded-md border border-dashed border-day-g0/70 bg-day-g0/15"
            style={{
              left: percent(range.low, top),
              width: percent(range.high - range.low, top),
            }}
          />
        )}

        {current !== null && (
          <>
            <div
              className="absolute top-[67px] h-1 rounded-sm bg-ink/60"
              style={{
                left: percent(current.p10, top),
                width: percent(current.p90 - current.p10, top),
              }}
            />
            <div
              className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-center text-[13px] text-ink/70"
              style={{ left: percent(current.p50, top) }}
            >
              <span className="block">Now</span>
              <b className="block font-mono text-[15px] font-bold text-ink">
                {figureText(current.p50)}
              </b>
              <i className="mx-auto mt-0.5 block h-7 w-0.5 bg-ink/60" />
            </div>
          </>
        )}

        {planned !== null && (
          <div
            className="absolute -bottom-[22px] -translate-x-1/2 whitespace-nowrap text-center"
            style={{ left: percent(planned.value, top) }}
          >
            <i className="mx-auto mb-0.5 block h-[22px] w-[3px] bg-day-model" />
            <b className="block font-mono text-[15px] font-bold text-day-model">
              {figureText(planned.value)}
            </b>
            <span className="block text-[13px] text-ink/70">With this plan</span>
          </div>
        )}
      </div>

      <div className="mt-8">
        {current === null ? (
          <p className="py-1 text-[14px] text-ink/70">
            No full week in the recordings yet.
          </p>
        ) : (
          <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
            <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
              <SourceLabel kind="measured">Measured</SourceLabel>
              Now, median of {current.weeks} weeks
            </span>
            <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
              {figureText(current.p50)}{' '}
              <span className="font-normal text-ink/70">
                ({figureText(current.p10)}–{figureText(current.p90)})
              </span>
            </b>
          </div>
        )}

        {planned === null ? (
          <NoticeBox>
            {dose.reason ?? 'Press Run to project the week.'}
          </NoticeBox>
        ) : (
          <>
            <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
              <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
                <SourceLabel kind="projected">Projected</SourceLabel>
                With this plan ({planned.days_per_week} days)
              </span>
              <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-day-model">
                {figureText(planned.value)}
              </b>
            </div>
            {added !== null && (
              <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
                <span className="text-ink/80">Added over the habit</span>
                <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
                  {added < 0 ? '\u2212' : '+'}
                  {figureText(Math.abs(added))}
                </b>
              </div>
            )}
          </>
        )}

        {range !== null && (
          <div className="flex justify-between gap-3 border-t border-white/10 py-1 text-[14px]">
            <span className="flex flex-wrap items-center gap-1.5 text-ink/80">
              <span
                aria-hidden="true"
                className="inline-block h-3 w-[22px] rounded-sm border border-dashed border-day-g0/70 bg-day-g0/15"
              />
              {range.label}
              <span className={PLACEHOLDER_BADGE}>Placeholder value</span>
            </span>
            <b className="whitespace-nowrap font-mono text-[14px] font-bold tabular-nums text-ink">
              {figureText(range.low)}–{figureText(range.high)}
            </b>
          </div>
        )}
      </div>
    </section>
  )
}

function HorizonTrail({
  result,
  choices,
  selected,
}: {
  result: AssessmentResult
  choices: HorizonChoice[]
  selected: number
}) {
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {choices.map((choice, index) => {
        const value = valueAtHorizon(result, choice)
        const isSelected = index === selected
        return (
          <span
            key={`${choice.index}-${choice.label}`}
            className={`rounded-md border px-1.5 py-0.5 font-mono text-[13px] tabular-nums ${
              isSelected
                ? 'border-day-model text-day-model'
                : 'border-white/10 text-ink/70'
            }`}
          >
            {horizonShort(choice)} {figureText(value, 2)}
          </span>
        )
      })}
    </div>
  )
}

function AdaptiveRiskRow({
  result,
  choices,
  selected,
  onEnter,
}: {
  result: AssessmentResult
  choices: HorizonChoice[]
  selected: number
  onEnter: (attribute: string | null) => void
}) {
  const choice = choices[selected] ?? choices[0]
  const value =
    result.now === null || choice === undefined
      ? null
      : valueAtHorizon(result, choice)

  const reasonInBody =
    result.not_applicable === null &&
    (result.now === null ||
      (result.now !== null &&
        selected !== 0 &&
        value === null &&
        result.needs.planned.length > 0))

  let body: ReactNode
  if (result.not_applicable !== null) {
    body = <NoticeBox>{result.not_applicable}</NoticeBox>
  } else if (result.now === null) {
    body = (
      <NeedsBox
        needs={result.needs.now}
        fallback={result.reason ?? 'could not be computed'}
        onEnter={onEnter}
      />
    )
  } else {
    const unit = displayUnit(result.unit)
    body = (
      <>
        <div className="mt-1.5 flex flex-wrap items-end gap-[18px]">
          <div className="min-w-[120px]">
            <span className="block text-[13px] text-ink/70">Now</span>
            <b className="font-mono text-[30px] font-bold leading-none tabular-nums text-ink">
              {figureText(result.now, 2)}
              {unit !== '' && (
                <small className="text-[16px] font-bold"> {unit}</small>
              )}
            </b>
          </div>
          <div className="min-w-[120px]">
            {selected === 0 ? (
              <>
                <span className="block text-[13px] text-ink/70">
                  After a session
                </span>
                <b className="text-[20px] font-bold leading-none text-ink/70">
                  no change yet
                </b>
              </>
            ) : (
              <>
                <span className="block text-[13px] text-ink/70">
                  {choice?.label ?? ''}
                </span>
                <b className="font-mono text-[30px] font-bold leading-none tabular-nums text-day-model">
                  {figureText(value, 2)}
                  {unit !== '' && (
                    <small className="text-[16px] font-bold"> {unit}</small>
                  )}
                </b>
              </>
            )}
          </div>
          {selected !== 0 && value !== null && (
            <RiskDelta value={value} now={result.now} />
          )}
        </div>

        <HorizonTrail result={result} choices={choices} selected={selected} />

        {selected !== 0 &&
          value === null &&
          result.needs.planned.length > 0 && (
            <NeedsBox
              needs={result.needs.planned}
              fallback={result.reason ?? 'could not be computed'}
              onEnter={onEnter}
            />
          )}
      </>
    )
  }

  return (
    <div className="mt-2.5 border-t border-white/10 pt-3">
      <RiskHead result={result} />
      {body}
      {result.reason !== null && !reasonInBody && (
        <p className="mt-1.5 text-[13px] text-ink/70">{result.reason}</p>
      )}
      <RiskDetails result={result} />
    </div>
  )
}

function AdaptiveRiskPanel({
  results,
  choices,
  selected,
  onEnter,
}: {
  results: AssessmentResult[]
  choices: HorizonChoice[]
  selected: number
  onEnter: (attribute: string | null) => void
}) {
  return (
    <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-[16px] font-semibold text-ink">
          Risk of disease
        </h3>
        <SourceLabel kind="population">
          Population model applied to you
        </SourceLabel>
      </div>

      {results.map((result) => (
        <AdaptiveRiskRow
          key={result.id}
          result={result}
          choices={choices}
          selected={selected}
          onEnter={onEnter}
        />
      ))}
    </section>
  )
}

function MediatorRow({
  mediator,
  choices,
  selected,
  scale,
  first,
  onEnter,
}: {
  mediator: AssessmentMediatorOutcome
  choices: HorizonChoice[]
  selected: number
  scale: number
  first: boolean
  onEnter: (attribute: string | null) => void
}) {
  const tag =
    mediator.source === 'measured' ? (
      <small className="block text-[13px] text-ink/70">
        <span aria-hidden="true" className="text-ink">
          ■{' '}
        </span>
        Measured from recordings
      </small>
    ) : (
      <small className="block text-[13px] text-ink/70">Entered</small>
    )
  const name = (
    <span className="text-[14px] leading-[1.25]">
      {mediator.label}
      {tag}
    </span>
  )
  const row = `${MED_GRID} py-2 text-[14px] ${
    first ? '' : 'border-t border-white/10'
  }`

  if (mediator.value_now === null) {
    const labels = mediator.needs.map(needText)
    return (
      <div className={row}>
        {name}
        <b className="text-right font-mono text-[14px] font-bold tabular-nums text-ink">
          –
        </b>
        <span className="col-span-2 flex flex-wrap items-center justify-between gap-2 text-[13px] text-ink/70">
          <span>
            Needs: {labels.length > 0 ? labels.join(', ') : 'not in the recordings'}
          </span>
          {mediator.needs.length > 0 && (
            <button
              type="button"
              onClick={() => onEnter(firstAttribute(mediator.needs))}
              className={`${SMALL_BUTTON} ${FOCUS_CLASS}`}
            >
              Enter
            </button>
          )}
        </span>
      </div>
    )
  }

  const now = mediator.value_now

  if (!mediator.moves) {
    return (
      <div className={row}>
        {name}
        <b className="text-right font-mono text-[14px] font-bold tabular-nums text-ink">
          {figureText(now, decimalsFor(now))}
        </b>
        <span className="col-span-2 text-[13px] text-ink/70">
          {mediator.still ?? 'Does not move with this plan.'}
        </span>
      </div>
    )
  }

  const values = choices.map((choice) => valueAtHorizon(mediator, choice))
  const points = values.map((value, index) => ({
    x: pointX(index, choices.length),
    y: pointY(mediatorPoint(value, now, scale)),
  }))
  const solid = points
    .slice(0, -1)
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`)
    .join(' ')
  const last = points[points.length - 1]
  const beforeLast = points[points.length - 2]
  const dashed =
    points.length > 1 && last !== undefined && beforeLast !== undefined
      ? `M${beforeLast.x} ${beforeLast.y} L${last.x} ${last.y}`
      : ''
  const lastValue = values[values.length - 1] ?? null
  const selectedValue = values[selected] ?? null
  const selectedDecimals =
    selectedValue === null ? 2 : decimalsFor(selectedValue)

  return (
    <div className={row}>
      {name}
      <b className="text-right font-mono text-[14px] font-bold tabular-nums text-ink">
        {figureText(now, decimalsFor(now))}
      </b>
      <svg
        viewBox="0 0 100 34"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${mediator.label} from ${figureText(now, decimalsFor(now))} now to ${figureText(lastValue, lastValue === null ? 1 : decimalsFor(lastValue))} settled`}
        className="h-[34px] w-full overflow-visible"
      >
        <line
          x1="0"
          y1="17"
          x2="100"
          y2="17"
          className="stroke-ink"
          strokeOpacity={0.18}
          vectorEffect="non-scaling-stroke"
        />
        {solid !== '' && (
          <path
            d={solid}
            fill="none"
            className="stroke-day-model"
            strokeWidth={1.6}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {dashed !== '' && (
          <path
            d={dashed}
            fill="none"
            className="stroke-day-model"
            strokeWidth={1.4}
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {points.map((point, index) => (
          <circle
            key={`${point.x}-${index}`}
            cx={point.x}
            cy={point.y}
            r={index === selected ? 3.2 : 1.8}
            className={
              index === selected
                ? 'fill-day-model stroke-day-model'
                : 'fill-surface-mid stroke-day-model'
            }
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <b className="text-right font-mono text-[14px] font-bold tabular-nums text-day-model">
        {figureText(selectedValue, selectedDecimals)}
        {selected !== 0 && selectedValue !== null && (
          <>
            <br />
            <span className="text-[13px] font-normal">
              {signedMove(selectedValue, now, selectedDecimals)}
            </span>
          </>
        )}
      </b>
    </div>
  )
}

function MediatorsPanel({
  mediators,
  choices,
  selected,
  onEnter,
}: {
  mediators: AssessmentMediatorOutcome[]
  choices: HorizonChoice[]
  selected: number
  onEnter: (attribute: string | null) => void
}) {
  const scale = mediatorScale(mediators, choices)
  const choice = choices[selected] ?? choices[0]

  return (
    <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-[16px] font-semibold text-ink">
          What changes, and when
        </h3>
        <StatusBadge status={mediators[0]?.status ?? null} />
      </div>

      <div className={`${MED_GRID} pb-1 text-[13px] text-ink/70`}>
        <span>Factor</span>
        <span className="text-right">Now</span>
        <span>{marksText(choices)}</span>
        <span className="text-right">{choice?.label ?? ''}</span>
      </div>

      {mediators.map((mediator, index) => (
        <MediatorRow
          key={`${mediator.now}-${mediator.source}`}
          mediator={mediator}
          choices={choices}
          selected={selected}
          scale={scale}
          first={index === 0}
          onEnter={onEnter}
        />
      ))}

      <p className="mt-1 text-[13px] leading-[18px] text-ink/70">
        Lines share one scale: the full height is ±{Math.round(scale * 100)}% of
        the value now.
      </p>
    </section>
  )
}

function FlagsPanel({
  flags,
  onEnter,
}: {
  flags: AssessmentFlag[]
  onEnter: (attribute: string | null) => void
}) {
  return (
    <section className="mt-4 min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
      <h3 className="font-display text-[16px] font-semibold text-ink">Flags</h3>

      <div className="grid grid-cols-1 gap-4 min-[1100px]:grid-cols-3">
        {flags.map((flag) => (
          <FlagRow
            key={flag.attribute}
            flag={flag}
            onEnter={onEnter}
            bordered={false}
          />
        ))}
      </div>

      <p className="mt-2 text-[13px] leading-[18px] text-ink/70">
        A flag repeats what guidance says for what you entered. No flag is not a
        statement that exercise is safe.
      </p>
    </section>
  )
}

function AdaptiveWeek({ answer, onEnter }: Props) {
  const { dose, assessment } = answer
  const choices = horizonChoices(assessment.horizons)
  const [selected, setSelected] = useState(0)
  const groupId = useId()

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <SourceLabel kind="measured">Measured from recordings</SourceLabel>
        <SourceLabel kind="projected">
          Projected by this person’s model
        </SourceLabel>
        <SourceLabel kind="population">
          Population model applied to you
        </SourceLabel>
      </div>

      <div
        role="group"
        aria-labelledby={groupId}
        className="flex flex-wrap items-center gap-2"
      >
        <span id={groupId} className="text-[14px] text-ink/70">
          Plan kept up for
        </span>
        <div className="flex flex-wrap gap-1.5">
          {choices.map((choice, index) => {
            const isSelected = index === selected
            return (
              <button
                key={`${choice.index}-${choice.label}`}
                type="button"
                aria-pressed={isSelected}
                onClick={() => setSelected(index)}
                className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-el border px-3 text-[13px] font-semibold transition-colors ${FOCUS_CLASS} ${
                  isSelected
                    ? 'border-oxy-container/60 bg-oxy-container/15 text-oxy'
                    : 'border-white/10 bg-surface-lowest text-ink/70 hover:text-ink'
                }`}
              >
                {isSelected && (
                  <span aria-hidden="true" className="text-[9px]">
                    ●
                  </span>
                )}
                {choice.label}
              </button>
            )
          })}
        </div>
      </div>

      <p className="mt-2.5 rounded-r-el border-l-[3px] border-day-model bg-day-model/[0.06] px-3 py-2 text-[14px] text-ink">
        Test results do not change after one session. These are the values this
        plan tends to if it is kept up, and how fast.
      </p>

      <div className="mt-3 grid grid-cols-1 gap-4 min-[1100px]:grid-cols-[minmax(0,.95fr)_minmax(0,1.05fr)_minmax(0,1.3fr)]">
        <WeeklyPanelAdaptive dose={dose} range={assessment.range} />
        <AdaptiveRiskPanel
          results={assessment.results}
          choices={choices}
          selected={selected}
          onEnter={onEnter}
        />
        <MediatorsPanel
          mediators={assessment.mediators}
          choices={choices}
          selected={selected}
          onEnter={onEnter}
        />
      </div>

      <FlagsPanel flags={assessment.flags} onEnter={onEnter} />
    </div>
  )
}

function WeekRiskToday({ answer, onEnter }: Props) {
  const { dose, assessment } = answer

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <SourceLabel kind="measured">Measured from recordings</SourceLabel>
        <SourceLabel kind="projected">
          Projected by this person’s model
        </SourceLabel>
        <SourceLabel kind="population">
          Population model applied to you
        </SourceLabel>
      </div>

      <div className="grid grid-cols-1 gap-4 min-[1100px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1.25fr)_minmax(0,.9fr)]">
        <WeeklyPanel dose={dose} range={assessment.range} />

        <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-display text-[16px] font-semibold text-ink">
              Risk of disease
            </h3>
            <SourceLabel kind="population">
              Population model applied to you
            </SourceLabel>
          </div>

          {assessment.results.map((result) => (
            <RiskRow key={result.id} result={result} onEnter={onEnter} />
          ))}
        </section>

        <section className="min-w-0 rounded-xl border border-white/10 bg-surface-mid px-4 py-3.5">
          <h3 className="font-display text-[16px] font-semibold text-ink">
            Flags
          </h3>

          {assessment.flags.map((flag) => (
            <FlagRow key={flag.attribute} flag={flag} onEnter={onEnter} />
          ))}

          <p className="mt-2 text-[13px] leading-[18px] text-ink/70">
            A flag repeats what guidance says for what you entered. No flag is
            not a statement that exercise is safe.
          </p>
        </section>
      </div>
    </div>
  )
}

const ANSWER_KEYS = new WeakMap<AssessmentAnswer, number>()
let nextAnswerKey = 0

function keyForAnswer(answer: AssessmentAnswer): number {
  let key = ANSWER_KEYS.get(answer)
  if (key === undefined) {
    nextAnswerKey += 1
    key = nextAnswerKey
    ANSWER_KEYS.set(answer, key)
  }
  return key
}

export function WeekRisk({ answer, onEnter }: Props) {
  if (answer.assessment.horizons === null) {
    return <WeekRiskToday answer={answer} onEnter={onEnter} />
  }
  return (
    <AdaptiveWeek key={keyForAnswer(answer)} answer={answer} onEnter={onEnter} />
  )
}
