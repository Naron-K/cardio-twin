/**
 * WeekRisk — the week's activity, the risk figures and the flags, drawn from
 * the assessed answer.  Every figure, label and unit comes from the answer or
 * the options; the component holds nothing and writes nothing.
 */
import type { ReactNode } from 'react'
import type {
  AssessmentAnswer,
  AssessmentDose,
  AssessmentFlag,
  AssessmentNeed,
  AssessmentRange,
  AssessmentResult,
  StatusTone,
} from '../../twin/assessment'
import {
  changeText,
  displayUnit,
  figureText,
  scaleTop,
  statusText,
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

function percent(value: number, top: number): string {
  return `${(100 * value) / top}%`
}

function firstAttribute(needs: AssessmentNeed[]): string | null {
  for (const need of needs) {
    if ('attribute' in need) return need.attribute
  }
  return null
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
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold text-ink">
          {result.label}{' '}
          <span className="font-body text-[13px] font-normal text-ink/70">
            {result.period}
          </span>
        </h3>
        <StatusBadge status={result.status} />
      </div>

      <RiskBody result={result} onEnter={onEnter} />

      {result.reason !== null && !reasonInBody && (
        <p className="mt-1.5 text-[13px] text-ink/70">{result.reason}</p>
      )}

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
    </div>
  )
}

function FlagRow({
  flag,
  onEnter,
}: {
  flag: AssessmentFlag
  onEnter: (attribute: string | null) => void
}) {
  if (flag.state === 'raised') {
    return (
      <div className="flex gap-2.5 border-t border-white/10 py-2.5 text-[14px] first:border-t-0">
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
      <div className="flex gap-2.5 border-t border-white/10 py-2.5 text-[14px] first:border-t-0">
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
    <div className="flex gap-2.5 border-t border-white/10 py-2.5 text-[14px] first:border-t-0">
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
              <span className="inline-block whitespace-nowrap rounded-md border border-warn-strong/60 bg-warn-strong/10 px-2 py-0.5 text-[13px] font-semibold text-warn">
                Placeholder value
              </span>
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

export function WeekRisk({ answer, onEnter }: Props) {
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
