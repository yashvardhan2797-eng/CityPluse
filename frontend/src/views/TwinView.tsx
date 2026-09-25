import { useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, ZoomControl } from 'react-leaflet'
import { useMutation, useQuery } from '@tanstack/react-query'
import Card from '../components/Card'
import { TogglePill } from '../components/TogglePill'
import { TextSkeleton } from '../components/Skeletons'
import {
  fetchImpactBrief,
  fetchScenarioModels,
  fetchTwin,
  runScenario,
} from '../api'
import type { ScenarioModelInfo, ScenarioRunResult, TwinZone } from '../types'

interface Props {
  cityId: string
  windowHours: number
}

const EDGE_COLOR = 'rgba(148,163,184,0.35)'

function zoneTone(zone: TwinZone): { color: string; label: string } {
  const flags = zone.anomalies_nearby.length
  if (flags > 0) return { color: '#f59e0b', label: `${flags} anomaly flag${flags === 1 ? '' : 's'}` }
  if (zone.events_nearby.length > 0) return { color: '#f97316', label: `${zone.events_nearby.length} active event${zone.events_nearby.length === 1 ? '' : 's'}` }
  return { color: '#34d399', label: 'no flags nearby' }
}

/** Zone explorer: map, per-zone metrics with deltas, and advisory hooks. */
function ZoneDetail({ zone, onAskImpact }: { zone: TwinZone; onAskImpact: (metric: string) => void }) {
  const metrics = useMemo(
    () => Object.entries(zone.metrics).sort((a, b) => (b[1].recent_avg ?? -1e9) - (a[1].recent_avg ?? -1e9)),
    [zone],
  )
  const tone = zoneTone(zone)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ background: tone.color }}
          aria-hidden
        />
        <p className="text-xs font-semibold text-slate-100">{zone.location}</p>
        <span className="text-[10px] text-slate-500">
          {tone.label} · {zone.coverage.recent_metric_points} obs / {zone.coverage.recent_window_hours}h
        </span>
      </div>

      <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {metrics.map(([metric, m]) => (
          <div key={metric} className="rounded-lg border border-white/10 bg-navy-800/40 px-2.5 py-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-[11px] text-slate-300">{metric}</span>
              <span className="text-[11px] font-semibold text-slate-100">
                {m.recent_avg ?? 'no data'}
                {m.delta_pct != null && (
                  <span className={m.delta_pct >= 0 ? 'ml-1 text-rose-300' : 'ml-1 text-emerald-300'}>
                    {m.delta_pct >= 0 ? '▲' : '▼'} {Math.abs(m.delta_pct)}%
                  </span>
                )}
              </span>
            </div>
            <p className="mt-0.5 text-[9px] text-slate-500">
              prev {m.previous_avg ?? '—'} · {m.recent_observations} obs
              {m.note ? ` · ${m.note}` : ''}
            </p>
          </div>
        ))}
      </div>

      {zone.anomalies_nearby.length > 0 && (
        <div className="rounded-lg border border-amber-400/25 bg-amber-500/5 p-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">anomaly flags near zone</p>
          {zone.anomalies_nearby.map((a, i) => (
            <button
              key={`${a.metric}-${a.observed_bucket}-${i}`}
              type="button"
              onClick={() => onAskImpact(a.metric)}
              className="mt-1 block w-full rounded-md px-1.5 py-1 text-left text-[10px] text-slate-300 hover:bg-white/5"
            >
              {a.metric} → {a.observed_value} (z={a.deviation_score}) · {a.distance_km} km · click for impact brief →
            </button>
          ))}
        </div>
      )}

      {zone.events_nearby.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-navy-800/40 p-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">events near zone</p>
          {zone.events_nearby.map((e, i) => (
            <p key={`${e.event_ref}-${i}`} className="mt-1 text-[10px] text-slate-300">
              {e.is_simulated ? '[SIMULATED] ' : ''}{e.title} · {e.severity} · {e.status} · {e.distance_km} km
            </p>
          ))}
        </div>
      )}

      {zone.advisories.length > 0 && (
        <div className="rounded-lg border border-accent/25 bg-accent/5 p-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-accent">
            advisory interventions (no action executed)
          </p>
          {zone.advisories.map((iv) => (
            <p key={iv.id} className="mt-1 text-[10px] leading-relaxed text-slate-300">
              • {iv.title} — {iv.rationale} <span className="text-slate-500">({iv.limits})</span>
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

/** Baseline vs scenario estimate rows with the formula printed inline. */
function ScenarioRows({ result }: { result: ScenarioRunResult }) {
  return (
    <div className="space-y-1.5">
      {result.rows.map((row) => (
        <div key={row.indicator} className="rounded-lg border border-white/10 bg-navy-800/40 px-2.5 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <span className="text-[11px] font-semibold text-slate-200">
              {row.indicator}
              {row.unit ? <span className="ml-1 font-normal text-slate-500">({row.unit})</span> : null}
            </span>
            <span className="text-[11px] text-slate-300">
              baseline <strong className="text-slate-100">{row.baseline}</strong>
              {' → '}
              <strong className={Number(row.scenario) >= row.baseline ? 'text-rose-300' : 'text-emerald-300'}>
                {row.scenario}
              </strong>
            </span>
          </div>
          <p className="mt-0.5 break-words font-mono text-[9px] leading-relaxed text-slate-500">{row.formula}</p>
        </div>
      ))}
      {result.tradeoffs.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[10px] text-slate-400">
          {result.tradeoffs.map((t) => <li key={t}>{t}</li>)}
        </ul>
      )}
    </div>
  )
}

/** One selectable scenario model with adjustable, validated parameters. */
function ScenarioPanel({
  model,
  cityId,
}: {
  model: ScenarioModelInfo
  cityId: string
}) {
  const [values, setValues] = useState<Record<string, number>>(
    () => Object.fromEntries(Object.entries(model.params).map(([k, v]) => [k, v.default])),
  )
  const run = useMutation({
    mutationFn: () => runScenario(cityId, model.model_id, values),
  })

  return (
    <div className="rounded-xl border border-white/10 bg-navy-900/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-slate-100">{model.name}</p>
          <p className="text-[10px] text-slate-500">{model.description}</p>
        </div>
        <button
          type="button"
          onClick={() => run.mutate()}
          disabled={run.isPending}
          className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-[11px] font-semibold text-accent hover:bg-accent/20 disabled:opacity-40"
        >
          {run.isPending ? 'running…' : 'Run scenario'}
        </button>
      </div>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {Object.entries(model.params).map(([key, spec]) => (
          <label key={key} className="block">
            <span className="text-[10px] text-slate-400">
              {key} ({spec.unit}) · {spec.min}–{spec.max}
            </span>
            <input
              type="range"
              min={spec.min}
              max={spec.max}
              step={(spec.max - spec.min) / 100}
              value={values[key] ?? spec.default}
              onChange={(e) => setValues((v) => ({ ...v, [key]: Number(e.target.value) }))}
              className="mt-1 w-full accent-cyan-400"
            />
            <span className="text-[10px] font-semibold text-slate-200">{values[key] ?? spec.default}</span>
          </label>
        ))}
      </div>

      {run.error ? (
        <p className="mt-2 rounded-lg border border-rose-400/30 bg-rose-500/5 px-2.5 py-2 text-[11px] text-rose-300">
          {run.error.message}
        </p>
      ) : run.data ? (
        <div className="mt-2">
          <p className="mb-1 rounded-md border border-amber-400/25 bg-amber-500/5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
            {run.data.simulation_label}
          </p>
          <ScenarioRows result={run.data} />
          <p className="mt-1.5 text-[9px] text-slate-500">
            Baseline: {Object.values(run.data.baseline_inputs).map((b) => `${b.value ?? 'no data'} (${b.n_points} pts)`).join(', ')} ·
            {' '}models reuse documented coefficients; identical inputs reproduce identical outputs.
          </p>
        </div>
      ) : (
        <p className="mt-2 text-[10px] text-slate-500">
          Set parameters and run — baseline comes from stored observations; scenario numbers are labeled model outputs.
        </p>
      )}
    </div>
  )
}

/** Urban Digital Twin: map-based zone exploration + Scenario Lab. */
export default function TwinView({ cityId, windowHours: _windowHours }: Props) {
  const [hours, setHours] = useState(24)
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null)
  const [impactMetric, setImpactMetric] = useState<string | undefined>(undefined)

  const twin = useQuery({
    queryKey: ['twin', cityId, hours],
    queryFn: () => fetchTwin(cityId, hours),
  })
  const models = useQuery({
    queryKey: ['scenario-models'],
    queryFn: fetchScenarioModels,
  })
  const impact = useQuery({
    queryKey: ['impact', cityId, impactMetric ?? 'auto'],
    queryFn: () => fetchImpactBrief(cityId, impactMetric, 72),
    enabled: impactMetric !== undefined,
  })

  const zones = twin.data?.zones ?? []
  const selectedZone = zones.find((z) => z.id === selectedZoneId) ?? null
  // First zone's coordinates anchor the map; recompute only when the query data changes.
  const anchor = twin.data?.zones?.[0]
  const center = useMemo<[number, number]>(
    () =>
      anchor
        ? [anchor.latitude, anchor.longitude]
        : cityId === 'delhi'
          ? [28.6139, 77.209]
          : cityId === 'mumbai'
            ? [19.076, 72.8777]
            : [12.9716, 77.5946],
    [anchor, cityId],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">twin window</span>
        {[6, 24, 48, 72].map((h) => (
          <TogglePill key={h} label={`${h}h`} active={hours === h} onSelect={() => setHours(h)} />
        ))}
        <span className="ml-auto rounded-md border border-amber-400/25 bg-amber-500/5 px-2 py-1 text-[10px] text-amber-300">
          advisory only · zones exist only where data exists
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          title="Zone Map"
          subtitle={`${zones.length} observed zones · click to inspect`}
          className="xl:col-span-2"
        >
          {twin.isLoading ? (
            <div className="h-[420px]"><TextSkeleton lines={8} /></div>
          ) : twin.data?.status === 'unavailable' ? (
            <p className="p-3 text-[11px] text-rose-300">Twin unavailable: {twin.data.error}</p>
          ) : (
            <div className="h-[420px] overflow-hidden rounded-xl border border-white/5">
              <MapContainer center={center} zoom={11} scrollWheelZoom zoomControl={false} className="h-full w-full">
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <ZoomControl position="bottomright" />
                {zones.map((zone) => {
                  const tone = zoneTone(zone)
                  const active = zone.id === selectedZoneId
                  return (
                    <CircleMarker
                      key={zone.id}
                      center={[zone.latitude, zone.longitude]}
                      radius={active ? 11 : 8}
                      pathOptions={{
                        color: tone.color,
                        fillColor: tone.color,
                        fillOpacity: active ? 0.6 : 0.3,
                        weight: active ? 3 : 1.5,
                      }}
                      eventHandlers={{ click: () => setSelectedZoneId(zone.id) }}
                    >
                      <Tooltip direction="top" offset={[0, -6]}>
                        <span className="text-xs font-semibold">{zone.location}</span>
                        <br />
                        <span className="text-[10px] text-slate-300">
                          {tone.label} · {zone.coverage.recent_metric_points} obs
                        </span>
                      </Tooltip>
                    </CircleMarker>
                  )
                })}
                {/* Co-location hint: lines from flagged zones to their nearest flagged peer */}
                {zones
                  .filter((z) => z.anomalies_nearby.length > 0)
                  .slice(0, 1)
                  .flatMap((z) =>
                    zones
                      .filter((o) => o.id !== z.id && o.anomalies_nearby.length > 0)
                      .slice(0, 3)
                      .map((o) => (
                        <Polyline
                          key={`link-${z.id}-${o.id}`}
                          positions={[[z.latitude, z.longitude], [o.latitude, o.longitude]]}
                          pathOptions={{ color: EDGE_COLOR, dashArray: '4 4', weight: 1 }}
                        />
                      )),
                  )}
              </MapContainer>
            </div>
          )}
        </Card>

        <Card title="Zone Inspector" subtitle={selectedZone ? selectedZone.location : 'select a zone on the map'}>
          {twin.isLoading ? (
            <TextSkeleton lines={6} />
          ) : selectedZone ? (
            <ZoneDetail zone={selectedZone} onAskImpact={(metric) => setImpactMetric(metric)} />
          ) : (
            <p className="text-[11px] text-slate-500">
              Click any zone marker to see its metrics, recent-vs-previous deltas, nearby anomaly flags,
              active events, and applicable advisory interventions. Green markers have no flags nearby.
            </p>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card
          title="Impact Engine"
          subtitle="Anomaly → documented impact → advisory interventions"
          className="xl:col-span-2"
        >
          {!impactMetric ? (
            <p className="text-[11px] text-slate-500">
              Click an anomaly flag in the Zone Inspector (or pick a metric below) to build an impact brief:
              related anomalies by time window and geo proximity, documented impact estimates, advisory
              interventions, and a baseline-vs-simulated comparison.
            </p>
          ) : impact.isLoading ? (
            <TextSkeleton lines={6} />
          ) : impact.error ? (
            <p className="text-[11px] text-rose-300">Impact engine error: {impact.error.message}</p>
          ) : impact.data?.status === 'no_anomaly' ? (
            <p className="text-[11px] text-slate-500">{impact.data.note}</p>
          ) : impact.data ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-[10px]">
                <span className="rounded-md border border-amber-400/25 bg-amber-500/5 px-2 py-1 font-semibold uppercase tracking-wider text-amber-300">
                  {impact.data.anomaly?.metric} anomaly
                </span>
                <span className="text-slate-400">
                  observed {impact.data.anomaly?.observed_value} vs baseline {impact.data.anomaly?.baseline_value}
                  {' '}· z={impact.data.anomaly?.deviation_score} · confidence {impact.data.anomaly?.confidence}
                </span>
                <button
                  type="button"
                  onClick={() => setImpactMetric(undefined)}
                  className="ml-auto text-slate-500 underline hover:text-slate-300"
                >
                  clear
                </button>
              </div>

              {impact.data.related_anomalies && (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded-lg border border-white/10 bg-navy-800/40 p-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      same-hour co-flags ({impact.data.related_anomalies.time_window.related.length})
                    </p>
                    {impact.data.related_anomalies.time_window.related.length === 0 ? (
                      <p className="mt-1 text-[10px] text-slate-500">none in this bucket</p>
                    ) : (
                      impact.data.related_anomalies.time_window.related.map((r, i) => (
                        <p key={i} className="mt-1 text-[10px] text-slate-300">
                          {r.metric} · {r.observed_value} (z={r.deviation_score})
                        </p>
                      ))
                    )}
                    <p className="mt-1 text-[9px] text-slate-600">
                      {impact.data.related_anomalies.time_window.note}
                    </p>
                  </div>
                  <div className="rounded-lg border border-white/10 bg-navy-800/40 p-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      nearby zones (≤{impact.data.related_anomalies.geo_proximity.radius_km} km)
                    </p>
                    {impact.data.related_anomalies.geo_proximity.zones.length === 0 ? (
                      <p className="mt-1 text-[10px] text-slate-500">no geolocated observations</p>
                    ) : (
                      impact.data.related_anomalies.geo_proximity.zones.slice(0, 4).map((z) => (
                        <p key={z.location} className="mt-1 text-[10px] text-slate-300">
                          {z.location} · {z.distance_km} km · {z.avg_value}
                          {z.synthetic ? ' · simulated' : ''}
                        </p>
                      ))
                    )}
                  </div>
                </div>
              )}

              {impact.data.impact_estimates && (
                <div>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    baseline vs simulated ({impact.data.impact_estimates.intervention ?? 'no intervention modeled'})
                  </p>
                  <div className="space-y-1.5">
                    {impact.data.impact_estimates.comparison.map((row) => (
                      <div key={row.indicator} className="rounded-lg border border-white/10 bg-navy-800/40 px-2.5 py-2">
                        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                          <span className="text-[11px] font-semibold text-slate-200">{row.indicator}</span>
                          <span className="text-[11px] text-slate-300">
                            {row.baseline} → {row.simulated}
                            <span className={row.change <= 0 ? 'ml-2 text-emerald-300' : 'ml-2 text-rose-300'}>
                              ({row.change >= 0 ? '+' : ''}{row.change})
                            </span>
                          </span>
                        </div>
                        <p className="mt-0.5 break-words font-mono text-[9px] text-slate-500">{row.formula}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {impact.data.interventions && impact.data.interventions.length > 0 && (
                <div className="rounded-lg border border-accent/25 bg-accent/5 p-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-accent">
                    advisory interventions — nothing is dispatched
                  </p>
                  {impact.data.interventions.map((iv) => (
                    <p key={iv.id} className="mt-1 text-[10px] leading-relaxed text-slate-300">
                      • <strong>{iv.title}</strong> — {iv.rationale}
                      <span className="text-slate-500"> ({iv.limits})</span>
                    </p>
                  ))}
                </div>
              )}

              {impact.data.limitations && (
                <details className="text-[10px] text-slate-500">
                  <summary className="cursor-pointer hover:text-slate-300">assumptions & limitations</summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {[...(impact.data.assumptions ?? []), ...impact.data.limitations].map((lim) => (
                      <li key={lim}>{lim}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          ) : null}
        </Card>

        <Card title="Impact Metric" subtitle="Choose which anomaly to explain">
          <div className="flex flex-wrap gap-1.5">
            {['delay_min', 'precipitation_mm', 'incident_count', 'pm25_ugm3', 'pm10_ugm3'].map((m) => (
              <TogglePill
                key={m}
                label={m}
                active={impactMetric === m}
                onSelect={() => setImpactMetric(m)}
              />
            ))}
          </div>
          <p className="mt-2 text-[10px] text-slate-500">
            The brief always uses the newest stored flag for that metric. Estimates are transparent
            heuristics over stored data — advisory decision support, not operational orders.
          </p>
        </Card>
      </div>

      <Card
        title="Scenario Lab"
        subtitle="Transparent what-if models over real baselines — always labeled SIMULATED"
      >
        {models.isLoading ? (
          <TextSkeleton lines={4} />
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {(models.data?.models ?? []).map((m) => (
              <ScenarioPanel key={m.model_id} model={m} cityId={cityId} />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
