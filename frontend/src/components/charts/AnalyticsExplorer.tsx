import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { HistoryResponse, LocationsResponse } from '../../types'
import { AXIS_STYLE, GRID_STROKE, TOOLTIP_LABEL, TOOLTIP_STYLE, seriesColor } from '../../lib/charts'
import { metricLabel } from '../../lib/theme'
import { ChartSkeleton } from '../Skeletons'
import { TogglePill } from '../TogglePill'

interface Props {
  history: HistoryResponse | undefined
  locations: LocationsResponse | undefined
  loading: boolean
  hours: number
  onHoursChange: (h: number) => void
}

type VizKind = 'line' | 'area' | 'bar'

const VIZ_OPTIONS: Array<{ kind: VizKind; label: string }> = [
  { kind: 'line', label: 'Line' },
  { kind: 'area', label: 'Area' },
  { kind: 'bar', label: 'Bar' },
]

const HISTORY_WINDOWS = [24, 48, 72, 168]

/** One config-driven explorer: metric × window × chart-type, plus a zone radar. */
export default function AnalyticsExplorer({ history, locations, loading, hours, onHoursChange }: Props) {
  const [selected, setSelected] = useState<string[]>(['pm25_ugm3'])
  const [viz, setViz] = useState<VizKind>('line')

  const metricNames = useMemo(
    () => [...new Set((history?.buckets ?? []).map((b) => b.metric))].slice(0, 8),
    [history],
  )
  const activeMetrics = metricNames.filter((m) => selected.includes(m))

  const series = useMemo(() => {
    const byMetric = new Map<string, Map<string, number>>()
    for (const row of history?.buckets ?? []) {
      if (row.avg_value == null || !selected.includes(row.metric)) continue
      byMetric.set(row.metric, (byMetric.get(row.metric) ?? new Map()).set(row.bucket, row.avg_value))
    }
    const allBuckets = [...new Set([...byMetric.values()].flatMap((m) => [...m.keys()]))].sort()
    return allBuckets.map((bucket) => {
      const point: Record<string, number | null | string> = { time: bucket.slice(11, 16), bucket }
      for (const [metric, values] of byMetric) point[metric] = values.get(bucket) ?? null
      return point
    })
  }, [history, selected])

  const radarData = useMemo(() => {
    if (!locations?.locations?.length) return []
    const all = locations.locations
      .filter((l) => l.metrics && Object.keys(l.metrics).length > 0)
      .slice(0, 4)
    const metricSet = [...new Set(all.flatMap((l) => Object.keys(l.metrics)))].slice(0, 5)
    return metricSet.map((metric) => {
      const row: Record<string, string | number> = { metric: metricLabel(metric) }
      for (const loc of all) {
        const stat = loc.metrics[metric]
        row[loc.location] = stat?.avg_value ?? 0
      }
      return row
    })
  }, [locations])

  const hasHistory = series.length > 0
  const hasRadar = radarData.length > 0

  return (
    <div className="space-y-4">
      {/* ---- config row: metrics, window, chart type ---- */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Metrics">
          {(metricNames.length ? metricNames : ['pm25_ugm3']).map((m) => (
            <TogglePill
              key={m}
              label={metricLabel(m)}
              active={selected.includes(m)}
              onSelect={() =>
                setSelected((prev) =>
                  prev.includes(m) ? (prev.length > 1 ? prev.filter((x) => x !== m) : prev) : [...prev, m],
                )
              }
            />
          ))}
        </div>
        <div className="flex items-center gap-1.5" role="group" aria-label="Time range">
          {HISTORY_WINDOWS.map((h) => (
            <TogglePill key={h} label={h >= 24 ? `${h / 24}d` : `${h}h`} active={hours === h} onSelect={() => onHoursChange(h)} />
          ))}
        </div>
        <div className="flex items-center gap-1.5" role="group" aria-label="Chart type">
          {VIZ_OPTIONS.map((v) => (
            <TogglePill key={v.kind} label={v.label} active={viz === v.kind} onSelect={() => setViz(v.kind)} />
          ))}
        </div>
      </div>

      {loading ? (
        <ChartSkeleton className="h-64" />
      ) : !hasHistory ? (
        <div className="rounded-lg border border-dashed border-white/10 p-4">
          <p className="text-sm text-slate-300">No stored observations for this selection.</p>
          <p className="mt-1 text-[11px] text-slate-500">
            Choose another metric/window — gaps are never filled with synthetic values.
          </p>
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            {viz === 'line' ? (
              <LineChart data={series} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                <XAxis dataKey="time" tick={AXIS_STYLE} interval="preserveStartEnd" />
                <YAxis tick={AXIS_STYLE} width={48} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {activeMetrics.map((m, i) => (
                  <Line key={m} type="monotone" dataKey={m} name={metricLabel(m)} stroke={seriesColor(i)}
                    strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
                ))}
              </LineChart>
            ) : viz === 'area' ? (
              <AreaChart data={series} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                <XAxis dataKey="time" tick={AXIS_STYLE} interval="preserveStartEnd" />
                <YAxis tick={AXIS_STYLE} width={48} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {activeMetrics.map((m, i) => (
                  <Area key={m} type="monotone" dataKey={m} name={metricLabel(m)} stroke={seriesColor(i)}
                    fill={seriesColor(i)} fillOpacity={0.15} strokeWidth={1.8} connectNulls={false} isAnimationActive={false} />
                ))}
              </AreaChart>
            ) : (
              <BarChart data={series} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                <XAxis dataKey="time" tick={AXIS_STYLE} interval="preserveStartEnd" />
                <YAxis tick={AXIS_STYLE} width={48} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {activeMetrics.map((m, i) => (
                  <Bar key={m} dataKey={m} name={metricLabel(m)} fill={seriesColor(i)} maxBarSize={26} isAnimationActive={false} />
                ))}
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}

      {/* ---- zone radar (only when location stats exist) ---- */}
      <div>
        <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
          Zone comparison (radar) — averages per location, unranked
        </p>
        {loading ? (
          <ChartSkeleton className="h-56" />
        ) : !hasRadar ? (
          <div className="rounded-lg border border-dashed border-white/10 p-4 text-[11px] text-slate-500">
            Location comparison needs geocoded observations — run ingestion to collect them.
          </div>
        ) : (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} outerRadius="72%">
                <PolarGrid stroke="rgba(148,163,184,0.15)" />
                <PolarAngleAxis dataKey="metric" tick={{ fontSize: 9, fill: '#94a3b8' }} />
                <PolarRadiusAxis tick={false} axisLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
                <Legend wrapperStyle={{ fontSize: 10 }} />
                {locations!.locations.slice(0, 4).map((loc, i) => (
                  <Radar
                    key={loc.location}
                    name={loc.location}
                    dataKey={(row: Record<string, string | number>) => row[loc.location] ?? 0}
                    stroke={seriesColor(i)}
                    fill={seriesColor(i)}
                    fillOpacity={0.18}
                    isAnimationActive={false}
                  />
                ))}
              </RadarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
