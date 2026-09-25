import { motion } from 'framer-motion'
import type { CivicRecord } from '../types'
import { severityColor, sourceLabel } from '../lib/theme'
import { timeAgo } from '../lib/ui'
import { ListSkeleton } from './Skeletons'

interface RecordsFeedProps {
  records: CivicRecord[]
  loading: boolean
  selectedId: number | null
  onSelect: (record: CivicRecord) => void
}

/** Latest-records feed; clicking a row focuses its map marker. */
export default function RecordsFeed({ records, loading, selectedId, onSelect }: RecordsFeedProps) {
  if (loading) {
    return <ListSkeleton rows={5} className="h-14" />
  }

  if (records.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-white/10 text-sm text-slate-400">
        No records for this city yet.
      </div>
    )
  }

  return (
    <ul className="max-h-[340px] space-y-2 overflow-y-auto pr-1">
      {records.slice(0, 12).map((record, index) => {
        const isSelected = record.id === selectedId
        return (
          <motion.li
            key={record.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.3) }}
          >
            <button
              type="button"
              onClick={() => onSelect(record)}
              className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                isSelected
                  ? 'border-accent/50 bg-accent/10'
                  : 'border-white/5 bg-navy-800/60 hover:border-white/15 hover:bg-navy-700/60'
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: severityColor(record.severity) }}
                  />
                  <p className="truncate text-sm font-medium text-slate-100">{record.location_name}</p>
                </div>
                <p className="shrink-0 font-mono text-sm text-slate-200">
                  {record.value ?? '—'}
                  <span className="ml-1 text-[10px] text-slate-400">{record.unit ?? ''}</span>
                </p>
              </div>
              <div className="mt-1 flex items-center justify-between gap-3 pl-4">
                <p className="truncate text-[11px] text-slate-400">
                  {sourceLabel(String(record.source_type))} · {timeAgo(record.recorded_at)}
                </p>
                <span
                  className="shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                  style={{
                    color: severityColor(record.severity),
                    borderColor: `${severityColor(record.severity)}55`,
                    backgroundColor: `${severityColor(record.severity)}14`,
                  }}
                >
                  {record.severity}
                </span>
              </div>
            </button>
          </motion.li>
        )
      })}
    </ul>
  )
}
