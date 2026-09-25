import { motion } from 'framer-motion'
import type { CityInfo, HealthInfo } from '../types'

interface HeaderProps {
  cities: CityInfo[]
  selectedCityId: string
  onCityChange: (cityId: string) => void
  health: HealthInfo | undefined
  isFetching: boolean
  onRefresh: () => void
  healthError: unknown
}

/** Sticky command-center header with brand, city selector, and status chips. */
export default function Header({
  cities,
  selectedCityId,
  onCityChange,
  health,
  isFetching,
  onRefresh,
  healthError,
}: HeaderProps) {
  const mode = health?.mode
  const modeChip = healthError
    ? { label: 'API OFFLINE', cls: 'border-rose-400/40 bg-rose-500/10 text-rose-300' }
    : mode === 'database'
      ? { label: 'LIVE DB (SAMPLE)', cls: 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300' }
      : mode === 'demo'
        ? { label: 'DEMO MODE', cls: 'border-amber-400/40 bg-amber-500/10 text-amber-300' }
        : { label: '…', cls: 'border-white/10 bg-white/5 text-slate-400' }

  return (
    <header className="sticky top-0 z-[900] border-b border-white/5 bg-navy-950/85 backdrop-blur">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <motion.span
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.4 }}
            className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-accent/30 bg-accent/10"
          >
            <span className="h-2.5 w-2.5 animate-pulse-dot rounded-full bg-accent shadow-glow" />
          </motion.span>
          <div>
            <h1 className="text-base font-bold leading-tight tracking-tight text-slate-50">
              City<span className="text-accent">Pulse</span>
            </h1>
            <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-slate-500">
              Civic Command Center
            </p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2.5">
          {/* City selector */}
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <span className="hidden sm:inline">City</span>
            <select
              value={selectedCityId}
              onChange={(event) => onCityChange(event.target.value)}
              className="rounded-lg border border-white/10 bg-navy-800 px-3 py-2 text-sm font-medium text-slate-100 outline-none transition-colors hover:border-accent/40 focus:border-accent/60"
              aria-label="Select city"
            >
              {cities.map((city) => (
                <option key={city.id} value={city.id}>
                  {city.name} — {city.country}
                </option>
              ))}
            </select>
          </label>

          {/* Data mode chip */}
          <span className={`rounded-full border px-3 py-1.5 text-[10px] font-bold tracking-wider ${modeChip.cls}`}>
            {modeChip.label}
          </span>

          {/* Refresh */}
          <button
            type="button"
            onClick={onRefresh}
            disabled={isFetching}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-navy-800 px-3 py-2 text-xs font-semibold text-slate-200 transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg
              className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
            </svg>
            {isFetching ? 'Syncing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Offline banner */}
      {healthError ? (
        <div className="border-t border-rose-500/20 bg-rose-500/10 px-4 py-1.5 text-center text-[11px] text-rose-200 sm:px-6">
          Cannot reach the CityPulse API on port 5000 — start it with{' '}
          <code className="rounded bg-navy-900 px-1 font-mono">python app.py</code>, then refresh.
        </div>
      ) : null}
    </header>
  )
}
