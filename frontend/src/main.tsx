import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastProvider } from './components/Toast'

// React 19's development build records a performance.measure for every
// component render, carrying a diff of the props that changed, and the
// browser keeps every entry until something clears them. A screen that
// re-renders a chart at 10 Hz piles them up: measured on the dashboard,
// 267,000 entries after 156 s, and a tab left open on it for about twenty
// minutes failed inside React with "DataCloneError: ... out of memory".
// Clearing every 10 s holds it near 10,000. Production builds record nothing,
// so this only keeps `npm run dev` alive through a long demo.
if (import.meta.env.DEV) {
  setInterval(() => performance.clearMeasures(), 10_000)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <ToastProvider>
        <App />
      </ToastProvider>
    </ErrorBoundary>
  </StrictMode>,
)
