/** Visual tokens shared across CityPulse components. */
import type { CivicRecord, Severity } from '../types'

export const SEVERITY_COLORS: Record<Severity, string> = {
  low: '#22c55e',
  moderate: '#eab308',
  high: '#f97316',
  critical: '#ef4444',
}

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  critical: 'Critical',
}

export const SOURCE_META: Record<string, { label: string; icon: string }> = {
  weather: { label: 'Weather', icon: '🌦️' },
  air_quality: { label: 'Air Quality', icon: '🌫️' },
  transit: { label: 'Transit', icon: '🚇' },
  incident: { label: 'Incident', icon: '⚠️' },
}

/** Consistent chart colors for per-metric time series (Phase 4 history). */
export const METRIC_COLORS: string[] = [
  '#22d3ee', // cyan
  '#a78bfa', // violet
  '#f59e0b', // amber
  '#34d399', // emerald
  '#f472b6', // pink
  '#60a5fa', // blue
]

export const METRIC_LABELS: Record<string, string> = {
  temperature_c: 'Temperature',
  humidity_pct: 'Humidity',
  precipitation_mm: 'Precipitation',
  wind_speed_kmh: 'Wind speed',
  pm25_ugm3: 'PM2.5',
  pm10_ugm3: 'PM10',
  o3_ugm3: 'Ozone',
  no2_ugm3: 'NO₂',
  load_factor_pct: 'Transit load',
  delay_min: 'Transit delay',
  active_vehicles: 'Active vehicles',
  avg_speed_kmh: 'Avg speed',
  incident_count: 'Incidents',
}

/** True when a record is provenance-stamped as synthetic demo data. */
export function isSyntheticRecord(record: CivicRecord): boolean {
  const meta = record.metadata as Record<string, unknown> | null | undefined
  return meta?.is_synthetic === true
}

export function severityColor(severity: string): string {
  return SEVERITY_COLORS[severity as Severity] ?? '#64748b'
}

export function sourceLabel(sourceType: string): string {
  return SOURCE_META[sourceType]?.label ?? sourceType
}

export function metricLabel(metric: string | null | undefined): string {
  if (!metric) return 'Metric'
  return METRIC_LABELS[metric] ?? metric
}
