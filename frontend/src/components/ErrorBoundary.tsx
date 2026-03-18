import { Component } from 'react'
import type { ReactNode, ErrorInfo } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ERROR] CardioTwin crash:', error.message)
    console.error('[ERROR] Component stack:', info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-900 flex items-center justify-center p-8">
          <div className="max-w-md w-full bg-slate-800 border border-red-800 rounded-lg p-6 text-center">
            <p className="text-red-400 text-base font-semibold mb-2">Application Error</p>
            <p className="text-slate-400 text-sm mb-1">An unexpected error occurred.</p>
            {this.state.error?.message && (
              <p className="text-slate-600 text-xs font-mono mb-5 break-words">
                {this.state.error.message}
              </p>
            )}
            <button
              onClick={() => window.location.reload()}
              className="px-5 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 text-sm rounded-md transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
