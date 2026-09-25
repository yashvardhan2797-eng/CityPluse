import type { SourceType } from '../types'
import { SOURCE_TYPES } from '../types'
import { SOURCE_META } from '../lib/theme'
import { TogglePill } from './TogglePill'

interface DataLayersBarProps {
  selected: SourceType | 'all'
  onChange: (value: SourceType | 'all') => void
  hours: number
  onHoursChange: (hours: number) => void
}

const WINDOWS = [
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '48h', hours: 48 },
  { label: '72h', hours: 72 },
]

/** Source-type filter chips + time-window selector shared by map/feed/analytics. */
export default function DataLayersBar({ selected, onChange, hours, onHoursChange }: DataLayersBarProps) {
  const options: Array<{ value: SourceType | 'all'; label: string; icon: string }> = [
    { value: 'all', label: 'All layers', icon: '🗺️' },
    ...SOURCE_TYPES.map((t) => ({ value: t, label: SOURCE_META[t].label, icon: SOURCE_META[t].icon })),
  ]

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Data layer filter">
        {options.map((option) => (
          <TogglePill
            key={option.value}
            label={
              <>
                <span aria-hidden className="mr-1">{option.icon}</span>
                {option.label}
              </>
            }
            active={selected === option.value}
            onSelect={() => onChange(option.value)}
          />
        ))}
      </div>

      <div className="flex items-center gap-1.5" role="group" aria-label="Time window">
        <span className="text-[11px] text-slate-500">Window</span>
        {WINDOWS.map((w) => (
          <TogglePill
            key={w.hours}
            label={w.label}
            active={hours === w.hours}
            onSelect={() => onHoursChange(w.hours)}
          />
        ))}
      </div>
    </div>
  )
}
