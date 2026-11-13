import { useCallback, useEffect, useState } from 'react'
import { Dashboard } from './components/dashboard/Dashboard'
import { TWIN_FORMS } from './components/dashboard/forms'
import type { TwinForm } from './components/dashboard/forms'
import { feedFromSearch, feedToSearch } from './feed'
import type { FeedRequest } from './hooks/useCardioStream'

/**
 * The app is one screen. Where you are on it lives in the URL, so a link opens
 * the lamina and the form it names and a reload stays there:
 *
 *   #dashboard/<lamina_id>/<animation|graph|table>
 *
 * A bare URL takes the backend's default lamina and the animation. Any other
 * hash, including the old #twin, #body, #stream and #analysis links, opens the
 * dashboard rather than an error.
 */
function readHash(): { lamina: string | null; form: TwinForm; formNamed: boolean } {
  const [screen, lamina, form] = window.location.hash.replace('#', '').split('/')
  if (screen !== 'dashboard') return { lamina: null, form: 'animation', formNamed: false }
  const named = TWIN_FORMS.includes(form as TwinForm)
  return {
    lamina: lamina || null,
    form: named ? (form as TwinForm) : 'animation',
    formNamed: named,
  }
}

export default function App() {
  const [initial] = useState(() => readHash())
  const [laminaId, setLaminaId] = useState<string | null>(initial.lamina)
  const [form, setForm] = useState<TwinForm>(initial.form)
  // Read once, like the hash: a reload may open a different day, but an
  // already-open tab must not keep re-reading a URL it is itself rewriting.
  const [feed, setFeed] = useState<FeedRequest>(() => feedFromSearch(window.location.search))

  // A different lamina is a different model, so a day recorded for the old one
  // is not a feed for the new one.
  const onLamina = useCallback((id: string) => {
    setLaminaId(id)
    setFeed({ source: 'simulated' })
  }, [])

  // Keep the URL in step with the screen and the feed so the current view is
  // shareable.  Every unrelated parameter (scale, idle) and the hash survive.
  useEffect(() => {
    const target =
      laminaId || form !== 'animation'
        ? `#dashboard/${laminaId ?? ''}${form !== 'animation' ? `/${form}` : ''}`
        : ''
    const search = feedToSearch(feed, window.location.search)
    const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
    const next = `${window.location.pathname}${search}${target}`
    if (current !== next) {
      window.history.replaceState(null, '', next)
    }
  }, [laminaId, form, feed])

  return (
    <Dashboard
      lamina={laminaId}
      onLamina={onLamina}
      form={form}
      onForm={setForm}
      feed={feed}
      onFeed={setFeed}
      formNamed={initial.formNamed}
    />
  )
}
