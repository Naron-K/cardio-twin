import { useCallback, useEffect, useState } from 'react'
import { DayView } from './components/day/DayView'
import { Chip } from './components/ui'
import type { DaySummary } from './twin/dayView'
import { fetchSources, findDayLamina } from './utils/api'
import type { DayRoute, SourcesResponse } from './utils/api'
import { neighbourDays, pickDay, routeFromSearch, routeToSearch } from './twin/sources'

interface DayMeta {
  subject: string
  date: string
  timezone: string
  synthetic: boolean
}

/**
 * The app is one recorded day.  It opens on the day the URL names
 * (`?subject=…&date=…`), or the first subject's newest day, and keeps the URL
 * in step so a link reopens the same day.
 */

type Boot =
  | { attempt: number; status: 'loading' }
  | { attempt: number; status: 'error'; message: string }
  | { attempt: number; status: 'empty' }
  | { attempt: number; status: 'ready'; lamina: string; sources: SourcesResponse }

const SELECT_CLASS =
  'min-h-[44px] min-w-0 rounded-el border border-white/10 bg-surface-lowest px-3 ' +
  'font-mono text-[13px] readout text-ink'

const STEP_CLASS =
  'min-h-[44px] min-w-[44px] rounded-el border border-white/10 bg-surface-lowest px-2 ' +
  'font-mono text-[15px] text-ink/80 transition-colors hover:text-ink ' +
  'disabled:cursor-not-allowed disabled:text-ink/20'

export default function App() {
  const [attempt, setAttempt] = useState(0)
  const [boot, setBoot] = useState<Boot>({ attempt: -1, status: 'loading' })
  const [route, setRoute] = useState<DayRoute | null>(null)

  useEffect(() => {
    let live = true
    findDayLamina()
      .then(async (lamina) => {
        if (!lamina) {
          if (live) setBoot({ attempt, status: 'empty' })
          return
        }
        const sources = await fetchSources(lamina)
        if (!live) return
        const opened = pickDay(sources, routeFromSearch(window.location.search))
        if (!opened) {
          setBoot({ attempt, status: 'empty' })
          return
        }
        setRoute(opened)
        setBoot({ attempt, status: 'ready', lamina, sources })
      })
      .catch((error: unknown) => {
        if (!live) return
        const message =
          error instanceof Error && error.message ? error.message : 'The server did not answer.'
        setBoot({ attempt, status: 'error', message })
      })
    return () => {
      live = false
    }
  }, [attempt])

  // The day in the URL; an older link's hash and feed parameters are dropped.
  useEffect(() => {
    if (!route) return
    const next = `${window.location.pathname}${routeToSearch(route, window.location.search)}`
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (current !== next) window.history.replaceState(null, '', next)
  }, [route])

  const open = useCallback((next: DayRoute) => setRoute(next), [])

  // The loaded day's zone and origin, kept with the day they belong to so the
  // header never shows the previous day's while the next one loads.
  const [meta, setMeta] = useState<DayMeta | null>(null)
  const onDay = useCallback(
    (day: DaySummary) =>
      setMeta({
        subject: day.subject,
        date: day.date,
        timezone: day.timezone,
        synthetic: day.synthetic,
      }),
    [],
  )
  const shown =
    meta && route && meta.subject === route.subject && meta.date === route.date ? meta : null

  const current = boot.attempt === attempt ? boot : null
  const ready = current?.status === 'ready' && route ? current : null
  const subjects = ready ? ready.sources.replay?.subjects ?? {} : {}
  const subjectNames = Object.keys(subjects)
  const dates = route ? subjects[route.subject] ?? [] : []
  const { older, newer } = route ? neighbourDays(dates, route.date) : { older: null, newer: null }

  return (
    <div className="min-h-app flex flex-col bg-surface text-ink font-body">
      <header className="shrink-0 flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-4 wide:px-margin wide:pt-gutter">
        <h1 className="font-display text-[24px] font-extrabold tracking-tight text-ink">
          Day view
        </h1>
        {route && (
          <p className="font-body text-[14px] text-ink/70">
            subject {route.subject} · {route.date}
            {shown?.timezone ? ` · ${shown.timezone}` : ''}
          </p>
        )}
        {shown?.synthetic && <Chip tone="warn">Synthetic data</Chip>}

        {ready && route && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {subjectNames.length > 1 ? (
              <select
                aria-label="Subject"
                value={route.subject}
                onChange={(event) => {
                  const days = subjects[event.target.value]
                  if (days && days.length > 0) open({ subject: event.target.value, date: days[0] })
                }}
                className={SELECT_CLASS}
              >
                {subjectNames.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-mono text-[13px] readout text-ink/80">{route.subject}</span>
            )}

            <button
              type="button"
              aria-label="Previous day"
              disabled={!older}
              onClick={() => older && open({ subject: route.subject, date: older })}
              className={STEP_CLASS}
            >
              ‹
            </button>
            <select
              aria-label="Day"
              value={route.date}
              onChange={(event) => {
                if (dates.includes(event.target.value)) {
                  open({ subject: route.subject, date: event.target.value })
                }
              }}
              className={SELECT_CLASS}
            >
              {dates.map((date) => (
                <option key={date} value={date}>
                  {date}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-label="Next day"
              disabled={!newer}
              onClick={() => newer && open({ subject: route.subject, date: newer })}
              className={STEP_CLASS}
            >
              ›
            </button>
          </div>
        )}
      </header>

      <main className="flex-1 p-4 wide:px-margin wide:py-gutter">
        {ready && route ? (
          <DayView
            lamina={ready.lamina}
            subject={route.subject}
            date={route.date}
            onDay={onDay}
          />
        ) : !current || current.status === 'loading' ? (
          <p className="font-mono text-[13px] readout uppercase text-ink/60 animate-pulse">
            Loading…
          </p>
        ) : current.status === 'empty' ? (
          <p className="font-body text-[15px] text-ink/80">No recorded days.</p>
        ) : current.status === 'error' ? (
          <div className="flex flex-col items-start gap-3">
            <p className="font-body text-[15px] text-crimson-container">{current.message}</p>
            <button
              type="button"
              onClick={() => setAttempt((value) => value + 1)}
              className="min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-4 font-mono text-[13px] font-bold readout uppercase text-ink/70 transition-colors hover:text-ink"
            >
              Retry
            </button>
          </div>
        ) : null}
      </main>
    </div>
  )
}
