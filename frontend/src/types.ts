/** Shared API response types for the CityPulse Flask backend (Phases 1-4). */

export type Severity = 'low' | 'moderate' | 'high' | 'critical'

export const SEVERITIES: Severity[] = ['low', 'moderate', 'high', 'critical']

export type SourceType = 'weather' | 'air_quality' | 'transit' | 'incident'

export const SOURCE_TYPES: SourceType[] = ['weather', 'air_quality', 'transit', 'incident']

export interface CityInfo {
  id: string
  name: string
  country: string
  lat: number
  lon: number
  timezone: string
}

export interface CivicRecord {
  id: number
  source_type: SourceType | string
  source_id: string
  city?: string | null
  location_name: string
  latitude: number
  longitude: number
  value: number | null
  unit: string | null
  description: string | null
  severity: Severity
  recorded_at: string
  created_at: string
  provider?: string | null
  metric?: string | null
  source_url?: string | null
  metadata?: Record<string, unknown> | null
}

export interface HealthInfo {
  status: string
  mode: 'database' | 'demo'
  database_reachable: boolean
  version: string
  last_refresh_seconds_ago?: number | null
  providers?: Array<{
    source_type: string
    provider: string
    mode: 'live' | 'synthetic'
    last_success_at: string | null
    last_error: string | null
  }> | null
}

export interface CitiesResponse {
  mode: string
  database_reachable: boolean
  cities: CityInfo[]
  error: string | null
}

export interface RecordsResponse {
  mode: 'database' | 'demo' | 'demo-fallback'
  city: string | null
  records: CivicRecord[]
  notice?: string
}

export interface MetricLatest {
  value: number | null
  unit: string | null
  recorded_at: string | null
  location: string | null
  synthetic: boolean
}

export interface CitySummary {
  temperature_c?: MetricLatest | null
  humidity_pct?: MetricLatest | null
  precipitation_mm?: MetricLatest | null
  pm25_ugm3?: MetricLatest | null
  transit_load_pct?: MetricLatest | null
  transit_delay_min?: MetricLatest | null
  active_incidents?: number
  data_quality: 'synthetic' | 'mixed' | 'live'
  window_hours?: number
  generated_at: string | null
}

export interface SummaryResponse {
  mode: string
  city: string
  database_reachable: boolean
  summary: CitySummary
  notice: string | null
}

export interface ProviderInfo {
  source_type: string
  provider: string
  configured: boolean
  mode: string
  last_attempt_at: string | null
  last_success_at: string | null
  last_error: string | null
  record_count_last: number
}

export interface SourcesResponse {
  mode: string
  database_reachable: boolean
  sources: ProviderInfo[]
  last_refresh_seconds_ago: number | null
  note: string
}

export interface AnomalyEvent {
  city: string
  source_type: string
  metric: string
  observed_bucket: string
  observed_value: number | null
  baseline_value: number | null
  deviation_score: number | null
  method: string
  window_hours: number | null
  sample_size: number | null
  confidence: string
  limitations: string | null
  created_at: string
}

export interface AnomaliesResponse {
  mode: string
  city: string
  window_hours: number
  detected?: number
  anomalies: AnomalyEvent[]
  insufficient_data?: Array<{ source_type: string; metric: string; reason: string }>
  checked?: Array<{ source_type: string; metric: string; points: number }>
  note?: string
}

export interface CorrelationPair {
  city: string
  metric_a: string
  metric_b: string
  unit_a: string
  unit_b: string
  window_hours: number
  sample_size: number
  outliers_excluded: number
  pearson_r: number
  spearman_rho: number
  interpretation: string
  time_scope: string
  geographic_scope: string
  status: 'ok'
  limitations: string
}

export interface CorrelationsResponse {
  mode: string
  city: string
  window_hours: number
  pairs_analyzed: number
  insufficient_pairs: number
  correlations: CorrelationPair[]
  insufficient_details?: Array<{ metric_a: string; metric_b: string; reason?: string }>
  note: string
  generated_at: string
}

// ---- Phase 3/4: civic companion, alerts, history, locations ----

export interface CompanionResponse {
  mode: string
  city: string
  question: string
  answer: string
  answered_by: string
  grounded_in: AiSummaryResponse['grounded_in']
  generated_at: string
  disclaimer: string
}

export interface AlertInstance {
  dedup_key: string
  city: string
  source_type: string | null
  metric: string | null
  severity: Severity
  title: string
  summary: string
  evidence: {
    kind?: string
    method?: string
    deviation_score?: number | null
    window_hours?: number | null
    sample_size?: number | null
    confidence?: string | null
    threshold?: number | null
    operator?: string
    limitations?: string
    [key: string]: unknown
  }
  observed_value: number | null
  baseline_value: number | null
  location_name: string | null
  detected_at: string
  acknowledged_at: string | null
  acknowledged_by: string | null
  dismissed_at: string | null
  is_synthetic: boolean
}

export interface AlertsResponse {
  mode: string
  city: string
  status: string
  alerts: AlertInstance[]
}

export interface AlertRule {
  id: number
  city: string | null
  metric: string
  operator: '>' | '<' | '>='
  threshold_value: number
  window_hours: number
  enabled: boolean
  label: string | null
}

export interface AlertRulesResponse {
  mode: string
  rules: AlertRule[]
}

export interface HistoryBucket {
  bucket: string
  metric: string
  avg_value: number | null
  n: number
}

export interface HistoryCoverageEntry {
  points: number
  first_bucket: string
  last_bucket: string
  note: string
}

export interface HistoryResponse {
  mode: string
  city: string
  hours: number
  buckets: HistoryBucket[]
  coverage: Record<string, HistoryCoverageEntry>
  note: string
}

export interface LocationMetricStat {
  avg_value: number | null
  observations: number
}

export interface LocationEntry {
  location: string
  metrics: Record<string, LocationMetricStat>
  observations: number
  hours_covered: number
  includes_synthetic: boolean
}

export interface LocationsResponse {
  mode: string
  city: string
  hours: number
  locations: LocationEntry[]
  note: string
}

export interface AiSummaryResponse {
  mode: string
  city: string
  window_hours: number
  summary: string
  generated_by: string
  grounded_in: {
    observations: Array<{
      source_type: string
      metric: string
      value: number | null
      unit: string
      location: string
      recorded_at: string
      synthetic: boolean
    }>
    recent_anomalies: Array<Record<string, unknown>>
    notable_associations: Array<Record<string, unknown>>
    data_quality_notes: string[]
  }
  generated_at: string
  disclaimer: string
}

export interface RefreshResponse {
  skipped: boolean
  reason?: string
  retry_after_seconds?: number
  sources?: Array<{
    source_type: string
    provider: string
    mode: string
    configured: boolean
    records_stored: number
    error: string | null
  }>
  ran_at?: string
}

// ---- Phase 3: civic event lifecycle (merged superset: timeline + demo-mode fields) ----

export type EventStatus = 'open' | 'acknowledged' | 'in_progress' | 'resolved' | 'closed'

export type EventAction = 'acknowledge' | 'start' | 'resolve' | 'close' | 'reopen'

export interface CivicEvent {
  event_ref: string
  city: string
  city_id?: string | null
  source_type: string
  category: string
  title: string
  description: string
  severity: Severity
  status: EventStatus
  latitude: number
  longitude: number
  location_name: string
  reported_at: string
  acknowledged_at?: string | null
  resolved_at?: string | null
  closed_at?: string | null
  acknowledged_by?: string | null
  resolved_by?: string | null
  resolution_note?: string | null
  evidence: Array<Record<string, unknown>>
  tags: string[]
  is_simulated: boolean
  is_active?: boolean
  simulation_run_id?: string | null
  revision: number
  allowed_actions: EventAction[]
  timeline?: EventTimelineEntry[]
  created_at?: string
  updated_at?: string
}

export interface EventTimelineEntry {
  action: string
  from_status: string | null
  to_status: string | null
  actor: string | null
  note: string | null
  at: string
}

export interface EventsResponse {
  mode: string
  persisted?: boolean
  city?: string | null
  status?: string | null
  severity?: string | null
  source_type?: string | null
  include_simulated?: boolean
  events: CivicEvent[]
  pagination: { limit: number; offset: number; returned: number }
  counts?: Record<string, number>
  count?: number
  total?: number | null
  active_count?: number
  stale_hours?: number
  filters?: Record<string, unknown>
  note?: string
}

export interface EventMutationResponse {
  mode?: string
  persisted?: boolean
  event: CivicEvent
  realtime?: { notification_id: number | null }
}

// ---- Phase 3: simulation drills ----

export interface ScenarioInfo {
  id: string
  name: string
  summary: string
  source_type: string
  category: string
  metric: string
  unit: string
  value: number
  severity: Severity
  duration_minutes: number
  recommended_actions: string[]
}

export interface ScenariosResponse {
  enabled: boolean
  scenarios: ScenarioInfo[]
  note?: string
}

export interface SimulationRunRecord {
  run_ref: string
  scenario_id: string
  scenario_name?: string
  city: string
  city_id?: string | null
  status: string
  started_at: string
  finished_at?: string | null
  actor?: string | null
  events_created: number
  observations_written: number
  event_refs?: string[]
  event?: CivicEvent | null
  events?: CivicEvent[]
  open_events?: number
}

// ---- Phase 3: real-time (SSE + polling fallback) ----

export interface RealtimeNotification {
  notification_id: number
  type: string
  published_at: string
  event_ref?: string
  status?: string
  event?: CivicEvent
  [key: string]: unknown
}

export interface EventsPollResponse {
  mode?: string
  notifications: RealtimeNotification[]
  last_notification_id: number
  count?: number
}

export interface SeverityResponse {
  mode: string
  city: string | null
  breakdown: Record<Severity, number>
  notice?: string
}

export interface SettingsInfo {
  mode: string
  database_reachable: boolean
  supabase_configured: boolean
  providers: Record<string, { provider: string; configured: boolean; needs_key: boolean }>
  ai_configured: boolean
  simulation_enabled?: boolean
  realtime_enabled?: boolean
  phase: number
}

export interface DataResponse {
  mode: string
  records: CivicRecord[]
  pagination: { limit: number; offset: number; returned?: number; total_estimate?: number | null }
  notice?: string
}

// ---- Graph dashboard additions ----

export interface HealthScore {
  city: string
  score: number
  category: 'good' | 'moderate' | 'poor' | 'critical'
  contributions: Array<{
    metric: string
    label: string
    latest: number
    points_averaged: number
    penalty: number
    limit: number
    status: string
  }>
  coverage: Record<string, { points: number; note: string }>
  window_hours: number
  generated_at: string
  note: string
}

export interface HealthTrend {
  city: string
  days: number
  trend: Array<{ day: string; score: number; n_points: number }>
  note: string
  generated_at: string
}

export interface SeveritySeriesResponse {
  mode: string
  city: string
  hours: number
  bucket: string
  series: Array<{ bucket: string; severity: Severity; count: number }>
  error?: string
}

// =====================================================================
// Phase 9 — urban intelligence
// =====================================================================

export type EvidenceClass = 'statistical_association' | 'hypothesis'

export interface ImpactEstimate {
  indicator: string
  unit?: string
  baseline: number
  scenario?: number
  simulated?: number
  formula: string
}

export interface ImpactIntervention {
  id: string
  title: string
  rationale: string
  evidence: string
  limits: string
  advisory: boolean
  triggered_by_metric?: string
}

export interface ImpactBrief {
  city: string
  status: 'ok' | 'no_anomaly' | 'unavailable'
  advisory?: string
  anomaly?: {
    metric: string
    source_type?: string | null
    observed_bucket: string | null
    observed_value: number | null
    baseline_value: number | null
    deviation_score: number | null
    confidence: string | null
    method?: string | null
    limitations?: string | null
  }
  impact_path?: string | null
  related_anomalies?: {
    time_window: { anchor_hour: string; related: Array<{ metric: string; observed_value: number | null; deviation_score: number | null }>; note: string }
    geo_proximity: { radius_km: number; center: { latitude: number; longitude: number } | null; zones: Array<{ location: string; distance_km: number; avg_value: number; synthetic: boolean }>; note: string }
    window_hours: number
  }
  inputs?: Record<string, { latest: number | null; n_points: number; source_type: string }>
  impact_estimates?: {
    baseline: ImpactEstimate[]
    simulated: ImpactEstimate[]
    comparison: Array<ImpactEstimate & { change: number; unit_hint?: string }>
    intervention: string | null
    coefficients: Record<string, { value: number; note: string }>
  }
  interventions?: ImpactIntervention[]
  assumptions?: string[]
  limitations?: string[]
  provenance?: { data: string; mode: string; simulated_parts: string; generated_at: string }
  note?: string
}

export interface CrossDomainEdge {
  id: string
  source: string
  target: string
  kind: 'co_occurrence' | 'correlation' | 'co_location' | 'hypothesis'
  evidence_class: EvidenceClass
  weight: number
  label: string
}

export interface CrossDomainNode {
  id: string
  label: string
  domain: string
  unit: string
  anomaly_count: number
  last_anomaly_bucket: string | null
  max_deviation_score: number
}

export interface CrossDomainEvidence {
  kind: string
  status?: string
  reason?: string
  pearson_r?: number
  spearman_rho?: number
  sample_size?: number
  outliers_excluded?: number
  window_hours?: number
  interpretation?: string
  provenance?: string
  limitations?: string
  measurements?: unknown
  sample_measurements?: Record<string, { n_rows: number; example: unknown }>
  requires?: string[]
  pairs_within_radius?: number
  min_nearest_distance_km?: number
  radius_km?: number
  note?: string
}

export interface CrossDomainReport {
  city: string
  window_hours: number
  co_occurrence_window_hours: number
  geo_radius_km: number
  nodes: CrossDomainNode[]
  edges: CrossDomainEdge[]
  evidence: Record<string, CrossDomainEvidence>
  summary: { anomalies_considered: number; co_occurring_pairs: number; edges: number; hypotheses: number }
  terminology: Record<string, string>
  generated_at: string
  note: string
}

export interface ResilienceComponent {
  value: number | null
  weight: number
  status: string
  inputs?: Record<string, unknown>
  formula: string
  note?: string
}

export interface ResilienceReport {
  city: string
  window_hours: number
  resilience_score: number | null
  category: string | null
  components: Record<string, ResilienceComponent>
  weights_used: Record<string, number>
  weight_renormalization: string
  disclaimer: string
  generated_at: string
  note: string
}

export interface ResilienceTrend {
  city: string
  days: number
  trend: Array<{ day: string; score: number; n_points: number; anomalies: number }>
  note: string
  disclaimer: string
  generated_at: string
}

export interface TwinZoneMetric {
  recent_avg: number | null
  previous_avg: number | null
  delta_pct: number | null
  recent_observations: number
  previous_observations: number
  last_recorded_at: string | null
  note: string | null
}

export interface TwinZone {
  id: string
  location: string
  latitude: number
  longitude: number
  metrics: Record<string, TwinZoneMetric>
  coverage: { recent_window_hours: number; recent_metric_points: number }
  anomalies_nearby: Array<{ metric: string; observed_bucket: string | null; observed_value: number | null; deviation_score: number | null; distance_km: number }>
  events_nearby: Array<{ event_ref: string; title: string; severity: Severity; status: string; is_simulated: boolean; distance_km: number }>
  advisories: ImpactIntervention[]
}

export interface TwinReport {
  city: string
  status: 'ok' | 'unavailable'
  window_hours: number
  zone_count: number
  zones: TwinZone[]
  layers: {
    anomalies: Array<{ metric: string; observed_bucket: string | null; observed_value: number | null; deviation_score: number | null; confidence: string | null; nearest_zone?: string; zone_distance_km?: number }>
    events: Array<{ event_ref: string; title: string; severity: Severity; status: string; category: string | null; latitude: number; longitude: number; location_name: string | null; is_simulated: boolean; reported_at: string | null }>
    note: string
  }
  advisory: string
  data_policy: string
  error?: string
  generated_at: string
}

export interface ScenarioParamSpec {
  min: number
  max: number
  default: number
  unit: string
  description: string
}

export interface ScenarioModelInfo {
  model_id: string
  name: string
  description: string
  params: Record<string, ScenarioParamSpec>
  required_baseline_metrics: string[]
}

export interface ScenarioModelsResponse {
  models: ScenarioModelInfo[]
  note: string
}

export interface ScenarioRunResult {
  city: string
  model_id: string
  model_name: string
  params_used: Record<string, number | boolean>
  param_ranges: Record<string, { min: number; max: number }>
  baseline_inputs: Record<string, { value: number | null; bucket: string | null; n_points: number; source: string }>
  rows: ImpactEstimate[]
  tradeoffs: string[]
  assumptions: string[]
  coefficients_reused: Record<string, { value: number; note: string }>
  simulation_label: string
  advisory: string
  provenance: Record<string, unknown>
  note: string
}

export interface CopilotToolOutput {
  tool: string
  error?: string
  [key: string]: unknown
}

export interface CopilotResponse {
  city: string
  mode: 'copilot_tools' | 'copilot_fallback'
  answer: string
  tools_used: string[]
  tool_outputs?: CopilotToolOutput[]
  tool_specs?: Array<{ name: string; description: string; params: Record<string, string> }>
  grounding?: unknown
  disclaimer: string
  generated_at?: string
}
