/**
 * SourceBar — which feed the twin reads, and where a replay is in its day.
 *
 * The backend decides whether a lamina has anything to choose from: with fewer
 * than two modes offered this renders nothing at all, so the screens that only
 * ever stream live data look exactly as they did. Every subject, date and speed
 * comes from `/api/sources`; a tick only supplies the position and speed shown.
 */
import { useEffect, useState } from 'react'
import type { FeedRequest, FeedStatus } from '../../hooks/useCardioStream'
import { fetchSources } from '../../utils/api'
import type { SourcesResponse } from '../../utils/api'
import { defaultReplayFeed, statusLine } from '../../twin/sourceBar'

interface Props {
  /** The lamina whose recorded days are being offered. */
  lamina: string | null
  feed: FeedRequest
  onFeed: (feed: FeedRequest) => void
  latest?: FeedStatus
  paused: boolean
  onTogglePause: () => void
  onSpeed: (speed: number) => void
  onRestart: () => void
}

interface SourceState {
  lamina: string | null
  attempt: number
  status: 'ready' | 'error'
  sources: SourcesResponse | null
}

type Mode = 'simulated' | 'replay'

const SELECT_CLASS =
  'min-h-[44px] min-w-0 rounded-el border border-white/10 bg-surface-lowest px-3 ' +
  'font-mono text-[12px] readout text-ink'

export function SourceBar({
  lamina,
  feed,
  onFeed,
  latest,
  paused,
  onTogglePause,
  onSpeed,
  onRestart,
}: Props) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<SourceState>({
    lamina: null,
    attempt: -1,
    status: 'ready',
    sources: null,
  })

  useEffect(() => {
    let live = true

    fetchSources(lamina)
      .then((sources) => {
        if (live) setState({ lamina, attempt, status: 'ready', sources })
      })
      .catch(() => {
        if (live) setState({ lamina, attempt, status: 'error', sources: null })
      })

    return () => {
      live = false
    }
  }, [lamina, attempt])

  // The response is tagged with its lamina and attempt, so a render between a
  // change and the fetch that answers it is loading, never the old offer.
  const current =
    state.lamina === lamina && state.attempt === attempt ? state : null
  const status = current?.status ?? 'loading'
  const sources = current?.sources ?? null

  if (status === 'loading') return null

  if (status === 'error' || !sources) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <p className="font-mono text-[12px] readout text-ink/50">
          Could not list recorded days.
        </p>
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          className="min-h-[44px] rounded-el border border-white/10 bg-surface-lowest px-4 font-mono text-[11px] font-bold readout uppercase text-ink/60 transition-colors hover:text-ink"
        >
          Retry
        </button>
      </div>
    )
  }

  const replay = sources.replay
  const offered: Mode[] = []
  if (sources.modes.includes('simulated')) offered.push('simulated')
  if (sources.modes.includes('replay') && replay) offered.push('replay')

  // A feed the backend would refuse is not a choice to draw.
  if (offered.length < 2 || !replay) return null

  const isReplay = feed.source === 'replay'
  const selectedMode: Mode = isReplay ? 'replay' : 'simulated'

  const subjects = Object.keys(replay.subjects)
  const subject =
    isReplay && subjects.includes(feed.subject) ? feed.subject : subjects[0]
  const dates = subject ? replay.subjects[subject] ?? [] : []
  const date = isReplay && dates.includes(feed.date) ? feed.date : dates[0]

  const tickSpeed =
    typeof latest?.speed === 'number' && Number.isFinite(latest.speed)
      ? latest.speed
      : null
  const speed =
    isReplay ? tickSpeed ?? feed.speed : replay.default_speed

  const chooseReplay = () => {
    const next = defaultReplayFeed(sources, feed)
    if (next) onFeed(next)
  }

  const changeSubject = (nextSubject: string) => {
    const nextDates = replay.subjects[nextSubject]
    if (!nextDates || nextDates.length === 0) return
    onFeed({
      source: 'replay',
      subject: nextSubject,
      date: nextDates[0],
      speed,
    })
  }

  const changeDate = (nextDate: string) => {
    if (!subject || !dates.includes(nextDate)) return
    onFeed({ source: 'replay', subject, date: nextDate, speed })
  }

  const line = isReplay ? statusLine(latest) : ''

  return (
    <div className="mb-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-full border border-white/10 bg-surface-lowest/80 p-0.5">
          {offered.map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() =>
                mode === 'simulated' ? onFeed({ source: 'simulated' }) : chooseReplay()
              }
              className={`min-h-[44px] rounded-full px-4 font-mono text-[11px] readout uppercase transition-colors ${
                selectedMode === mode
                  ? 'bg-white/10 text-ink'
                  : 'text-ink/40 hover:text-ink/70'
              }`}
            >
              {mode === 'simulated' ? 'Synthetic' : 'Replay'}
            </button>
          ))}
        </div>

        {isReplay && subjects.length > 1 && (
          <select
            aria-label="Subject"
            value={subject ?? ''}
            onChange={(event) => changeSubject(event.target.value)}
            className={SELECT_CLASS}
          >
            {subjects.map((id) => (
              <option key={id} value={id}>
                {id}
                {replay.fitted[id] === true ? ' · fitted' : ''}
              </option>
            ))}
          </select>
        )}

        {isReplay && (
          <select
            aria-label="Recorded day"
            value={date ?? ''}
            onChange={(event) => changeDate(event.target.value)}
            className={SELECT_CLASS}
          >
            {dates.map((day) => (
              <option key={day} value={day}>
                {day}
              </option>
            ))}
          </select>
        )}
      </div>

      {isReplay && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onTogglePause}
            className="min-h-[44px] rounded-el border-2 border-oxy-container/60 px-4 font-mono text-[11px] font-bold readout uppercase text-oxy transition-colors hover:bg-oxy-container/15"
          >
            {paused ? '▶ Play' : '⏸ Pause'}
          </button>

          {/* One group, so the speeds wrap together rather than leaving the
              last one stranded on a line of its own in a narrow column. */}
          <div className="flex gap-1.5">
            {replay.speeds.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => onSpeed(value)}
                className={`min-h-[44px] min-w-[44px] rounded-el border px-2 font-mono text-[11px] font-bold readout uppercase transition-colors ${
                  speed === value
                    ? 'border-oxy-container/60 bg-oxy-container/15 text-oxy'
                    : 'border-white/10 bg-surface-lowest text-ink/50 hover:text-ink'
                }`}
              >
                ×{value}
              </button>
            ))}
          </div>
        </div>
      )}

      {isReplay && line && (
        <p className="font-mono text-[12px] readout text-ink/55">{line}</p>
      )}

      {isReplay && latest?.ended === true && (
        <div>
          <button
            type="button"
            onClick={onRestart}
            className="min-h-[44px] rounded-el border-2 border-oxy-container/60 px-4 font-mono text-[11px] font-bold readout uppercase text-oxy transition-colors hover:bg-oxy-container/15"
          >
            ▶ Play again
          </button>
        </div>
      )}
    </div>
  )
}
