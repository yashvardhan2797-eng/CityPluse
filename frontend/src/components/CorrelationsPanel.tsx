import type { CorrelationsResponse } from '../types'
import { metricLabel } from '../lib/theme'
import { ListSkeleton } from './Skeletons'

interface CorrelationsPanelProps {
  report: CorrelationsResponse | undefined
  loading: boolean
}

/** Correlation panel: associations with sample size and explicit limits. */
export default function CorrelationsPanel({ report, loading }: CorrelationsPanelProps) {
  if (loading) {
    return <ListSkeleton rows={3} className="h-14" />
  }

  const correlations = report?.correlations ?? []
  return (
    <div className="space-y-3">
      {correlations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">Not enough aligned data yet.</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Correlations need 12+ overlapping hourly points per pair. Run ingestion a few times
            (or let it accumulate hourly demo history), then check back.
          </p>
        </div>
      ) : (
        <ul className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {correlations.map((pair) => {
            const strength = Math.abs(pair.pearson_r)
            const barColor = pair.pearson_r >= 0 ? '#22d3ee' : '#f97316'
            return (
              <li key={`${pair.metric_a}-${pair.metric_b}`} className="rounded-lg border border-white/5 bg-navy-800/60 px-3 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {metricLabel(pair.metric_a)} <span className="text-slate-500">×</span> {metricLabel(pair.metric_b)}
                  </p>
                  <span className="shrink-0 font-mono text-sm text-slate-100">
                    r={pair.pearson_r.toFixed(2)}
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-navy-700">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.round(strength * 100)}%`, backgroundColor: barColor, opacity: 0.8 }}
                  />
                </div>
                <p className="mt-1.5 text-[11px] text-slate-400">{pair.interpretation}</p>
                <p className="mt-0.5 text-[10px] text-slate-500">
                  n={pair.sample_size} · ρ={pair.spearman_rho.toFixed(2)} · {pair.time_scope} · {pair.geographic_scope}
                </p>
              </li>
            )
          })}
        </ul>
      )}

      {(report?.insufficient_pairs ?? 0) > 0 && (
        <p className="text-[11px] text-slate-500">
          {report!.insufficient_pairs} pair(s) skipped: insufficient overlapping observations.
        </p>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">{report?.note}</p>
    </div>
  )
}
