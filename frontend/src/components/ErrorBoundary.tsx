import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Phase 4: app-level error boundary — a render crash shows a recoverable
 * error state instead of a blank page. Retrying unmounts the failed subtree
 * and remounts it fresh; reloading is always available as the safe option.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Console only — no stack traces or data are sent anywhere.
    console.error('[CityPulse] render error captured:', error, info.componentStack)
  }

  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <div
        role="alert"
        className="flex min-h-screen flex-col items-center justify-center gap-4 bg-navy-900 px-6 text-center"
      >
        <h1 className="text-lg font-semibold text-slate-100">Something went wrong</h1>
        <p className="max-w-md text-sm text-slate-400">
          The dashboard hit an unexpected error and stopped rendering. Your data is unaffected —
          recovering or reloading usually resolves it.
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="rounded-lg border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-semibold text-accent transition-colors hover:bg-accent/20"
          >
            Try to recover
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg border border-white/10 bg-navy-800 px-4 py-2 text-sm font-semibold text-slate-200 transition-colors hover:border-white/25"
          >
            Reload dashboard
          </button>
        </div>
        {this.state.error && (
          <pre className="max-w-xl overflow-auto rounded-lg border border-white/10 bg-navy-800/60 p-3 text-left text-[11px] text-slate-500">
            {this.state.error.message}
          </pre>
        )}
      </div>
    )
  }
}
