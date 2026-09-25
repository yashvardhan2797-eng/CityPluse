/** Typed REST client for the CityPulse Flask backend.
 *
 * All calls go to same-origin /api/*; the Vite dev server proxies them to
 * Flask. The browser never sees database credentials or secret keys.
 */
import type {
  AiSummaryResponse,
  AlertRulesResponse,
  AlertsResponse,
  AnomaliesResponse,
  CitiesResponse,
  CompanionResponse,
  CorrelationsResponse,
  DataResponse,
  EventAction,
  EventMutationResponse,
  EventsPollResponse,
  EventsResponse,
  HealthInfo,
  HealthScore,
  HealthTrend,
  HistoryResponse,
  LocationsResponse,
  RecordsResponse,
  RefreshResponse,
  ScenariosResponse,
  SeverityResponse,
  SeveritySeriesResponse,
  SettingsInfo,
  SimulationRunRecord,
  SourcesResponse,
  SummaryResponse,
} from './types'

const API_BASE = '/api'
const REQUEST_TIMEOUT_MS = 15_000

async function getJson<T>(path: string): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, { signal: controller.signal })
    if (!response.ok) {
      throw new Error(`API ${response.status} on ${path}`)
    }
    return (await response.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

async function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    const parsed = (await response.json()) as T
    if (!response.ok) {
      const message =
        typeof parsed === 'object' && parsed !== null && 'error' in parsed
          ? String((parsed as { error: unknown }).error)
          : `API ${response.status} on ${path}`
      throw new Error(message)
    }
    return parsed
  } finally {
    clearTimeout(timer)
  }
}

export const fetchHealth = () => getJson<HealthInfo>('/health')
export const fetchSettings = () => getJson<SettingsInfo>('/settings')
export const fetchCities = () => getJson<CitiesResponse>('/cities')
export const fetchRecords = (cityId: string) =>
  getJson<RecordsResponse>(`/records?city=${encodeURIComponent(cityId)}`)
export const fetchSummary = (cityId: string, hours = 24) =>
  getJson<SummaryResponse>(`/summary?city=${encodeURIComponent(cityId)}&hours=${hours}`)
export const fetchSeverityBreakdown = (cityId: string) =>
  getJson<SeverityResponse>(`/chart/severity?city=${encodeURIComponent(cityId)}`)

// ---- Phase 2 ----
export const fetchSources = () => getJson<SourcesResponse>('/sources')
export const fetchData = (cityId: string, options: { sourceType?: string; hours?: number; limit?: number } = {}) => {
  const params = new URLSearchParams({ city: cityId })
  if (options.sourceType) params.set('source_type', options.sourceType)
  if (options.hours) params.set('hours', String(options.hours))
  if (options.limit) params.set('limit', String(options.limit))
  return getJson<DataResponse>(`/data?${params.toString()}`)
}
export async function triggerRefresh(cityId?: string): Promise<RefreshResponse> {
  const response = await fetch('/api/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cityId ? { city: cityId } : {}),
  })
  const body = (await response.json()) as RefreshResponse
  if (!response.ok && !body.reason) {
    throw new Error(`refresh failed: ${response.status}`)
  }
  return body
}

// ---- Phase 3 ----
export const fetchAnomalies = (cityId: string, windowHours = 72, detect = false) =>
  getJson<AnomaliesResponse>(
    `/analytics/anomalies?city=${encodeURIComponent(cityId)}&window_hours=${windowHours}${detect ? '&detect=1' : ''}`,
  )
export const fetchCorrelations = (cityId: string, windowHours = 72) =>
  getJson<CorrelationsResponse>(
    `/analytics/correlations?city=${encodeURIComponent(cityId)}&window_hours=${windowHours}`,
  )
export const fetchAiSummary = (cityId: string, windowHours = 72) =>
  getJson<AiSummaryResponse>(
    `/ai/summary?city=${encodeURIComponent(cityId)}&window_hours=${windowHours}`,
  )

// ---- Phase 3/4: companion, alerts, history, locations ----
export async function askCompanion(cityId: string, question: string, windowHours = 72): Promise<CompanionResponse> {
  const response = await fetch('/api/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ city: cityId, question, window_hours: windowHours }),
  })
  const body = (await response.json()) as CompanionResponse & { error?: string }
  if (!response.ok) throw new Error(body.error ?? `companion failed: ${response.status}`)
  return body
}

export const fetchAlerts = (cityId: string, status = 'active', limit = 50) =>
  getJson<AlertsResponse>(
    `/alerts?city=${encodeURIComponent(cityId)}&status=${status}&limit=${limit}`,
  )

export const fetchAlertRules = () => getJson<AlertRulesResponse>('/alerts/rules')

export const acknowledgeAlert = (cityId: string, dedupKey: string) =>
  postJson<{ mode: string; alert: unknown }>(
    `/alerts/${encodeURIComponent(dedupKey)}/acknowledge?city=${encodeURIComponent(cityId)}`,
    {},
  )

export const dismissAlert = (cityId: string, dedupKey: string) =>
  postJson<{ mode: string; alert: unknown }>(
    `/alerts/${encodeURIComponent(dedupKey)}/dismiss?city=${encodeURIComponent(cityId)}`,
    {},
  )

export const fetchHistory = (cityId: string, hours: number, metrics?: string[]) => {
  const params = new URLSearchParams({ city: cityId, hours: String(hours) })
  if (metrics?.length) params.set('metrics', metrics.join(','))
  return getJson<HistoryResponse>(`/history?${params.toString()}`)
}

export const fetchLocations = (cityId: string, hours: number, metrics?: string[]) => {
  const params = new URLSearchParams({ city: cityId, hours: String(hours) })
  if (metrics?.length) params.set('metrics', metrics.join(','))
  return getJson<LocationsResponse>(`/analytics/locations?${params.toString()}`)
}

// ---- Phase 3: civic events ----

export const fetchEvents = (
  cityId: string,
  options: {
    status?: string
    severity?: string
    sourceType?: string
    includeSimulated?: boolean
    limit?: number
    offset?: number
  } = {},
) => {
  const params = new URLSearchParams({ city: cityId })
  if (options.status) params.set('status', options.status)
  if (options.severity) params.set('severity', options.severity)
  if (options.sourceType) params.set('source_type', options.sourceType)
  if (options.includeSimulated === false) params.set('include_simulated', 'false')
  if (options.limit) params.set('limit', String(options.limit))
  if (options.offset) params.set('offset', String(options.offset))
  return getJson<EventsResponse>(`/events?${params.toString()}`)
}

async function mutateEvent(path: string, body: Record<string, unknown> = {}): Promise<EventMutationResponse> {
  const response = await postJson<EventMutationResponse>(path, body)
  return response
}

export const acknowledgeEvent = (eventRef: string, actor = 'operator') =>
  mutateEvent(`/events/${encodeURIComponent(eventRef)}/acknowledge`, { actor })
export const resolveEvent = (eventRef: string, actor = 'operator', note?: string) =>
  mutateEvent(`/events/${encodeURIComponent(eventRef)}/resolve`, note ? { actor, note } : { actor })
export const closeEvent = (eventRef: string, actor = 'operator') =>
  mutateEvent(`/events/${encodeURIComponent(eventRef)}/close`, { actor })
export const transitionEvent = (eventRef: string, action: EventAction, actor = 'operator', note?: string) =>
  mutateEvent(`/events/${encodeURIComponent(eventRef)}/transition`, { action, actor, ...(note ? { note } : {}) })

export async function pollEventNotifications(since = 0): Promise<EventsPollResponse> {
  return getJson<EventsPollResponse>(`/events/poll?since=${since}`)
}

// ---- Phase 3: simulation drills ----

export const fetchScenarios = () => getJson<ScenariosResponse>('/simulation/scenarios')

export const fetchSimulationRuns = (limit = 20) =>
  getJson<SimulationRunRecord[]>(`/simulation/runs?limit=${limit}`)

export async function startSimulation(scenarioId: string, cityId: string): Promise<SimulationRunRecord> {
  const response = await fetch('/api/simulation/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId, city: cityId, actor: 'operator' }),
  })
  const body = (await response.json()) as SimulationRunRecord & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `simulation failed: ${response.status}`)
  }
  return body
}

export async function advanceSimulation(runRef: string, action = 'acknowledge'): Promise<SimulationRunRecord> {
  const response = await fetch(`/api/simulation/runs/${encodeURIComponent(runRef)}/advance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, actor: 'operator' }),
  })
  const body = (await response.json()) as SimulationRunRecord & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `advance failed: ${response.status}`)
  }
  return body
}

export async function resetSimulation(runRef: string): Promise<SimulationRunRecord> {
  const response = await fetch(`/api/simulation/runs/${encodeURIComponent(runRef)}/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ actor: 'operator' }),
  })
  const body = (await response.json()) as SimulationRunRecord & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `reset failed: ${response.status}`)
  }
  return body
}

// ---- Graph dashboard: health score, trend, severity time series ----

export const fetchHealthScore = (cityId: string, hours = 24) =>
  getJson<HealthScore>(`/analytics/health?city=${encodeURIComponent(cityId)}&hours=${hours}`)

export const fetchHealthTrend = (cityId: string, days = 7) =>
  getJson<HealthTrend>(`/analytics/health/trend?city=${encodeURIComponent(cityId)}&days=${days}`)

export const fetchSeveritySeries = (cityId: string, hours = 72, bucket: 'hour' | 'day' = 'hour') =>
  getJson<SeveritySeriesResponse>(
    `/analytics/severity-series?city=${encodeURIComponent(cityId)}&hours=${hours}&bucket=${bucket}`,
  )


// ---- Phase 9: impact engine, cross-domain, resilience, twin, scenario lab, copilot ----

export const fetchImpactBrief = (cityId: string, metric?: string, windowHours = 72) =>
  getJson<ImpactBrief>(
    `/analytics/impact?city=${encodeURIComponent(cityId)}&window_hours=${windowHours}` +
    (metric ? `&metric=${encodeURIComponent(metric)}` : ''),
  )

export const fetchCrossDomain = (cityId: string, windowHours = 72) =>
  getJson<CrossDomainReport>(
    `/analytics/cross-domain?city=${encodeURIComponent(cityId)}&window_hours=${windowHours}`,
  )

export const fetchResilience = (cityId: string, hours = 168) =>
  getJson<ResilienceReport>(`/analytics/resilience?city=${encodeURIComponent(cityId)}&hours=${hours}`)

export const fetchResilienceTrend = (cityId: string, days = 14) =>
  getJson<ResilienceTrend>(`/analytics/resilience/trend?city=${encodeURIComponent(cityId)}&days=${days}`)

export const fetchTwin = (cityId: string, hours = 24) =>
  getJson<TwinReport>(`/twin?city=${encodeURIComponent(cityId)}&hours=${hours}`)

export const fetchScenarioModels = () => getJson<ScenarioModelsResponse>('/scenario-lab/models')

export async function runScenario(
  cityId: string,
  modelId: string,
  params: Record<string, number | boolean>,
): Promise<ScenarioRunResult> {
  const response = await fetch('/api/scenario-lab/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ city: cityId, model: modelId, params }),
  })
  const body = (await response.json()) as ScenarioRunResult & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `scenario run failed: ${response.status}`)
  }
  return body
}

export async function askCopilot(cityId: string, question: string, windowHours = 72): Promise<CopilotResponse> {
  const response = await fetch('/api/copilot/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ city: cityId, question, window_hours: windowHours }),
  })
  const body = (await response.json()) as CopilotResponse & { error?: string }
  if (!response.ok) {
    throw new Error(body.error ?? `copilot failed: ${response.status}`)
  }
  return body
}
