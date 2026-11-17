/**
 * HealthDrawer — the right-hand "Your health" panel.
 *
 * The panel body is a separate component mounted only while the drawer is
 * open, so its drafts and field messages start fresh on every open without a
 * state reset inside an effect.  The component itself only reads the entries
 * `assessment.ts` parses; it never writes them anywhere but through the
 * `onChange` callback.
 */
import { useEffect, useId, useRef, useState } from 'react'
import type { AssessmentEntry, AssessmentOptions, Entries } from '../../twin/assessment'
import { displayUnit, entryText, setEntry } from '../../twin/assessment'
import { FOCUS_CLASS } from './PlanEditor'

interface Props {
  open: boolean
  options: AssessmentOptions
  entries: Entries
  onChange: (entries: Entries) => void
  onClose: () => void
  refused: { attribute: string | null; message: string } | null
  focusAttribute: string | null
}

interface BodyProps {
  options: AssessmentOptions
  entries: Entries
  onChange: (entries: Entries) => void
  refused: { attribute: string | null; message: string } | null
  focusAttribute: string | null
}

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'

const SELECTED = 'border-transparent bg-oxy-container text-oxy-on'
const UNSELECTED =
  'border-white/10 bg-surface-low text-ink/70 hover:text-ink'

function isEntered(entries: Entries, entry: AssessmentEntry): boolean {
  const value = entries[entry.attribute]
  return value !== undefined && Number.isFinite(value)
}

function DrawerBody({
  options,
  entries,
  onChange,
  refused,
  focusAttribute,
}: BodyProps) {
  const root = useRef<HTMLDivElement | null>(null)
  const baseId = useId()
  const [messages, setMessages] = useState<Record<string, string>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const group of options.groups) {
      for (const entry of group.entries) {
        if (entry.kind === 'number') {
          initial[entry.attribute] = entryText(entry, entries)
        }
      }
    }
    return initial
  })

  useEffect(() => {
    const node = root.current
    if (!node) return

    let found: HTMLElement | null = null
    if (focusAttribute !== null) {
      for (const candidate of Array.from(
        node.querySelectorAll<HTMLElement>('[data-entry]'),
      )) {
        if (candidate.dataset.entry === focusAttribute) {
          found = candidate
          break
        }
      }
    }

    const control =
      found?.querySelector<HTMLElement>('input, button') ??
      node.querySelector<HTMLElement>('input, button')
    ;(control ?? node).focus()
  }, [focusAttribute])

  const commit = (attribute: string, text: string) => {
    const result = setEntry(options, entries, attribute, text)
    setMessages((current) => ({ ...current, [attribute]: result.message }))
    onChange(result.entries)
  }

  const typeNumber = (attribute: string, text: string) => {
    setDrafts((current) => ({ ...current, [attribute]: text }))
    commit(attribute, text)
  }

  const pressChoice = (attribute: string, value: number) => {
    const pressed = entries[attribute] === value
    commit(attribute, pressed ? '' : String(value))
  }

  return (
    <div ref={root} tabIndex={-1}>
      {options.groups.map((group) => (
        <div key={group.id}>
          <h3 className="mt-4 font-display text-[16px] font-semibold text-ink">
            {group.label}
          </h3>

          {group.entries.map((entry) => {
            const entered = isEntered(entries, entry)
            const labelId = `${baseId}-${entry.attribute}-label`
            const inputId = `${baseId}-${entry.attribute}-input`
            const local = messages[entry.attribute] ?? ''
            const server =
              refused && refused.attribute === entry.attribute
                ? refused.message
                : ''
            const message = local || server
            const choices =
              entry.kind === 'yesno'
                ? [
                    { value: 1, label: 'Yes' },
                    { value: 0, label: 'No' },
                  ]
                : entry.options ?? []

            return (
              <div
                key={entry.attribute}
                data-entry={entry.attribute}
                className="border-t border-white/10 py-2"
              >
                <div className="grid grid-cols-1 gap-x-3 gap-y-1 min-[1100px]:grid-cols-[1fr_190px] min-[1100px]:items-center">
                  <label
                    htmlFor={entry.kind === 'number' ? inputId : undefined}
                    id={labelId}
                    className="text-[15px] font-semibold text-ink"
                  >
                    {entry.label}
                  </label>

                  {entry.kind === 'number' ? (
                    <div
                      className={`flex min-h-[44px] items-center gap-2 rounded-el border bg-surface-lowest px-3 ${
                        entered
                          ? 'border-white/10'
                          : 'border-dashed border-white/20'
                      }`}
                    >
                      <input
                        id={inputId}
                        type="text"
                        inputMode="decimal"
                        value={drafts[entry.attribute] ?? entryText(entry, entries)}
                        placeholder={`${entry.min} – ${entry.max}`}
                        onChange={(event) =>
                          typeNumber(entry.attribute, event.target.value)
                        }
                        className={`h-11 w-full bg-transparent font-mono text-[16px] font-bold text-ink placeholder:text-ink/40 ${FOCUS_CLASS}`}
                      />
                      <span className="whitespace-nowrap text-[13px] text-ink/70">
                        {displayUnit(entry.unit)}
                      </span>
                    </div>
                  ) : choices.length === 0 ? (
                    <p className="text-[13px] text-ink/70">No options offered.</p>
                  ) : (
                    <div
                      role="group"
                      aria-labelledby={labelId}
                      className="flex gap-1.5"
                    >
                      {choices.map((choice) => {
                        const selected =
                          entries[entry.attribute] === choice.value
                        return (
                          <button
                            key={choice.value}
                            type="button"
                            aria-pressed={selected}
                            onClick={() =>
                              pressChoice(entry.attribute, choice.value)
                            }
                            className={`min-h-[44px] flex-1 rounded-el border px-2 text-[13px] font-semibold transition-colors ${FOCUS_CLASS} ${
                              selected ? SELECTED : UNSELECTED
                            }`}
                          >
                            {choice.label}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>

                <p className="mt-1 text-[13px] text-ink/70">
                  {entry.why}
                  {!entered && (
                    <>
                      {' · '}
                      <b className="font-semibold text-ink">not entered</b>
                    </>
                  )}
                </p>

                {message !== '' && (
                  <p role="alert" className="mt-1 text-[13px] text-warn">
                    {message}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

export function HealthDrawer({
  open,
  options,
  entries,
  onChange,
  onClose,
  refused,
  focusAttribute,
}: Props) {
  const headingId = useId()
  const panel = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    const node = panel.current

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab' || !node) return

      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) {
        event.preventDefault()
        node.focus()
        return
      }

      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || !node.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !node.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-40 bg-surface-lowest/70"
      />
      <aside
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        className="fixed bottom-0 right-0 top-0 z-50 w-full overflow-y-auto border-l border-white/10 bg-surface-low px-5 py-4 sm:w-[560px]"
      >
        <div className="flex min-h-[44px] items-center justify-between gap-3">
          <h2
            id={headingId}
            className="font-display text-[17px] font-semibold text-ink"
          >
            Your health
          </h2>
          <button
            type="button"
            onClick={onClose}
            className={`min-h-[44px] rounded-el border border-white/10 bg-surface-mid px-4 text-[14px] font-semibold text-ink/70 transition-colors hover:text-ink ${FOCUS_CLASS}`}
          >
            Done
          </button>
        </div>

        <p className="mt-1 text-[14px] leading-[20px] text-ink/70">
          Enter what you know. Anything left empty is asked for by the result
          that needs it; nothing is assumed.
        </p>

        {refused && refused.attribute === null && (
          <p role="alert" className="mt-2 text-[13px] text-warn">
            {refused.message}
          </p>
        )}

        <DrawerBody
          options={options}
          entries={entries}
          onChange={onChange}
          refused={refused}
          focusAttribute={focusAttribute}
        />
      </aside>
    </>
  )
}
