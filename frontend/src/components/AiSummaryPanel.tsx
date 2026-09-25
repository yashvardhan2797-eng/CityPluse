import { motion } from 'framer-motion'
import type { AiSummaryResponse } from '../types'
import { formatClock } from '../lib/ui'
import { TextSkeleton } from './Skeletons'

interface AiSummaryPanelProps {
  report: AiSummaryResponse | undefined
  loading: boolean
  error: unknown
}

/** Civic briefing panel: deterministic or AI, always grounded + labeled. */
export default function AiSummaryPanel({ report, loading, error }: AiSummaryPanelProps) {
  const isAi = report?.generated_by?.startsWith('ai:')

  return (
    <div className="space-y-3">
      {loading ? (
        <TextSkeleton lines={3} />
      ) : error || !report ? (
        <p className="text-sm text-slate-400">
          Summary unavailable — the API could not generate a briefing.
        </p>
      ) : (
        <>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4 }}
            className="text-sm leading-relaxed text-slate-200"
          >
            {report.summary}
          </motion.p>

          <div className="flex flex-wrap items-center gap-2 text-[10px]">
            <span
              className={`rounded-full border px-2 py-0.5 font-semibold ${
                isAi
                  ? 'border-violet-400/40 bg-violet-500/10 text-violet-300'
                  : 'border-sky-400/40 bg-sky-500/10 text-sky-300'
              }`}
            >
              {isAi ? `AI: ${report.generated_by.slice(3)}` : 'DETERMINISTIC SUMMARY'}
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">
              generated {formatClock(report.generated_at)}
            </span>
            <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-slate-400">
              window {report.window_hours}h
            </span>
          </div>

          <details className="text-[11px] text-slate-400">
            <summary className="cursor-pointer select-none text-slate-500">
              Evidence used ({report.grounded_in.observations.length} observations
              {report.grounded_in.recent_anomalies.length > 0
                ? `, ${report.grounded_in.recent_anomalies.length} anomaly flags`
                : ''}
              )
            </summary>
            <ul className="mt-1.5 space-y-1 pl-3">
              {report.grounded_in.observations.slice(0, 8).map((o) => (
                <li key={`${o.source_type}-${o.metric}`} className="font-mono text-[10px] text-slate-400">
                  {o.metric}: {o.value ?? '—'} {o.unit}
                  {o.synthetic ? ' · synthetic' : ''} · {o.recorded_at?.slice(0, 16).replace('T', ' ')}Z
                </li>
              ))}
            </ul>
          </details>

          <p className="text-[10px] leading-relaxed text-slate-500">{report.disclaimer}</p>
        </>
      )}
    </div>
  )
}
