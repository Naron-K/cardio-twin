import { useEffect, useState } from 'react'
import { Dashboard } from './components/dashboard/Dashboard'
import { TWIN_FORMS } from './components/dashboard/forms'
import type { TwinForm } from './components/dashboard/forms'

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
function readHash(): { lamina: string | null; form: TwinForm } {
  const [screen, lamina, form] = window.location.hash.replace('#', '').split('/')
  if (screen !== 'dashboard') return { lamina: null, form: 'animation' }
  return {
    lamina: lamina || null,
    form: TWIN_FORMS.includes(form as TwinForm) ? (form as TwinForm) : 'animation',
  }
}

export default function App() {
  const [laminaId, setLaminaId] = useState<string | null>(() => readHash().lamina)
  const [form, setForm] = useState<TwinForm>(() => readHash().form)

  // Keep the URL in step with the screen so the current view is shareable.
  useEffect(() => {
    const target =
      laminaId || form !== 'animation'
        ? `#dashboard/${laminaId ?? ''}${form !== 'animation' ? `/${form}` : ''}`
        : ''
    if (window.location.hash !== target) {
      window.history.replaceState(null, '', target || window.location.pathname)
    }
  }, [laminaId, form])

  return <Dashboard lamina={laminaId} onLamina={setLaminaId} form={form} onForm={setForm} />
}
