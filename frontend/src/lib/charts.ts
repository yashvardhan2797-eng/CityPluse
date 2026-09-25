/** Shared Recharts theming so every chart reads as one system. */
export const AXIS_STYLE = { fontSize: 10, fill: '#64748b' } as const
export const GRID_STROKE = 'rgba(148,163,184,0.12)'
export const TOOLTIP_STYLE = {
  background: '#0b1220ee',
  border: '1px solid rgba(148,163,184,0.2)',
  borderRadius: 8,
  fontSize: 11,
} as const
export const TOOLTIP_LABEL = { color: '#94a3b8' } as const

/** Deterministic color for any metric id across all charts. */
export const METRIC_SERIES_COLORS = [
  '#22d3ee', '#a78bfa', '#f59e0b', '#34d399', '#f472b6', '#60a5fa',
] as const
export function seriesColor(index: number): string {
  return METRIC_SERIES_COLORS[index % METRIC_SERIES_COLORS.length]
}

/** Diverging color for correlation cells (-1 .. +1). */
export function correlationColor(r: number): string {
  const a = Math.min(1, Math.abs(r))
  return r >= 0
    ? `rgba(34,211,238,${0.08 + a * 0.72})`   // cyan for positive
    : `rgba(244,114,182,${0.08 + a * 0.72})`  // pink for negative
}

export const CHART_HEIGHTS = { sm: 180, md: 240, lg: 300 } as const
export type ChartHeight = keyof typeof CHART_HEIGHTS
