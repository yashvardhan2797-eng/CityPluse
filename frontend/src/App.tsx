import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  acknowledgeAlert,
  askCopilot,
  dismissAlert,
  fetchAiSummary,
  fetchAlerts,
  fetchAnomalies,
  fetchCities,
  fetchCorrelations,
  fetchData,
  fetchHealth,
  fetchHistory,
  fetchLocations,
  fetchRecords,
  fetchSeverityBreakdown,
  fetchSettings,
  fetchSources,
  fetchSummary,
  triggerRefresh,
} from './api'
import type { CivicRecord, CopilotResponse, SourceType } from './types'
import Header from './components/Header'
import AnalyticsView from './views/AnalyticsView'
import TwinView from './views/TwinView'
import IntelligenceView from './views/IntelligenceView'
import { TogglePill } from './components/TogglePill'
import CityMap from './components/CityMap'
import SeverityChart from './components/SeverityChart'
import RecordsFeed from './components/RecordsFeed'
import DataSourcePanel from './components/DataSourcePanel'
import SourceHealth from './components/SourceHealth'
import DataLayersBar from './components/DataLayersBar'
import AnomaliesPanel from './components/AnomaliesPanel'
import CorrelationsPanel from './components/CorrelationsPanel'
import AiSummaryPanel from './components/AiSummaryPanel'
import AlertCenter from './components/AlertCenter'
import HistoryChart from './components/HistoryChart'
import LocationsPanel from './components/LocationsPanel'
import CopilotPanel from './components/CopilotPanel'
import KpiCard from './components/KpiCard'
import Card from './components/Card'
import { formatClock } from './lib/ui'

/** CityPulse dashboard shell (Phases 1-4). */
export default function App() {
  const [selectedCityId, setSelectedCityId] = useState('bengaluru')
  const [selectedRecord, setSelectedRecord] = useState<CivicRecord | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceType | 'all'>('all')
  const [windowHours, setWindowHours] = useState(24)
  const [historyHours, setHistoryHours] = useState(72)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<'overview' | 'analytics' | 'twin' | 'intelligence'>('overview')
  const [copilotAnswer, setCopilotAnswer] = useState<CopilotResponse | null>(null)
  const queryClient = useQueryClient()

  // ---- core data (all through the Flask backend) ----
  const healthQuery = useQuery({ queryKey: ['health'], queryFn: fetchHealth, refetchInterval: 60_000 })
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: fetchSettings })
  const citiesQuery = useQuery({ queryKey: ['cities'], queryFn: fetchCities })
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: fetchSources })

  const recordsQuery = useQuery({
    queryKey: ['records', selectedCityId],
    queryFn: () => fetchRecords(selectedCityId),
  })
  const dataQuery = useQuery({
    queryKey: ['data', selectedCityId, sourceFilter, windowHours],
    queryFn: () =>
      fetchData(selectedCityId, {
        sourceType: sourceFilter === 'all' ? undefined : sourceFilter,
        hours: windowHours,
        limit: 400,
      }).catch(() => ({
        mode: 'demo' as const,
        records: [] as CivicRecord[],
        pagination: { limit: 400, offset: 0 },
      })),
  })
  const summaryQuery = useQuery({
    queryKey: ['summary', selectedCityId, windowHours],
    queryFn: () => fetchSummary(selectedCityId, windowHours),
  })
  const severityQuery = useQuery({
    queryKey: ['severity', selectedCityId],
    queryFn: () => fetchSeverityBreakdown(selectedCityId),
  })

  // ---- Phase 3 ----
  const anomaliesQuery = useQuery({
    queryKey: ['anomalies', selectedCityId, windowHours],
    queryFn: () => fetchAnomalies(selectedCityId, windowHours),
  })
  const correlationsQuery = useQuery({
    queryKey: ['correlations', selectedCityId, windowHours],
    queryFn: () => fetchCorrelations(selectedCityId, windowHours),
  })
  const aiSummaryQuery = useQuery({
    queryKey: ['ai-summary', selectedCityId, windowHours],
    queryFn: () => fetchAiSummary(selectedCityId, windowHours),
  })
  const detectMutation = useMutation({
    mutationFn: () => fetchAnomalies(selectedCityId, windowHours, true),
    onSuccess: (report) => {
      queryClient.setQueryData(['anomalies', selectedCityId, windowHours], report)
    },
  })

  const refreshMutation = useMutation({
    mutationFn: () => triggerRefresh(selectedCityId),
    onSuccess: () => {
      void queryClient.invalidateQueries()
    },
  })

  // ---- Phase 4: alerts, history replay, location comparison, companion ----
  const alertsQuery = useQuery({
    queryKey: ['alerts', selectedCityId],
    queryFn: () => fetchAlerts(selectedCityId),
  })
  const historyQuery = useQuery({
    queryKey: ['history', selectedCityId, historyHours],
    queryFn: () => fetchHistory(selectedCityId, historyHours),
  })
  const locationsQuery = useQuery({
    queryKey: ['locations', selectedCityId, windowHours],
    queryFn: () => fetchLocations(selectedCityId, windowHours),
  })

  const copilotMutation = useMutation({
    mutationFn: (question: string) => askCopilot(selectedCityId, question, windowHours),
    onSuccess: setCopilotAnswer,
  })

  function invalidateAlerts() {
    void queryClient.invalidateQueries({ queryKey: ['alerts', selectedCityId] })
  }
  const acknowledgeMutation = useMutation({
    mutationFn: (dedupKey: string) => acknowledgeAlert(selectedCityId, dedupKey),
    onMutate: (dedupKey) => setBusyKey(dedupKey),
    onSettled: () => setBusyKey(null),
    onSuccess: invalidateAlerts,
  })
  const dismissMutation = useMutation({
    mutationFn: (dedupKey: string) => dismissAlert(selectedCityId, dedupKey),
    onMutate: (dedupKey) => setBusyKey(dedupKey),
    onSettled: () => setBusyKey(null),
    onSuccess: invalidateAlerts,
  })

  // Periodic revalidation of live-ish data while auto-refresh is on.
  useEffect(() => {
    if (!autoRefresh) return
    const id = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ['records', selectedCityId] })
      void queryClient.invalidateQueries({ queryKey: ['summary', selectedCityId, windowHours] })
      void queryClient.invalidateQueries({ queryKey: ['sources'] })
      void queryClient.invalidateQueries({ queryKey: ['alerts', selectedCityId] })
      void queryClient.invalidateQueries({ queryKey: ['locations', selectedCityId, windowHours] })
    }, 60_000)
    return () => window.clearInterval(id)
  }, [autoRefresh, queryClient, selectedCityId, windowHours])

  const cities = citiesQuery.data?.cities ?? []
  const city = useMemo(
    () => cities.find((c) => c.id === selectedCityId),
    [cities, selectedCityId],
  )
  const allRecords = recordsQuery.data?.records ?? []
  const dataRecords = dataQuery.data?.records ?? []
  const visibleRecords = dataRecords.length > 0 ? dataRecords : allRecords
  const dataMode = recordsQuery.data?.mode ?? 'demo'

  function handleCityChange(cityId: string) {
    setSelectedCityId(cityId)
    setSelectedRecord(null)
    setCopilotAnswer(null) // answers are city-scoped; never show a stale city's answer
  }

  const summary = summaryQuery.data?.summary
  const summaryLoading = summaryQuery.isLoading
  const anyFetching = recordsQuery.isFetching || dataQuery.isFetching || healthQuery.isFetching

  const qualityLabel =
    summary?.data_quality === 'live' ? 'live observations' :
    summary?.data_quality === 'mixed' ? 'live + simulated mix' : 'simulated observations'

  return (
    <div className="min-h-full">
      <Header
        cities={cities}
        selectedCityId={selectedCityId}
        onCityChange={handleCityChange}
        health={healthQuery.data}
        isFetching={anyFetching || refreshMutation.isPending}
        onRefresh={() => void queryClient.invalidateQueries()}
        healthError={healthQuery.error}
      />

      <main className="mx-auto max-w-[1400px] space-y-4 px-4 py-5 sm:px-6">
        {/* Section navigation (lightweight tabs, no router dependency) */}
        <nav aria-label="Dashboard sections" className="flex gap-1.5">
          {([
            { id: 'overview', label: 'Overview' },
            { id: 'analytics', label: 'Analytics' },
            { id: 'twin', label: 'Digital Twin' },
            { id: 'intelligence', label: 'Intelligence' },
          ] as const).map((v) => (
            <TogglePill
              key={v.id}
              label={v.label}
              active={activeView === v.id}
              onSelect={() => setActiveView(v.id)}
            />
          ))}
        </nav>

        {activeView === 'overview' && (
        <>
        {/* Filters */}
        <DataLayersBar
          selected={sourceFilter}
          onChange={(value) => setSourceFilter(value)}
          hours={windowHours}
          onHoursChange={(h) => setWindowHours(h)}
        />

        {/* KPI strip */}
        <section aria-label="City summary KPIs">
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <KpiCard
              label="Temperature"
              value={summary?.temperature_c?.value ?? null}
              unit={summary?.temperature_c?.unit ?? '°C'}
              icon="🌦️"
              accent="#22d3ee"
              loading={summaryLoading}
              synthetic={summary?.temperature_c?.synthetic ?? true}
              detail={summary?.temperature_c?.recorded_at ? `observed ${formatClock(summary.temperature_c.recorded_at)}Z` : null}
            />
            <KpiCard
              label="PM2.5"
              value={summary?.pm25_ugm3?.value ?? null}
              unit={summary?.pm25_ugm3?.unit ?? 'µg/m³'}
              icon="🌫️"
              accent="#a78bfa"
              loading={summaryLoading}
              synthetic={summary?.pm25_ugm3?.synthetic ?? true}
              detail={summary?.pm25_ugm3?.location ?? undefined}
            />
            <KpiCard
              label="Transit Load"
              value={summary?.transit_load_pct?.value ?? null}
              unit={summary?.transit_load_pct?.unit ?? '%'}
              icon="🚇"
              accent="#818cf8"
              loading={summaryLoading}
              synthetic={summary?.transit_load_pct?.synthetic ?? true}
              detail={summary?.transit_delay_min?.value != null ? `delay ${summary.transit_delay_min.value} min` : null}
            />
            <KpiCard
              label="Incidents"
              value={summary?.active_incidents ?? null}
              unit={`in ${summary?.window_hours ?? windowHours}h`}
              icon="⚠️"
              accent="#f97316"
              loading={summaryLoading}
              synthetic={summary?.data_quality !== 'live'}
            />
          </div>
          <p className="mt-2 text-[10px] text-slate-500">
            Showing {qualityLabel} · window {summary?.window_hours ?? windowHours}h ·{' '}
            {summary?.generated_at ? `latest observation ${formatClock(summary.generated_at)}Z` : 'no observations yet'}
          </p>
        </section>

        {/* Map + side panel */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card
            title="Civic Map"
            subtitle={city ? `${city.name} · OpenStreetMap` : 'OpenStreetMap'}
            className="xl:col-span-2"
            right={
              selectedRecord ? (
                <span className="hidden rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-[10px] font-semibold text-accent sm:inline">
                  focused: {selectedRecord.location_name}
                </span>
              ) : undefined
            }
          >
            <CityMap
              city={city}
              records={visibleRecords}
              loading={dataQuery.isLoading || recordsQuery.isLoading}
              mode={dataQuery.data?.mode ?? dataMode}
              selectedId={selectedRecord?.id ?? null}
              onSelect={(record) => setSelectedRecord(record)}
            />
          </Card>

          <Card title="Latest Records" subtitle="Click a row to focus its marker">
            <RecordsFeed
              records={visibleRecords}
              loading={dataQuery.isLoading || recordsQuery.isLoading}
              selectedId={selectedRecord?.id ?? null}
              onSelect={(record) => setSelectedRecord(record)}
            />
          </Card>
        </div>

        {/* Chart + data sources */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card
            title="Severity Distribution"
            subtitle={dataMode === 'database' ? 'From civic_data observations' : 'Synthetic demo distribution'}
            className="xl:col-span-2"
          >
            <SeverityChart
              breakdown={severityQuery.data?.breakdown}
              loading={severityQuery.isLoading}
            />
          </Card>

          <Card title="Data Sources & Refresh" subtitle="Provider health and manual ingestion">
            <SourceHealth
              sources={sourcesQuery.data?.sources}
              loading={sourcesQuery.isLoading}
              lastRefreshSecondsAgo={sourcesQuery.data?.last_refresh_seconds_ago ?? null}
              refreshing={refreshMutation.isPending}
              refreshResult={refreshMutation.data ?? null}
              onRefresh={() => refreshMutation.mutate()}
            />
          </Card>
        </div>

        {/* Alerts, companion, locations */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card
            title="Alert Center"
            subtitle="Deduplicated, evidence-backed observations"
            right={
              <button
                type="button"
                onClick={() => setAutoRefresh((v) => !v)}
                aria-pressed={autoRefresh}
                className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                  autoRefresh
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-white/10 text-slate-400 hover:text-slate-200'
                }`}
              >
                auto refresh {autoRefresh ? 'on' : 'off'}
              </button>
            }
          >
            <AlertCenter
              report={alertsQuery.data}
              loading={alertsQuery.isLoading}
              busyKey={busyKey}
              onAcknowledge={(key) => acknowledgeMutation.mutate(key)}
              onDismiss={(key) => dismissMutation.mutate(key)}
            />
          </Card>

          <Card title="Operations Copilot" subtitle="Validated read-only tools + grounded answers">
            <CopilotPanel
              answer={copilotAnswer ?? undefined}
              loading={copilotMutation.isPending}
              error={copilotMutation.error}
              onAsk={(q) => copilotMutation.mutate(q)}
              windowHours={windowHours}
            />
          </Card>

          <Card title="Location Comparison" subtitle={`Coverage-honest averages · ${windowHours}h`}>
            <LocationsPanel
              report={locationsQuery.data}
              loading={locationsQuery.isLoading}
              hours={windowHours}
            />
          </Card>
        </div>

        {/* Historical replay (stored data only) */}
        <Card
          title="Historical Replay"
          subtitle="Hourly averages from stored records — gaps are shown, never filled"
        >
          <HistoryChart
            report={historyQuery.data}
            loading={historyQuery.isLoading}
            hours={historyHours}
            onHoursChange={setHistoryHours}
            onRefresh={() => void historyQuery.refetch()}
            refreshing={historyQuery.isFetching}
          />
        </Card>

        {/* Intelligence row */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <Card
            title="Civic Briefing"
            subtitle={`Grounded in ${summary?.window_hours ?? windowHours}h of observations`}
          >
            <AiSummaryPanel
              report={aiSummaryQuery.data}
              loading={aiSummaryQuery.isLoading}
              error={aiSummaryQuery.error}
            />
          </Card>

          <Card title="Anomaly Watch" subtitle="Unusual values vs rolling baseline">
            <AnomaliesPanel
              report={anomaliesQuery.data}
              loading={anomaliesQuery.isLoading}
              onDetect={() => detectMutation.mutate()}
              detecting={detectMutation.isPending}
            />
          </Card>

          <Card title="Associations" subtitle="Metric pairs over aligned hours">
            <CorrelationsPanel
              report={correlationsQuery.data}
              loading={correlationsQuery.isLoading}
            />
          </Card>
        </div>

        </>
        )}

        {activeView === 'analytics' && (
          <AnalyticsView cityId={selectedCityId} windowHours={windowHours} />
        )}

        {activeView === 'twin' && (
          <TwinView cityId={selectedCityId} windowHours={windowHours} />
        )}

        {activeView === 'intelligence' && (
          <IntelligenceView cityId={selectedCityId} windowHours={windowHours} />
        )}

        {/* System status */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <DataSourcePanel
            health={healthQuery.data}
            settings={settingsQuery.data}
            healthError={healthQuery.error}
            recordsNotice={recordsQuery.data?.notice}
            mode={dataMode}
            className="xl:col-span-3"
          />
        </div>

        <footer className="pb-4 pt-2 text-center text-[10px] text-slate-600">
          CityPulse Phases 1-9 · map data © OpenStreetMap contributors · weather © Open-Meteo ·
          synthetic data is always labeled — nothing here is an official measurement
        </footer>
      </main>
    </div>
  )
}
