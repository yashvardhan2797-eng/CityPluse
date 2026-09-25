import { useState } from 'react'
import { motion } from 'framer-motion'
import type { AlertInstance, AlertsResponse } from '../types'
import { metricLabel } from '../lib/theme'
import { formatClock } from '../lib/ui'
import { ListSkeleton } from './Skeletons'
import { TogglePill } from './TogglePill'

interface AlertCenterProps {
  report: AlertsResponse | undefined
  loading: boolean
  busyKey: string | null
  onAcknowledge: (key: string) => void
  onDismiss: (key: string) => void
}

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
  high: 'border-orange-400/40 bg-orange-400/10 text-orange-200',
  moderate: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  low: 'border-sky-400/30 bg-sky-400/10 text-sky-200',
}

/** Phase 4 alert center: evidence-based, deduplicated, informational only. */
export default function AlertCenter({ report, loading, busyKey, onAcknowledge, onDismiss }: AlertCenterProps) {
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const all: AlertInstance[] = report?.alerts ?? []
  const alerts =
    severityFilter === 'all' ? all : all.filter((a) => a.severity === severityFilter)

  return (
    <div className="space-y-3">
      <p className="text-[11px] leading-relaxed text-slate-500">
        Informational civic observations from verified anomalies and configured thresholds —
        <span className="text-slate-400">        not official emergency warnings.</span>
      </p>

      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Severity filter">
        {['all', 'critical', 'high', 'moderate', 'low'].map((level) => (
          <TogglePill
            key={level}
            label={level === 'all' ? 'All severities' : level}
            active={severityFilter === level}
            onSelect={() => setSeverityFilter(level)}
          />
        ))}
      </div>

      {loading ? <ListSkeleton rows={2} className="h-20" /> : alerts.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">No active alerts.</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Alerts appear when the analytics engine flags an anomaly or a configured threshold is
            crossed by stored observations.
          </p>
        </div>
      ) : (
        <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
          {alerts.map((alert) => (
            <motion.li
              key={alert.dedup_key}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className={`rounded-lg border px-3 py-2.5 ${SEVERITY_STYLE[alert.severity] ?? SEVERITY_STYLE.low}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">
                    {alert.title}
                    {alert.is_synthetic && (
                      <span className="ml-2 rounded border border-white/20 px-1 py-px text-[9px] font-bold uppercase tracking-wider text-slate-300">
                        sim
                      </span>
                    )}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-300/90">{alert.summary}</p>
                </div>
                <span className="shrink-0 rounded-full border border-white/15 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider">
                  {alert.severity}
                </span>
              </div>

              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-400">
                {alert.metric && <span>metric: {metricLabel(alert.metric)}</span>}
                <span>detected {formatClock(alert.detected_at)}Z</span>
                {alert.location_name && <span className="truncate">{alert.location_name}</span>}
              </div>

              <div className="mt-2 flex gap-2">
                {alert.dismissed_at ? (
                  <span className="text-[10px] text-slate-500">dismissed</span>
                ) : (
                  <>
                    {!alert.acknowledged_at && (
                      <button
                        type="button"
                        disabled={busyKey === alert.dedup_key}
                        onClick={() => onAcknowledge(alert.dedup_key)}
                        className="rounded-md border border-white/10 bg-navy-800/80 px-2 py-1 text-[10px] font-semibold text-slate-200 transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-50"
                      >
                        {busyKey === alert.dedup_key ? '…' : 'Acknowledge'}
                      </button>
                    )}
                    {alert.acknowledged_at && (
                      <span className="text-[10px] text-emerald-300/80">
                        acknowledged {formatClock(alert.acknowledged_at)}Z
                      </span>
                    )}
                    <button
                      type="button"
                      disabled={busyKey === alert.dedup_key}
                      onClick={() => onDismiss(alert.dedup_key)}
                      className="rounded-md border border-white/10 px-2 py-1 text-[10px] text-slate-400 transition-colors hover:border-rose-400/40 hover:text-rose-300 disabled:opacity-50"
                    >
                      Dismiss
                    </button>
                  </>
                )}
              </div>
            </motion.li>
          ))}
        </ul>
      )}
    </div>
  )
}
