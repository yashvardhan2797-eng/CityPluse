import { motion } from 'framer-motion'
import { formatNumber } from '../lib/ui'

interface KpiCardProps {
  label: string
  value: number | null
  unit: string
  icon: string
  accent: string
  loading: boolean
  synthetic?: boolean
  detail?: string | null
}

/** Animated KPI tile with provenance badge (LIVE vs SIM). */
export default function KpiCard({
  label,
  value,
  unit,
  icon,
  accent,
  loading,
  synthetic = false,
  detail,
}: KpiCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      whileHover={{ y: -2 }}
      className="rounded-xl border border-white/5 bg-navy-800/70 p-4"
    >
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-lg text-sm"
          style={{ backgroundColor: `${accent}1f` }}
        >
          {icon}
        </span>
      </div>
      {loading ? (
        <div className="mt-2 h-8 w-20 animate-pulse rounded bg-navy-700/70" />
      ) : (
        <div className="mt-1 flex items-baseline gap-2">
          <p className="font-mono text-2xl font-semibold text-slate-50">
            {formatNumber(value)}
            <span className="ml-1 text-xs font-medium text-slate-400">{unit}</span>
          </p>
          <span
            className={`rounded-full border px-1.5 py-0.5 text-[9px] font-bold tracking-wide ${
              synthetic
                ? 'border-amber-400/40 bg-amber-500/10 text-amber-300'
                : 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300'
            }`}
          >
            {synthetic ? 'SIM' : 'LIVE'}
          </span>
        </div>
      )}
      {detail && !loading && <p className="mt-1 truncate text-[10px] text-slate-500">{detail}</p>}
    </motion.div>
  )
}
