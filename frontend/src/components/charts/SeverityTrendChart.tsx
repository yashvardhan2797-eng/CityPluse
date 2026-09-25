import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SeveritySeriesResponse } from '../../types'
import { SEVERITIES } from '../../types'
import { AXIS_STYLE, GRID_STROKE, TOOLTIP_LABEL, TOOLTIP_STYLE } from '../../lib/charts'
import { SEVERITY_COLORS, SEVERITY_LABELS } from '../../lib/theme'
import { ChartSkeleton } from '../Skeletons'

interface Props {
  report: SeveritySeriesResponse | undefined
  loading: boolean
}

/** Stacked severity counts per bucket — how incident pressure moved over time. */
export default function SeverityTrendChart({ report, loading }: Props) {
  const data = useMemo(() => {
    const byBucket = new Map<string, Record<string, number | string>>()
    for (const row of report?.series ?? []) {
      if (!byBucket.has(row.bucket)) {
        byBucket.set(row.bucket, { time: row.bucket.slice(5, 16).replace('T', ' ') })
      }
      const point = byBucket.get(row.bucket)!
      point[row.severity] = (point[row.severity] as number ?? 0) + row.count
    }
    return [...byBucket.values()].sort((a, b) => String(a.time).localeCompare(String(b.time)))
  }, [report])

  if (loading) return <ChartSkeleton className="h-52" />

  if (data.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-white/10 p-4">
        <p className="text-sm text-slate-300">No severity-tagged observations in this window.</p>
        <p className="mt-1 text-[11px] text-slate-500">
          Stacked counts appear once ingestion stores severity-classified records.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="time" tick={AXIS_STYLE} interval="preserveStartEnd" />
            <YAxis allowDecimals={false} tick={AXIS_STYLE} width={40} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {SEVERITIES.map((severity) => (
              <Bar
                key={severity}
                dataKey={severity}
                name={SEVERITY_LABELS[severity]}
                stackId="sev"
                fill={SEVERITY_COLORS[severity]}
                maxBarSize={30}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-slate-500">
        Observation counts per severity per {report?.bucket ?? 'hour'} — from stored records only;
        buckets without data are absent, never zero-filled.
      </p>
    </div>
  )
}
