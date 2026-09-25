import { useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, ZoomControl, useMap } from 'react-leaflet'
import type { CivicRecord, CityInfo } from '../types'
import { isSyntheticRecord, severityColor, sourceLabel } from '../lib/theme'

interface CityMapProps {
  city: CityInfo | undefined
  records: CivicRecord[]
  loading: boolean
  mode: string
  selectedId: number | null
  onSelect: (record: CivicRecord) => void
}

/** Recenters the map smoothly whenever the selected city changes. */
function MapFlyController({ city }: { city: CityInfo | undefined }) {
  const map = useMap()
  useEffect(() => {
    if (city) {
      map.flyTo([city.lat, city.lon], 12, { duration: 0.8 })
    }
  }, [city, map])
  return null
}

/** Interactive Leaflet map with live/synthetic marker distinction. */
export default function CityMap({ city, records, loading, mode, selectedId, onSelect }: CityMapProps) {
  const center = useMemo<[number, number]>(
    () => (city ? [city.lat, city.lon] : [12.9716, 77.5946]),
    [city],
  )
  const syntheticCount = useMemo(() => records.filter(isSyntheticRecord).length, [records])
  const liveCount = records.length - syntheticCount

  return (
    <div className="relative h-[380px] overflow-hidden rounded-xl border border-white/5 sm:h-[460px]">
      <MapContainer
        center={center}
        zoom={12}
        scrollWheelZoom
        zoomControl={false}
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ZoomControl position="bottomright" />
        <MapFlyController city={city} />

        {records.map((record) => {
          const isFocused = record.id === selectedId
          const synthetic = isSyntheticRecord(record)
          return (
            <CircleMarker
              // Remount on focus change so Leaflet re-applies the CSS pulse
              // class (className is only honored at path initialization).
              key={isFocused ? `${record.id}-focused` : record.id}
              center={[record.latitude, record.longitude]}
              radius={isFocused ? 10 : 7}
              pathOptions={{
                // Synthetic data = hollow markers; live = solid.
                color: severityColor(record.severity),
                fillColor: severityColor(record.severity),
                fillOpacity: synthetic ? 0.12 : isFocused ? 0.75 : 0.45,
                weight: isFocused ? 3 : synthetic ? 2 : 1.5,
                dashArray: synthetic ? '3 3' : undefined,
                className: isFocused ? 'cp-marker-focus' : undefined,
              }}
              eventHandlers={{ click: () => onSelect(record) }}
            >
              <Tooltip direction="top" offset={[0, -6]} opacity={1}>
                <span className="text-xs font-semibold">{record.location_name}</span>
                <br />
                <span className="text-[11px] text-slate-300">
                  {sourceLabel(String(record.source_type))} · {record.value ?? '—'} {record.unit ?? ''}
                </span>
                <br />
                <span className="text-[10px] text-slate-400">
                  {synthetic ? 'SIMULATED data' : 'live observation'} · {record.provider ?? 'demo'}
                </span>
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>

      {/* City badge */}
      <div className="pointer-events-none absolute left-3 top-3 z-[500] rounded-lg border border-white/10 bg-navy-950/85 px-3 py-1.5 shadow-card">
        <p className="text-xs font-semibold text-slate-100">
          {city ? `${city.name}, ${city.country}` : 'Loading city…'}
        </p>
        <p className="text-[10px] text-slate-400">
          {records.length} marker{records.length === 1 ? '' : 's'}
          {liveCount > 0 ? ` · ${liveCount} live` : ''}
          {syntheticCount > 0 ? ` · ${syntheticCount} simulated` : ''}
        </p>
      </div>

      {/* Legend: live vs synthetic */}
      <div className="pointer-events-none absolute right-3 top-3 z-[500] rounded-lg border border-white/10 bg-navy-950/85 px-2.5 py-1.5">
        <p className="flex items-center gap-1.5 text-[10px] text-slate-300">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400/70" /> live
        </p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-300">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-dashed border-amber-400/80" /> simulated
        </p>
      </div>

      {/* Loading veil */}
      {loading && (
        <div className="absolute inset-0 z-[600] flex items-center justify-center bg-navy-950/45">
          <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-navy-900/90 px-4 py-2 text-xs text-slate-300 shadow-card">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            Loading map data…
          </div>
        </div>
      )}

      {/* Honest data labeling — always visible */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-md border border-amber-400/25 bg-navy-950/85 px-2.5 py-1">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-300">
          {mode === 'database'
            ? 'Sample + simulated observations — not official measurements'
            : 'Demo data — synthetic markers'}
        </p>
      </div>
    </div>
  )
}
