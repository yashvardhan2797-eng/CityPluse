import { motion } from 'framer-motion'
import type { ProviderInfo, RefreshResponse } from '../types'
import { timeAgo } from '../lib/ui'
import { sourceLabel } from '../lib/theme'
import { ListSkeleton } from './Skeletons'

interface SourceHealthProps {
  sources: ProviderInfo[] | undefined
  loading: boolean
  lastRefreshSecondsAgo: number | null
  refreshing: boolean
  refreshResult: RefreshResponse | null
  onRefresh: () => void
}

const MODE_BADGE: Record<string, { label: string; cls: string }> = {
  live: { label: 'LIVE', cls: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300' },
  synthetic: { label: 'SIMULATED', cls: 'border-amber-400/40 bg-amber-500/10 text-amber-300' },
  configured: { label: 'READY', cls: 'border-sky-400/40 bg-sky-500/10 text-sky-300' },
  unconfigured: { label: 'NOT SET UP', cls: 'border-white/10 bg-white/5 text-slate-400' },
}

/** Provider health + freshness panel with the manual refresh trigger. */
export default function SourceHealth({
  sources,
  loading,
  lastRefreshSecondsAgo,
  refreshing,
  refreshResult,
  onRefresh,
}: SourceHealthProps) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-400">
          Last ingestion:{' '}
          <span className="font-mono text-slate-200">
            {lastRefreshSecondsAgo === null || lastRefreshSecondsAgo === undefined
              ? 'never'
              : timeAgo(new Date(Date.now() - lastRefreshSecondsAgo * 1000).toISOString())}
          </span>
        </p>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg
            className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
          >
            <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
          </svg>
          {refreshing ? 'Ingesting…' : 'Refresh data'}
        </button>
      </div>

      {refreshResult?.skipped && refreshResult.reason && (
        <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-[11px] text-amber-200">
          {refreshResult.reason}
        </div>
      )}
      {refreshResult && !refreshResult.skipped && refreshResult.sources && (
        <div className="rounded-lg border border-emerald-400/25 bg-emerald-400/5 px-3 py-2 text-[11px] text-emerald-200">
          Ingestion complete:{' '}
          {refreshResult.sources
            .map((s) => `${s.source_type} ${s.records_stored}${s.mode === 'demo' ? ' (demo)' : ''}`)
            .join(' · ')}
        </div>
      )}

      {loading ? <ListSkeleton rows={4} className="h-14" /> : (
        <ul className="space-y-2">
          {(sources ?? []).map((source, index) => {
            const badge = MODE_BADGE[source.mode] ?? MODE_BADGE.unconfigured
            return (
              <motion.li
                key={source.source_type}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: index * 0.05 }}
                className="rounded-lg border border-white/5 bg-navy-800/60 px-3 py-2.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <p className="truncate text-sm font-medium text-slate-100">
                      {sourceLabel(source.source_type)}
                    </p>
                    <span className="font-mono text-[10px] text-slate-500">{source.provider}</span>
                  </div>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold ${badge.cls}`}>
                    {badge.label}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-3">
                  <p className="truncate text-[11px] text-slate-400">
                    {source.last_success_at
                      ? `last ok ${timeAgo(source.last_success_at)}`
                      : source.configured
                        ? 'configured, not fetched yet'
                        : 'no credentials — demo data'}
                  </p>
                  <p className="shrink-0 font-mono text-[10px] text-slate-500">
                    {source.record_count_last > 0 ? `+${source.record_count_last} rows` : ''}
                  </p>
                </div>
                {source.last_error && (
                  <p className="mt-1 truncate text-[10px] text-rose-300/90" title={source.last_error}>
                    ⚠ {source.last_error}
                  </p>
                )}
              </motion.li>
            )
          })}
        </ul>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">
        Sources without credentials serve clearly-labeled simulated data. Weather uses Open-Meteo
        (keyless); air quality needs a free OpenAQ key; transit/incidents need a feed URL in .env.
      </p>
    </div>
  )
}
