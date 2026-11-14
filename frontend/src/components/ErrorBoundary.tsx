import { Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  /** Seconds until the page reloads itself, counting down. */
  countdown: number
}

/**
 * The dashboard runs unattended on a wall display, where nobody may be near
 * enough to press a button. A crash therefore says what happened, offers the
 * reload, and also reloads by itself after half a minute, so the screen comes
 * back without a visit.
 */
const AUTO_RELOAD_S = 30

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, countdown: AUTO_RELOAD_S }
  private timer: ReturnType<typeof setInterval> | null = null

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error, countdown: AUTO_RELOAD_S }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ERROR] CardioTwin crash:', error.message)
    console.error('[ERROR] Component stack:', info.componentStack)
    if (this.timer) return
    this.timer = setInterval(() => {
      const next = this.state.countdown - 1
      if (next <= 0) window.location.reload()
      else this.setState({ countdown: next })
    }, 1_000)
  }

  componentWillUnmount() {
    if (this.timer) clearInterval(this.timer)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-surface text-ink font-body flex items-center justify-center p-8">
          <div className="max-w-lg w-full rounded-card border-2 border-crimson-container/70 bg-surface-low/90 shadow-bloom-sm p-8 text-center">
            <p className="font-mono text-[11px] font-bold readout uppercase text-crimson-container">
              Something went wrong
            </p>
            <h1 className="font-display text-xl font-semibold mt-2">The page stopped</h1>
            <p className="mt-3 text-[14px] leading-relaxed text-ink/70">
              A part of the screen failed while drawing. Reloading starts it again from the
              server; nothing on the server was lost.
            </p>
            {this.state.error?.message && (
              <p className="mt-4 font-mono text-[11px] text-ink/35 break-words">
                {this.state.error.message}
              </p>
            )}
            <button
              onClick={() => window.location.reload()}
              className="mt-6 min-h-[48px] px-6 rounded-full border-2 border-crimson-container/60
                         bg-crimson-container/15 text-crimson font-mono text-[12px] font-bold readout uppercase"
            >
              Reload now
            </button>
            <p className="mt-3 font-mono text-[11px] readout text-ink/40">
              Reloading by itself in {this.state.countdown}s
            </p>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
