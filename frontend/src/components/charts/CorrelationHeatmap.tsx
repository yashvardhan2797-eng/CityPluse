import { useMemo } from 'react'
import type { CorrelationsResponse } from '../../types'
import { correlationColor, seriesColor } from '../../lib/charts'
import { metricLabel } from '../../lib/theme'
import { ChartSkeleton } from '../Skeletons'

interface Props {
  report: CorrelationsResponse | undefined
  loading: boolean
  /** Optional pair selection drives the detail readout below the grid. */
  selectedPair: { a: string; b: string } | null
  onSelectPair: (pair: { a: string; b: string } | null) => void
}

type Cell = { a: string; b: string; r: number; rho: number; n: number; interpretation: string }

/** Metric × metric grid; cyan = positive, pink = negative, click to inspect. */
export default function CorrelationHeatmap({ report, loading, selectedPair, onSelectPair }: Props) {
  const { metrics, cells, byPair } = useMemo(() => {
    const list: Cell[] = (report?.correlations ?? []).map((c) => ({
      a: c.metric_a,
      b: c.metric_b,
      r: c.pearson_r,
      rho: c.spearman_rho,
      n: c.sample_size,
      interpretation: c.interpretation,
    }))
    const names = [...new Set(list.flatMap((c) => [c.a, c.b]))].sort()
    const map = new Map<string, Cell>()
    for (const c of list) map.set(c.a < c.b ? `${c.a}|${c.b}` : `${c.b}|${c.a}`, c)
    return { metrics: names, cells: list, byPair: map }
  }, [report])

  const selected: Cell | null = useMemo(() => {
    if (!selectedPair) return null
    const { a, b } = selectedPair
    return byPair.get(a < b ? `${a}|${b}` : `${b}|${a}`) ?? null
  }, [selectedPair, byPair])

  if (loading) return <ChartSkeleton className="h-64" />

  if (cells.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-white/10 p-4">
        <p className="text-sm text-slate-300">No correlation pairs have enough aligned data yet.</p>
        <p className="mt-1 text-[11px] text-slate-500">
          Pairs need 12+ aligned hourly points per metric. Run ingestion to accumulate history.
        </p>
      </div>
    )
  }

  const cellPx = metrics.length > 5 ? 34 : 44

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="border-separate" style={{ borderSpacing: 3 }} role="grid" aria-label="Correlation heatmap">
          <thead>
            <tr>
              <th aria-hidden />
              {metrics.map((m) => (
                <th
                  key={m}
                  scope="col"
                  className="pb-1 text-[9px] font-medium text-slate-400"
                  style={{ writingMode: 'vertical-rl', rotate: '180deg', height: 64, maxWidth: 18 }}
                >
                  {metricLabel(m)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((rowMetric, ri) => (
              <tr key={rowMetric}>
                <th scope="row" className="pr-2 text-right text-[10px] font-medium text-slate-300 whitespace-nowrap">
                  {metricLabel(rowMetric)}
                </th>
                {metrics.map((colMetric, ci) => {
                  if (ci === ri) {
                    return <td key={colMetric} className="text-center text-[9px] text-slate-600">1.0</td>
                  }
                  if (ci < ri) {
                    return <td key={colMetric} aria-hidden className="bg-white/[0.015]" />
                  }
                  const cell = byPair.get(
                    rowMetric < colMetric ? `${rowMetric}|${colMetric}` : `${colMetric}|${rowMetric}`,
                  )
                  if (!cell) return <td key={colMetric} className="text-center text-[10px] text-slate-700">·</td>
                  const strong = Math.abs(cell.r) >= 0.4
                  return (
                    <td key={colMetric} className="p-0">
                      <button
                        type="button"
                        onClick={() => onSelectPair(selectedPair?.a === rowMetric && selectedPair?.b === colMetric ? null : { a: rowMetric, b: colMetric })}
                        aria-pressed={!!selectedPair && selectedPair.a === rowMetric && selectedPair.b === colMetric}
                        title={`${metricLabel(rowMetric)} × ${metricLabel(colMetric)} — r=${cell.r}, ρ=${cell.rho}, n=${cell.n}`}
                        className="flex h-full w-full items-center justify-center font-mono text-[10px] font-semibold transition-transform hover:scale-[1.06]"
                        style={{
                          minWidth: cellPx, minHeight: cellPx, padding: '2px 3px', borderRadius: 6,
                          background: correlationColor(cell.r),
                          color: strong ? '#04121b' : '#cbd5e1',
                        }}
                      >
                        {cell.r.toFixed(2)}
                      </button>
                      {/* rho visible in tooltip/title and detail panel */}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-2 text-[10px] text-slate-500">
        <span>−1</span>
        <div className="h-1.5 w-40 rounded-full" style={{ background: 'linear-gradient(90deg, rgba(244,114,182,0.8), rgba(148,163,184,0.15), rgba(34,211,238,0.8))' }} />
        <span>+1</span>
        <span className="ml-2">cyan = move together · pink = opposite · click a cell</span>
        <span className="ml-auto" style={{ color: seriesColor(0) }}>●</span>
      </div>

      {selected && (
        <div className="rounded-lg border border-white/10 bg-navy-800/50 p-3 text-[11px]">
          <p className="font-semibold text-slate-200">
            {metricLabel(selected.a)} × {metricLabel(selected.b)}
          </p>
          <p className="mt-1 text-slate-400">
            Pearson r=<span className="font-mono text-slate-100">{selected.r.toFixed(3)}</span> · Spearman ρ=
            <span className="font-mono text-slate-100">{selected.rho.toFixed(3)}</span> · n={selected.n} · {selected.interpretation}
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-600">
            Association only — not evidence of causation. Short windows and city-wide averages
            can over- or under-state real relationships.
          </p>
        </div>
      )}
    </div>
  )
}
