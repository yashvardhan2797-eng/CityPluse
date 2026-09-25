import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { EventsResponse, Severity } from '../../types'
import { SEVERITIES } from '../../types'
import { AXIS_STYLE, GRID_STROKE, TOOLTIP_LABEL, TOOLTIP_STYLE } from '../../lib/charts'
import { SEVERITY_COLORS, SEVERITY_LABELS } from '../../lib/theme'
import { ChartSkeleton } from '../Skeletons'

interface Props {
  events: EventsResponse | undefined
  loading: boolean
}

const STATUS_COLOR: Record<string, string> = {
  open: '#f59e0b', acknowledged: '#22d3ee', in_progress: '#60a5fa',
  resolved: '#34d399', closed: '#64748b',
}

/** Event/incident analytics: status split, severity profile, recent resolution times. */
export default function EventsAnalytics({ events, loading }: Props) {
  const data = useMemo(() => {
    const list = events?.events ?? []
    const byStatus = new Map<string, number>()
    const bySeverity = new Map<Severity, number>()
    for (const e of list) {
      byStatus.set(e.status, (byStatus.get(e.status) ?? 0) + 1)
      bySeverity.set(e.severity, (bySeverity.get(e.severity) ?? 0) + 1)
    }
    const resolutionHours: number[] = []
    for (const e of list) {
      if (e.resolved_at && e.reported_at) {
        const h = (new Date(e.resolved_at).getTime() - new Date(e.reported_at).getTime()) / 3_600_000
        if (h >= 0) resolutionHours.push(h)
      }
    }
    resolutionHours.sort((a, b) => a - b)
    const medianH = resolutionHours.length
      ? resolutionHours[Math.floor(resolutionHours.length / 2)]
      : null
    return {
      statusData: [...byStatus].map(([status, count]) => ({ status, count })),
      severityData: SEVERITIES.map((severity) => ({
        severity,
        name: SEVERITY_LABELS[severity],
        count: bySeverity.get(severity) ?? 0,
      })),
      resolutionHours,
      medianH,
      total: list.length,
    }
  }, [events])

  if (loading) return <ChartSkeleton className="h-56" />

  if (data.total === 0) {
    return (
      <div className="rounded-lg border border-dashed border-white/10 p-4">
        <p className="text-sm text-slate-300">No civic events recorded for this city yet.</p>
        <p className="mt-1 text-[11px] text-slate-500">
          Events are created by the event lifecycle (and labeled simulation drills) — analytics
          appear once events exist.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {data.statusData.map((s) => (
          <div key={s.status} className="rounded-lg border border-white/5 bg-navy-800/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-slate-500">{s.status.replace('_', ' ')}</p>
            <p className="text-lg font-bold" style={{ color: STATUS_COLOR[s.status] ?? '#94a3b8' }}>
              {s.count}
            </p>
          </div>
        ))}
      </div>

      <div className="h-36">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.severityData} margin={{ top: 4, right: 6, left: -24, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis dataKey="name" tick={AXIS_STYLE} />
            <YAxis allowDecimals={false} tick={AXIS_STYLE} width={34} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
            <Bar dataKey="count" name="Events" radius={[4, 4, 0, 0]} maxBarSize={44} isAnimationActive={false}>
              {data.severityData.map((entry) => (
                <Cell key={entry.severity} fill={SEVERITY_COLORS[entry.severity]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[10px] leading-relaxed text-slate-500">
        {data.resolutionHours.length > 0
          ? `Resolved events: n=${data.resolutionHours.length}, median ${data.medianH?.toFixed(1)}h from report to resolve (range ${data.resolutionHours[0].toFixed(1)}–${data.resolutionHours[data.resolutionHours.length - 1].toFixed(1)}h).`
          : 'No resolved events in this window yet — resolution-time stats appear as events are resolved.'}
        {' '}Statuses reflect the event lifecycle; simulation drills are labeled in the events list.
      </p>
    </div>
  )
}
