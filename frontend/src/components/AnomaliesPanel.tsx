import type { AnomaliesResponse } from '../types'
import { metricLabel, sourceLabel } from '../lib/theme'
import { formatNumber } from '../lib/ui'
import { ListSkeleton } from './Skeletons'

interface AnomaliesPanelProps {
  report: AnomaliesResponse | undefined
  loading: boolean
  onDetect: () => void
  detecting: boolean
}

/** Anomaly panel: what was flagged, with evidence — never a causal claim. */
export default function AnomaliesPanel({ report, loading, onDetect, detecting }: AnomaliesPanelProps) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-400">
          Robust z-score vs rolling baseline ({report?.window_hours ?? 72}h window)
        </p>
        <button
          type="button"
          onClick={onDetect}
          disabled={detecting}
          className="rounded-lg border border-white/10 bg-navy-800 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-50"
        >
          {detecting ? 'Analyzing…' : 'Run detection'}
        </button>
      </div>

      {loading ? <ListSkeleton rows={2} className="h-16" /> : (report?.anomalies?.length ?? 0) === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">No anomalies flagged.</p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            {report?.note ?? 'Statistical flags only — an anomaly is not an explanation.'}
          </p>
        </div>
      ) : (
        <ul className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {report!.anomalies.map((a) => (
            <li key={`${a.metric}-${a.observed_bucket}`} className="rounded-lg border border-orange-400/25 bg-orange-400/5 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-sm font-medium text-slate-100">
                  {metricLabel(a.metric)}{' '}
                  <span className="text-[10px] font-normal text-slate-500">({sourceLabel(a.source_type)})</span>
                </p>
                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${
                    a.confidence === 'medium'
                      ? 'border-orange-400/40 bg-orange-400/10 text-orange-300'
                      : 'border-white/10 bg-white/5 text-slate-300'
                  }`}
                >
                  {a.confidence} confidence
                </span>
              </div>
              <div className="mt-1 grid grid-cols-3 gap-2 text-[11px]">
                <span className="text-slate-400">
                  observed <span className="font-mono text-slate-100">{formatNumber(a.observed_value)}</span>
                </span>
                <span className="text-slate-400">
                  baseline <span className="font-mono text-slate-100">{formatNumber(a.baseline_value)}</span>
                </span>
                <span className="text-slate-400">
                  z <span className="font-mono text-slate-100">{formatNumber(a.deviation_score)}</span>
                </span>
              </div>
              <p className="mt-1 text-[10px] text-slate-500">
                {a.method} · n={a.sample_size} · {a.observed_bucket?.slice(0, 16).replace('T', ' ')}Z
              </p>
            </li>
          ))}
        </ul>
      )}

      {(report?.insufficient_data?.length ?? 0) > 0 && (
        <details className="text-[11px] text-slate-400">
          <summary className="cursor-pointer select-none text-slate-500">
            {report!.insufficient_data!.length} metric(s) lacked enough history
          </summary>
          <ul className="mt-1 space-y-0.5 pl-3">
            {report!.insufficient_data!.map((d) => (
              <li key={`${d.source_type}-${d.metric}`} className="truncate">
                {metricLabel(d.metric)}: {d.reason}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">
        An anomaly means “unusual vs recent history”. It does not explain the cause.
      </p>
    </div>
  )
}
