import { useMemo, useState } from 'react'
import type { LocationsResponse } from '../types'
import { metricLabel } from '../lib/theme'
import { formatNumber } from '../lib/ui'
import { ListSkeleton } from './Skeletons'
import { TogglePill } from './TogglePill'

interface LocationsPanelProps {
  report: LocationsResponse | undefined
  loading: boolean
  hours: number
}

/** Phase 4 location comparison — coverage-honest, alphabetically listed (no ranking). */
export default function LocationsPanel({ report, loading, hours }: LocationsPanelProps) {
  const [metricFilter, setMetricFilter] = useState<string>('all')

  const metricNames = useMemo(() => {
    const names = new Set<string>()
    for (const entry of report?.locations ?? []) {
      for (const metric of Object.keys(entry.metrics)) names.add(metric)
    }
    return [...names].sort().slice(0, 8)
  }, [report])

  const locations = useMemo(() => {
    const all = report?.locations ?? []
    if (metricFilter === 'all') return all
    // A metric filter narrows both the rows (locations that have the metric)
    // and the columns (only that metric's stat) so the toggle does what it
    // visually promises.
    return all
      .filter((entry) => metricFilter in entry.metrics)
      .map((entry) => ({ ...entry, metrics: { [metricFilter]: entry.metrics[metricFilter] } }))
  }, [report, metricFilter])

  const maxObs = useMemo(
    () => Math.max(1, ...locations.map((l) => l.observations)),
    [locations],
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <TogglePill label="All metrics" active={metricFilter === 'all'} onSelect={() => setMetricFilter('all')} />
        {metricNames.map((metric) => (
          <TogglePill
            key={metric}
            label={metricLabel(metric)}
            active={metricFilter === metric}
            onSelect={() => setMetricFilter(metric)}
          />
        ))}
      </div>

      {loading ? <ListSkeleton rows={3} className="h-14" /> : locations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">No geocoded observations in this window.</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Comparison needs records with distinct location names; run ingestion to collect them.
          </p>
        </div>
      ) : (
        <ul className="max-h-72 space-y-2 overflow-y-auto pr-1">
          {locations.map((entry) => (
            <li key={entry.location} className="rounded-lg border border-white/10 bg-navy-800/50 px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-sm font-medium text-slate-100">{entry.location}</p>
                {entry.includes_synthetic && (
                  <span className="shrink-0 rounded border border-amber-400/30 px-1 py-px text-[9px] font-bold uppercase tracking-wider text-amber-300/90">
                    incl. sim
                  </span>
                )}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-300">
                {Object.entries(entry.metrics).map(([metric, stat]) => (
                  <span key={metric}>
                    {metricLabel(metric)}:{' '}
                    <span className="font-mono text-slate-100">{formatNumber(stat.avg_value)}</span>
                    <span className="text-[10px] text-slate-500"> (n={stat.observations})</span>
                  </span>
                ))}
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-500">
                <span>coverage: {entry.hours_covered}h · {entry.observations} obs</span>
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/5">
                  <div
                    className="h-full rounded-full bg-accent/40"
                    style={{ width: `${Math.round((entry.observations / maxObs) * 100)}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] leading-relaxed text-slate-500">
        {report?.note ??
          'Comparisons describe available observations only; locations differ in coverage and sample size. No ranking is implied.'}
        {' '}Window: {hours}h.
      </p>
    </div>
  )
}
