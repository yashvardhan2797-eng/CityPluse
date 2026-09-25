import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { HistoryResponse } from '../types'
import { metricLabel, METRIC_COLORS } from '../lib/theme'
import { formatClock } from '../lib/ui'
import { ChartSkeleton } from './Skeletons'
import { TogglePill } from './TogglePill'

interface HistoryChartProps {
  report: HistoryResponse | undefined
  loading: boolean
  hours: number
  onHoursChange: (hours: number) => void
  onRefresh: () => void
  refreshing?: boolean
}

const WINDOW_OPTIONS = [24, 48, 72, 168]

/** Phase 4 historical replay: hourly averages from stored records only. */
export default function HistoryChart({ report, loading, hours, onHoursChange, onRefresh, refreshing }: HistoryChartProps) {
  const series = useMemo(() => {
    const byMetric = new Map<string, Map<string, number>>()
    for (const row of report?.buckets ?? []) {
      if (row.avg_value == null) continue
      if (!byMetric.has(row.metric)) byMetric.set(row.metric, new Map())
      byMetric.get(row.metric)!.set(row.bucket, row.avg_value)
    }
    const allBuckets = [...new Set([...byMetric.values()].flatMap((m) => [...m.keys()]))].sort()
    return allBuckets.map((bucket) => {
      const point: Record<string, number | null | string> = {
        time: formatClock(bucket),
        _bucket: bucket,
      }
      for (const [metric, values] of byMetric) {
        // Missing hours stay null — the chart shows the gap, never a zero.
        point[metric] = values.get(bucket) ?? null
      }
      return point
    })
  }, [report])

  const metricNames = useMemo(
    () => [...new Set((report?.buckets ?? []).map((b) => b.metric))].slice(0, 6),
    [report],
  )

  const coverage = report?.coverage ?? {}
  const mode = report?.mode ?? 'demo'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5" role="group" aria-label="History window">
          {WINDOW_OPTIONS.map((h) => (
            <TogglePill
              key={h}
              label={h >= 24 ? `${h / 24}d` : `${h}h`}
              active={hours === h}
              onSelect={() => onHoursChange(h)}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="rounded-md border border-white/10 bg-navy-800 px-2.5 py-1 text-[11px] font-semibold text-slate-300 transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-50"
        >
          {refreshing ? 'Loading…' : 'Reload'}
        </button>
      </div>

      {loading ? <ChartSkeleton className="h-56" /> : series.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">No stored observations in this window.</p>
          <p className="mt-1 text-[11px] text-slate-500">
            The replay shows only what was actually recorded — gaps are never filled with
            synthetic or interpolated values.
          </p>
        </div>
      ) : (
        <>
          <div className="h-56" data-testid="history-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#64748b' }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10, fill: '#64748b' }} width={52} />
                <Tooltip
                  contentStyle={{ background: '#0b1220ee', border: '1px solid rgba(148,163,184,0.2)', borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: '#94a3b8' }}
                />
                <Legend wrapperStyle={{ fontSize: 10 }} formatter={(v) => metricLabel(String(v))} />
                {metricNames.map((metric, i) => (
                  <Line
                    key={metric}
                    type="monotone"
                    dataKey={metric}
                    name={metricLabel(metric)}
                    stroke={METRIC_COLORS[i % METRIC_COLORS.length]}
                    strokeWidth={1.8}
                    dot={false}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-[10px] leading-relaxed text-slate-500">
            {mode === 'database' ? 'From stored civic_data records' : 'Synthetic demo replay'} ·{' '}
            {Object.entries(coverage).map(([metric, c]) => `${metricLabel(metric)}: ${c.points}h`).join(' · ')}
            {' '}— gaps mean no observations existed; nothing is interpolated.
          </p>
        </>
      )}
    </div>
  )
}
