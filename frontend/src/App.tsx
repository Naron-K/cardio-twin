import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { PlanPage } from './components/plan/PlanPage'
import { RecordedDays } from './components/recorded/RecordedDays'
import { searchForView, viewFromSearch } from './twin/sources'
import type { PageView } from './twin/sources'

const VIEWS: { view: PageView; label: string }[] = [
  { view: 'plan', label: 'Plan a day' },
  { view: 'recorded', label: 'Recorded days' },
]

const TAB_CLASS =
  'min-h-[44px] rounded-t-el px-4 font-mono text-[14px] readout uppercase transition-colors'

/**
 * The app shell: two views behind a tab row.  The view lives in the URL
 * (`?view=plan` or `?view=recorded&subject=…&date=…`), so a link reopens it.
 */
export default function App() {
  const [view, setView] = useState<PageView>(() => viewFromSearch(window.location.search))
  const tabs = useRef<Record<PageView, HTMLButtonElement | null>>({ plan: null, recorded: null })

  useEffect(() => {
    const onPop = () => setView(viewFromSearch(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const select = useCallback((next: PageView) => {
    const search = searchForView(next, window.location.search)
    window.history.pushState(null, '', `${window.location.pathname}${search}`)
    setView(next)
  }, [])

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const index = VIEWS.findIndex((item) => item.view === view)
    const step = event.key === 'ArrowRight' ? 1 : -1
    const next = VIEWS[(index + step + VIEWS.length) % VIEWS.length].view
    select(next)
    tabs.current[next]?.focus()
  }

  return (
    <div className="min-h-app flex flex-col bg-surface text-ink font-body">
      <div
        role="tablist"
        aria-label="Views"
        className="flex shrink-0 gap-1 px-4 pt-4 wide:px-margin wide:pt-gutter"
      >
        {VIEWS.map(({ view: item, label }) => {
          const selected = item === view
          return (
            <button
              key={item}
              ref={(node) => {
                tabs.current[item] = node
              }}
              type="button"
              role="tab"
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(item)}
              onKeyDown={onKeyDown}
              className={`${TAB_CLASS} ${
                selected
                  ? 'bg-surface-low font-bold text-ink underline decoration-oxy decoration-2 underline-offset-4'
                  : 'text-ink/60 hover:text-ink'
              }`}
            >
              {label}
            </button>
          )
        })}
      </div>

      {view === 'recorded' ? <RecordedDays /> : <PlanPage />}
    </div>
  )
}
