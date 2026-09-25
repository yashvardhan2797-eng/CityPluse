import type { HealthInfo, SettingsInfo } from '../types'
import Card from './Card'
import StatusDot from './StatusDot'

interface DataSourcePanelProps {
  health: HealthInfo | undefined
  settings: SettingsInfo | undefined
  healthError: unknown
  recordsNotice?: string
  mode: string
  className?: string
}

/** Data-source & system status panel with honest labeling about data quality. */
export default function DataSourcePanel({
  health,
  settings,
  healthError,
  recordsNotice,
  mode,
  className = '',
}: DataSourcePanelProps) {
  const dbOk = health?.database_reachable === true

  return (
    <Card
      title="System Status"
      subtitle="API, database, and provider configuration"
      className={className}
      right={
        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 font-mono text-[10px] text-slate-400">
          phase {settings?.phase ?? 1}
        </span>
      }
    >
      <div className="space-y-3.5">
        <StatusDot
          tone={healthError ? 'down' : 'ok'}
          label={healthError ? 'Flask API unreachable' : 'Flask API online'}
          detail={healthError ? 'Start the backend: python app.py' : `v${health?.version ?? ''} · /api/health`}
        />
        <StatusDot
          tone={dbOk ? 'ok' : 'warn'}
          label={dbOk ? 'Supabase PostgreSQL connected' : 'Supabase not connected'}
          detail={
            dbOk
              ? 'Reading seeded sample rows from civic_data'
              : 'Add DATABASE_URL to .env — dashboard runs on demo data meanwhile'
          }
        />
        <StatusDot
          tone={
            settings?.providers && Object.values(settings.providers).some((p) => p.configured)
              ? 'ok'
              : 'warn'
          }
          label={
            settings?.providers
              ? `Providers: ${Object.entries(settings.providers)
                  .filter(([, p]) => p.configured)
                  .map(([key]) => key)
                  .join(', ') || 'none configured — demo mode'}`
              : 'Providers loading…'
          }
          detail={
            settings?.ai_configured
              ? 'AI summaries enabled (server-side key)'
              : 'AI summaries use the deterministic fallback (no provider key)'
          }
        />

        <div className="rounded-lg border border-amber-400/20 bg-amber-400/5 p-3">
          <p className="text-[11px] font-bold uppercase tracking-wider text-amber-300">
            About this data
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-300">
            {mode === 'database'
              ? 'Records come from civic_data. Rows are provenance-stamped: hollow map markers = simulated, solid = live observations. Nothing here is an official measurement.'
              : 'All markers, KPIs, and charts are clearly-labeled synthetic demo data. No live civic measurement is shown.'}
          </p>
          {recordsNotice && (
            <p className="mt-1.5 font-mono text-[10px] text-amber-200/80">API notice: {recordsNotice}</p>
          )}
        </div>
      </div>
    </Card>
  )
}
