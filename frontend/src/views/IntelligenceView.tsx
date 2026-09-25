import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Card from '../components/Card'
import { TogglePill } from '../components/TogglePill'
import { TextSkeleton } from '../components/Skeletons'
import { fetchCrossDomain, fetchResilience, fetchResilienceTrend } from '../api'
import type { CrossDomainEdge, CrossDomainEvidence, CrossDomainReport } from '../types'

interface Props {
  cityId: string
  windowHours: number
}

const EDGE_COLORS: Record<string, string> = {
  co_occurrence: '#f59e0b',
  correlation: '#22d3ee',
  co_location: '#a78bfa',
  hypothesis: '#f472b6',
}

/** Radial SVG layout: nodes on a circle, straight colored edges, labels at midpoints. */
function AssociationGraph({ report, onSelectEdge }: {
  report: CrossDomainReport
  onSelectEdge: (edge: CrossDomainEdge) => void
}) {
  const width = 560
  const height = 380
  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(cx, cy) - 55

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    const n = Math.max(report.nodes.length, 1)
    report.nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / n - Math.PI / 2
      map.set(node.id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
      if (report.nodes.length === 1) map.set(node.id, { x: cx, y: cy })
    })
    return map
  }, [report.nodes, cx, cy, radius])

  const maxAnomalies = Math.max(1, ...report.nodes.map((n) => n.anomaly_count))

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Cross-domain association graph"
      className="h-auto w-full"
    >
      {report.edges.map((edge) => {
        const a = positions.get(edge.source)
        const b = positions.get(edge.target)
        if (!a || !b) return null
        const stroke = EDGE_COLORS[edge.kind] ?? '#64748b'
        const dash = edge.kind === 'hypothesis' ? '5 4' : undefined
        const width2 = edge.kind === 'correlation' ? 1 + Math.abs(edge.weight) * 2.2 : 1 + Math.min(edge.weight, 4) * 0.6
        return (
          <g key={edge.id} className="cursor-pointer" onClick={() => onSelectEdge(edge)}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth={12} />
            <line
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={stroke}
              strokeWidth={width2}
              strokeDasharray={dash}
              opacity={0.75}
            />
          </g>
        )
      })}
      {report.nodes.map((node) => {
        const pos = positions.get(node.id)
        if (!pos) return null
        const r = 8 + (node.anomaly_count / maxAnomalies) * 10
        return (
          <g key={node.id}>
            <circle
              cx={pos.x} cy={pos.y} r={r}
              fill="rgba(11,18,32,0.9)"
              stroke="#22d3ee"
              strokeWidth={1.5}
            />
            <text x={pos.x} y={pos.y + 3.5} textAnchor="middle" fontSize={r > 13 ? 9 : 8} fill="#e2e8f0">
              {node.id.replace('_ugm3', '').replace('_mm', '').replace('_kmh', '').replace('_min', '').replace('_pct', '').replace('_count', '')}
            </text>
          </g>
        )
      })}
      <g>
        {Object.entries(EDGE_COLORS).map(([kind, color], i) => (
          <g key={kind} transform={`translate(12, ${14 + i * 14})`}>
            <rect width={9} height={3} y={-1.5} fill={color} rx={1.5} />
            <text x={14} y={2.5} fontSize={9} fill="#94a3b8">
              {kind.replace('_', ' ')}
            </text>
          </g>
        ))}
      </g>
    </svg>
  )
}

/** Evidence panel for one selected edge — the measurements behind the line. */
function EdgeEvidence({ edge, evidence }: { edge: CrossDomainEdge; evidence: Record<string, CrossDomainEvidence> }) {
  const ev = evidence[edge.id]
  if (!ev) return <p className="text-[11px] text-slate-500">No evidence block for this edge.</p>
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider"
          style={{
            color: EDGE_COLORS[edge.kind],
            border: `1px solid ${EDGE_COLORS[edge.kind]}55`,
            background: `${EDGE_COLORS[edge.kind]}11`,
          }}
        >
          {edge.kind.replace('_', ' ')} · {edge.evidence_class.replace('_', ' ')}
        </span>
        <span className="text-[10px] text-slate-400">{edge.label}</span>
      </div>

      {ev.kind === 'correlation' && ev.pearson_r !== undefined && (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">          {[
            { label: 'pearson r', value: ev.pearson_r },
            { label: 'spearman ρ', value: ev.spearman_rho },
            { label: 'n points', value: ev.sample_size },
            { label: 'outliers excluded', value: ev.outliers_excluded },
          ].map((s) => (
            <div key={s.label} className="rounded-lg border border-white/10 bg-navy-800/40 px-2 py-1.5">
              <p className="text-[9px] uppercase tracking-wider text-slate-500">{s.label}</p>
              <p className="text-xs font-semibold text-slate-100">{s.value ?? '—'}</p>
            </div>
          ))}
        </div>
      )}

      {ev.kind === 'co_occurrence' && ev.measurements !== undefined && Array.isArray(ev.measurements) && (
        <div className="space-y-1">
          {(ev.measurements as Array<{ buckets: string[]; gap_hours: number; values: Record<string, number | null> }>).map((m, i) => (
            <p key={i} className="text-[10px] text-slate-300">
              {m.buckets[0]?.slice(5, 16)}Z ↔ {m.buckets[1]?.slice(5, 16)}Z · gap {m.gap_hours}h ·
              {' '}{Object.entries(m.values).map(([k, v]) => `${k}=${v ?? '—'}`).join(', ')}
            </p>
          ))}
        </div>
      )}

      {ev.kind === 'co_location' && (
        <div className="text-[10px] text-slate-300">
          <p>
            {ev.pairs_within_radius ?? 0} site pair(s) within {ev.radius_km} km ·
            {' '}closest {ev.min_nearest_distance_km ?? '—'} km
          </p>
          {ev.note && <p className="mt-1 text-[9px] text-slate-500">{ev.note}</p>}
        </div>
      )}

      {ev.interpretation && (
        <p className="text-[10px] leading-relaxed text-slate-300">{ev.interpretation}</p>
      )}
      {ev.provenance && (
        <p className="text-[10px] text-slate-500"><strong className="text-slate-400">provenance:</strong> {ev.provenance}</p>
      )}      {ev.limitations && (
        <p className="rounded-md border border-amber-400/20 bg-amber-500/5 px-2 py-1 text-[9px] leading-relaxed text-amber-200/90">
          {ev.limitations}
        </p>
      )}
    </div>
  )
}

/** Component bar with formula disclosure. */
function ResilienceComponentBar({ name, comp }: { name: string; comp: { value: number | null; weight: number; status: string; formula: string; note?: string } }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="font-semibold text-slate-200">{name.replace('_', ' ')}</span>
        <span className={comp.value == null ? 'text-slate-500' : 'text-slate-100'}>
          {comp.value == null ? comp.status.replace('_', ' ') : comp.value}
          <span className="ml-1 text-[9px] text-slate-500">w={comp.weight}</span>
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${comp.value ?? 0}%`,
            background: comp.value == null ? 'rgba(148,163,184,0.2)'
              : comp.value >= 75 ? '#34d399' : comp.value >= 55 ? '#f59e0b' : '#f87171',
          }}
        />
      </div>
      <p className="mt-0.5 break-words font-mono text-[9px] text-slate-600">{comp.formula}</p>
      {comp.note && <p className="text-[9px] text-slate-600">{comp.note}</p>}
    </div>
  )
}

/** Urban Intelligence: cross-domain graph + evidence + resilience. */
export default function IntelligenceView({ cityId, windowHours: _windowHours }: Props) {
  const [hours, setHours] = useState(72)
  const [selectedEdge, setSelectedEdge] = useState<CrossDomainEdge | null>(null)
  const [trendDays, setTrendDays] = useState(14)

  const crossDomain = useQuery({
    queryKey: ['cross-domain', cityId, hours],
    queryFn: () => fetchCrossDomain(cityId, hours),
  })
  const resilience = useQuery({
    queryKey: ['resilience', cityId, 168],
    queryFn: () => fetchResilience(cityId, 168),
  })
  const trend = useQuery({
    queryKey: ['resilience-trend', cityId, trendDays],
    queryFn: () => fetchResilienceTrend(cityId, trendDays),
  })

  const report = crossDomain.data
  const activeEdge = selectedEdge && report?.evidence[selectedEdge.id] ? selectedEdge : null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] uppercase tracking-wider text-slate-500">analysis window</span>
        {[12, 24, 72, 168].map((h) => (
          <TogglePill key={h} label={`${h}h`} active={hours === h} onSelect={() => setHours(h)} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          title="Cross-Domain Association Graph"
          subtitle={`${report?.summary.anomalies_considered ?? '—'} anomalies · ${report?.summary.edges ?? '—'} edges · click an edge for evidence`}
          className="xl:col-span-2"
        >
          {crossDomain.isLoading ? (
            <TextSkeleton lines={8} />
          ) : report && report.edges.length > 0 ? (
            <AssociationGraph report={report} onSelectEdge={setSelectedEdge} />
          ) : report ? (
            <div className="p-3">
              <p className="text-[11px] text-slate-400">
                No associations yet: edges form when anomalies of different metrics are flagged within
                {` ${report.co_occurrence_window_hours}h`} of each other, or when correlated pairs exist.
              </p>
              <p className="mt-1 text-[10px] text-slate-500">{report.note}</p>
            </div>
            ) : (
            <p className="p-3 text-[11px] text-rose-300">
              {crossDomain.error?.message ?? 'Cross-domain analysis unavailable.'}
            </p>
          )}
        </Card>

        <Card title="Evidence Panel" subtitle={activeEdge ? activeEdge.label : 'select an edge in the graph'}>
          {activeEdge ? (
            <EdgeEvidence edge={activeEdge} evidence={report?.evidence ?? {}} />
          ) : (
            <p className="text-[11px] text-slate-500">
              Every edge is clickable: the panel shows the measurements, sample sizes, provenance, and
              limitations that support the relationship. Hypothesis edges combine co-occurrence with
              spatial overlap — they are review leads, not established causes.
            </p>
          )}
        </Card>
        </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="Resilience Indicator" subtitle="Explainable components over a 7-day window">
          {resilience.isLoading ? (
            <TextSkeleton lines={6} />
          ) : resilience.data ? (
            <div className="space-y-2.5">
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-bold text-slate-100">
                  {resilience.data.resilience_score ?? '—'}
                </span>
                <span className="text-[10px] text-slate-500">
                  {resilience.data.category ?? 'insufficient data'} · 7d window
                </span>
              </div>
              <div className="space-y-2">
                {Object.entries(resilience.data.components).map(([name, comp]) => (
                  <ResilienceComponentBar key={name} name={name} comp={comp} />
                ))}
              </div>
              <p className="rounded-md border border-amber-400/20 bg-amber-500/5 px-2 py-1 text-[9px] leading-relaxed text-amber-200/90">
                {resilience.data.disclaimer}
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-rose-300">{resilience.error?.message ?? 'unavailable'}</p>
          )}
        </Card>

        <Card title="Resilience Trend" subtitle="Daily health score + anomaly counts (stored days only)">
          <div className="space-y-2">
            <div className="flex gap-1.5">
              {[7, 14, 30].map((d) => (
                <TogglePill key={d} label={`${d}d`} active={trendDays === d} onSelect={() => setTrendDays(d)} />
              ))}
            </div>
            {trend.isLoading ? (
              <TextSkeleton lines={4} />
            ) : trend.data && trend.data.trend.length > 0 ? (
              <table className="w-full text-[10px]">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="font-medium">day</th>
                    <th className="font-medium">score</th>
                    <th className="font-medium">anomalies</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.data.trend.slice(-9).map((row) => (
                    <tr key={row.day} className="border-t border-white/5">
                      <td className="py-0.5 text-slate-300">{row.day}</td>
                      <td className="py-0.5 text-slate-100">{row.score}</td>
                      <td className="py-0.5 text-slate-300">{row.anomalies}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-[11px] text-slate-500">No stored days in this window yet.</p>
            )}
          </div>
        </Card>

        <Card title="Reading the Graph" subtitle="Terminology used across this page">
          <div className="space-y-1.5">
            {report
              ? Object.entries(report.terminology).map(([term, def]) => (
                  <p key={term} className="text-[10px] leading-relaxed text-slate-300">
                    <strong className="text-slate-100">{term.replace('_', ' ')}:</strong> {def}
                  </p>
                ))
              : <TextSkeleton lines={5} />}
            <p className="mt-2 rounded-md border border-rose-400/20 bg-rose-500/5 px-2 py-1 text-[9px] leading-relaxed text-rose-200/90">
              Causation is never claimed on this page. Hypothesis edges are review leads for humans,
              not established causes.
            </p>
          </div>
        </Card>
      </div>
    </div>
  )
}
