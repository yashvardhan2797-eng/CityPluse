import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Severity } from '../types'
import { SEVERITIES } from '../types'
import { SEVERITY_COLORS, SEVERITY_LABELS } from '../lib/theme'
import { ChartSkeleton } from './Skeletons'

interface SeverityChartProps {
  breakdown: Record<Severity, number> | undefined
  loading: boolean
}

const DARK_TOOLTIP = {
  backgroundColor: '#0d1729',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 12,
  color: '#e2e8f0',
  fontSize: 12,
}

/** Bar chart of record counts per severity bucket. */
export default function SeverityChart({ breakdown, loading }: SeverityChartProps) {
  const data = SEVERITIES.map((severity) => ({
    severity,
    name: SEVERITY_LABELS[severity],
    count: breakdown?.[severity] ?? 0,
  }))
  const total = data.reduce((sum, d) => sum + d.count, 0)

  if (loading) {
    return <ChartSkeleton className="h-56" />
  }

  if (total === 0) {
    return (
      <div className="flex h-56 items-center justify-center rounded-lg border border-dashed border-white/10 text-sm text-slate-400">
        No records available for this city yet.
      </div>
    )
  }

  return (
    <div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              contentStyle={DARK_TOOLTIP}
              itemStyle={{ color: '#e2e8f0' }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value) => [`${value} records`, 'Count']}
            />
            <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={46}>
              {data.map((entry) => (
                <Cell key={entry.severity} fill={SEVERITY_COLORS[entry.severity]} fillOpacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {data.map((entry) => (
          <span key={entry.severity} className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: SEVERITY_COLORS[entry.severity] }} />
            {entry.name}: <span className="font-mono text-slate-200">{entry.count}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
