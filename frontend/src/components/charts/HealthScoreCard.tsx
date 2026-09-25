import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { HealthScore, HealthTrend } from '../../types'
import { AXIS_STYLE, GRID_STROKE, TOOLTIP_LABEL, TOOLTIP_STYLE } from '../../lib/charts'
import { ChartSkeleton } from '../Skeletons'

interface Props {
  score: HealthScore | undefined
  trend: HealthTrend | undefined
  loading: boolean
}

const CATEGORY_COLOR: Record<string, string> = {
  good: '#34d399', moderate: '#22d3ee', poor: '#f59e0b', critical: '#ef4444',
}

/** City health: score number + penalty contribution bars + daily trend area. */
export default function HealthScoreCard({ score, trend, loading }: Props) {
  const trendData = useMemo(
    () => (trend?.trend ?? []).map((p) => ({ ...p, label: p.day.slice(5) })),
    [trend],
  )
  const avgScore = trendData.length
    ? Math.round(trendData.reduce((s, p) => s + p.score, 0) / trendData.length)
    : null

  if (loading) return <ChartSkeleton className="h-44" />
  if (!score) {
    return (
      <div className="rounded-lg border border-dashed border-white/10 p-4 text-sm text-slate-300">
        Health score unavailable.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500">City health score</p>
          <p className="flex items-baseline gap-2">
            <span
              className="text-3xl font-bold"
              style={{ color: CATEGORY_COLOR[score.category] ?? '#22d3ee' }}
            >
              {score.score}
            </span>
            <span className="text-xs uppercase tracking-wide text-slate-400">{score.category}</span>
          </p>
        </div>
        {avgScore !== null && (
          <p className="text-[11px] text-slate-500">
            {trendData.length}-day avg <span className="font-mono text-slate-300">{avgScore}</span>
          </p>
        )}
      </div>

      {trendData.length >= 2 ? (
        <div className="h-28">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trendData} margin={{ top: 4, right: 6, left: -22, bottom: 0 }}>
              <defs>
                <linearGradient id="healthFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
              <XAxis dataKey="label" tick={AXIS_STYLE} interval="preserveStartEnd" />
              <YAxis domain={[0, 100]} tick={AXIS_STYLE} width={40} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={TOOLTIP_LABEL} />
              <ReferenceLine y={60} stroke="#f59e0b55" strokeDasharray="4 4" />
              <ReferenceLine y={80} stroke="#34d39955" strokeDasharray="4 4" />
              <Area
                type="monotone"
                dataKey="score"
                name="Health score"
                stroke="#22d3ee"
                strokeWidth={2}
                fill="url(#healthFill)"
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-[11px] text-slate-500">
          {trend?.note ?? 'Not enough stored days for a trend line yet.'}
        </p>
      )}

      <div className="space-y-1">
        {score.contributions.map((c) => (
          <div key={c.metric} className="flex items-center gap-2 text-[11px]">
            <span className="w-24 shrink-0 truncate text-slate-300">{c.label}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, (c.penalty / 30) * 100)}%`,
                  backgroundColor: c.penalty > 0 ? '#f59e0b' : '#34d39966',
                }}
              />
            </div>
            <span className="w-40 shrink-0 text-right text-slate-500">
              {c.latest} vs {c.limit} ·{' '}
              <span className={c.penalty > 0 ? 'text-amber-300' : 'text-emerald-300/70'}>
                −{c.penalty}
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="text-[10px] leading-relaxed text-slate-600">{score.note}</p>
    </div>
  )
}
