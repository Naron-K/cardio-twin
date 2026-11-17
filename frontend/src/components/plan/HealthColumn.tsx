/**
 * HealthColumn — the "Your health" column, sized and drawn like the Day column.
 *
 * It only reports what `assessment.ts` says about the entries: the total and
 * per-group progress come from `totalProgress` and `groupProgress`, and every
 * label comes from the options.  It holds no state and writes nothing.
 */
import { useId } from 'react'
import type { AssessmentOptions, Entries } from '../../twin/assessment'
import { groupProgress, profileOf, totalProgress } from '../../twin/assessment'
import { FOCUS_CLASS } from './PlanEditor'

interface Props {
  options: AssessmentOptions
  entries: Entries
  onEdit: () => void
  onFillExample: () => void
  onFillProfile: (id: string) => void
  onClear: () => void
}

const PRIMARY =
  'min-h-[44px] rounded-el border border-transparent bg-oxy-container px-4 text-[16px] font-bold text-oxy-on transition-opacity disabled:cursor-not-allowed disabled:opacity-50'

const SECONDARY =
  'min-h-[44px] rounded-el border border-white/10 bg-surface-low px-4 text-[14px] font-semibold text-ink/70 transition-colors hover:text-ink'

export function HealthColumn({
  options,
  entries,
  onEdit,
  onFillExample,
  onFillProfile,
  onClear,
}: Props) {
  const total = totalProgress(options, entries)
  const groups = groupProgress(options, entries)
  const complete = total.given === total.of && total.of > 0
  const baseId = useId()
  const profileId = profileOf(options, entries)
  const filled =
    profileId === null
      ? null
      : options.examples.find((example) => example.id === profileId) ?? null

  return (
    <div className="w-[440px] flex-none rounded-xl border border-white/10 bg-surface-mid px-4 pb-2 pt-3 phone:w-full">
      <div className="mb-1 flex min-h-[44px] flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-[16px] font-semibold text-ink">Your health</h3>
        <span
          className={`font-mono text-[13px] font-bold tabular-nums ${
            complete ? 'text-day-g0' : 'text-ink/70'
          }`}
        >
          {complete && <span aria-hidden="true">✓ </span>}
          {total.given} of {total.of} entered
        </span>
      </div>

      <div>
        {groups.map((group) => {
          const done = group.given === group.of && group.of > 0
          return (
            <div
              key={group.id}
              className="flex min-h-[36px] items-center justify-between gap-3 border-t border-white/10 text-[14px] text-ink/80 first:border-t-0"
            >
              <span>{group.label}</span>
              <span
                className={`font-mono text-[13px] font-bold tabular-nums ${
                  done ? 'text-day-g0' : 'text-ink/70'
                }`}
              >
                {done && <span aria-hidden="true">✓ </span>}
                {group.given} / {group.of}
              </span>
            </div>
          )
        })}
      </div>

      <div className="mt-2.5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onEdit}
          className={`${PRIMARY} ${FOCUS_CLASS}`}
        >
          Enter or edit
        </button>
        {total.given > 0 && (
          <button
            type="button"
            onClick={onClear}
            className={`${SECONDARY} ${FOCUS_CLASS}`}
          >
            Clear
          </button>
        )}
      </div>

      {options.examples.length > 0 ? (
        <>
          <p className="mt-2 text-[13px] leading-[18px] text-ink/70">
            Fill with an invented example:
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {options.examples.map((example, index) => (
              <button
                key={example.id}
                type="button"
                aria-pressed={profileId === example.id}
                aria-describedby={`${baseId}-profile-${index}`}
                onClick={() => onFillProfile(example.id)}
                className={`min-h-[44px] rounded-el border px-4 text-[14px] font-semibold transition-colors ${FOCUS_CLASS} ${
                  profileId === example.id
                    ? 'border-warn-strong/70 bg-surface-high text-ink shadow-inset1'
                    : 'border-white/10 bg-surface-low text-ink/70 hover:text-ink'
                }`}
              >
                {profileId === example.id && (
                  <span aria-hidden="true" className="mr-1.5 text-[11px] text-warn">
                    ▲
                  </span>
                )}
                {example.label.split(' · ')[0]}
              </button>
            ))}
          </div>
          <div className="sr-only">
            {options.examples.map((example, index) => (
              <p key={example.id} id={`${baseId}-profile-${index}`}>
                {example.label}
              </p>
            ))}
          </div>
        </>
      ) : options.example ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onFillExample}
            aria-describedby={`${baseId}-example`}
            className={`${SECONDARY} ${FOCUS_CLASS}`}
          >
            Fill with invented example
          </button>
          <span id={`${baseId}-example`} className="sr-only">
            {options.example.label}
          </span>
        </div>
      ) : null}

      {filled && (
        <p className="mt-2 inline-block rounded-md border border-warn-strong/60 bg-warn-strong/10 px-2 py-0.5 font-body text-[13px] font-semibold text-warn">
          <span aria-hidden="true">▲ </span>
          {filled.label}
        </p>
      )}

      <p className="mt-1 text-[13px] leading-[18px] text-ink/70">
        Held on this device only. Not saved on the server and not part of the link.
      </p>
    </div>
  )
}
