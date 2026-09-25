import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Card from '../components/Card'
import AnalyticsExplorer from '../components/charts/AnalyticsExplorer'
import CorrelationHeatmap from '../components/charts/CorrelationHeatmap'
import EventsAnalytics from '../components/charts/EventsAnalytics'
import SeverityTrendChart from '../components/charts/SeverityTrendChart'
import HealthScoreCard from '../components/charts/HealthScoreCard'
import {
  fetchCorrelations,
  fetchEvents,
  fetchHealthScore,
  fetchHealthTrend,
  fetchHistory,
  fetchLocations,
  fetchSeveritySeries,
} from '../api'

interface Props {
  cityId: string
  windowHours: number
}

/** Graph-first intelligence page: health, heatmap, explorer, events. */
export default function AnalyticsView({ cityId, windowHours }: Props) {
  const [explorerHours, setExplorerHours] = useState(72)
  const [selectedPair, setSelectedPair] = useState<{ a: string; b: string } | null>(null)

  const healthScore = useQuery({
    queryKey: ['health-score', cityId, windowHours],
    queryFn: () => fetchHealthScore(cityId, windowHours),
  })
  const healthTrend = useQuery({
    queryKey: ['health-trend', cityId],
    queryFn: () => fetchHealthTrend(cityId, 7),
  })
  const correlations = useQuery({
    queryKey: ['correlations', cityId, windowHours],
    queryFn: () => fetchCorrelations(cityId, windowHours),
  })
  const history = useQuery({
    queryKey: ['history', cityId, explorerHours],
    queryFn: () => fetchHistory(cityId, explorerHours),
  })
  const locations = useQuery({
    queryKey: ['locations', cityId, windowHours],
    queryFn: () => fetchLocations(cityId, windowHours),
  })
  const events = useQuery({
    queryKey: ['events', cityId],
    queryFn: () => fetchEvents(cityId, { limit: 100 }),
  })
  const severitySeries = useQuery({
    queryKey: ['severity-series', cityId, 72],
    queryFn: () => fetchSeveritySeries(cityId, 72, 'hour'),
  })

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card title="City Health" subtitle="Penalty-based score over documented guidelines">
          <HealthScoreCard
            score={healthScore.data}
            trend={healthTrend.data}
            loading={healthScore.isLoading || healthTrend.isLoading}
          />
        </Card>

        <Card
          title="Correlation Heatmap"
          subtitle={`Pearson r on aligned hourly pairs · ${windowHours}h`}
          className="xl:col-span-2"
        >
          <CorrelationHeatmap
            report={correlations.data}
            loading={correlations.isLoading}
            selectedPair={selectedPair}
            onSelectPair={setSelectedPair}
          />
        </Card>
      </div>

      <Card
        title="Analytics Explorer"
        subtitle="Pick metrics, range, and chart type — generated from stored data"
      >
        <AnalyticsExplorer
          history={history.data}
          locations={locations.data}
          loading={history.isLoading || locations.isLoading}
          hours={explorerHours}
          onHoursChange={setExplorerHours}
        />
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Events & Incidents" subtitle="Lifecycle status, severity profile, resolution times">
          <EventsAnalytics events={events.data} loading={events.isLoading} />
        </Card>

        <Card title="Severity Over Time" subtitle="Stacked observation counts per hour">
          <SeverityTrendChart report={severitySeries.data} loading={severitySeries.isLoading} />
        </Card>

        <Card title="Data Coverage" subtitle="What the analytics above are grounded in">
          <p className="text-[11px] leading-relaxed text-slate-400">
            Every chart on this page is generated from stored observations in Supabase —
            city-wide hourly averages with explicit sample sizes. Missing periods render as
            gaps, never interpolated values. Correlations are associations, not causes.
            Health scores are a transparent penalty model over documented guidelines, not an
            official index. Simulated provider rows are labeled in the source panel.
          </p>
          <p className="mt-2 text-[11px] text-slate-500">
            Events analytics reflect the event lifecycle (including clearly labeled simulation
            drills). Where no events exist yet, panels show empty states instead of placeholders.
          </p>
        </Card>
      </div>
    </div>
  )
}
