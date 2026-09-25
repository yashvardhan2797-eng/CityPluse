import type { ReactNode } from 'react'

interface TogglePillProps {
  label: ReactNode
  active: boolean
  onSelect: () => void
  /** Accessible name when the label is not descriptive text. */
  ariaLabel?: string
}

/**
 * Shared aria-pressed pill used by every filter/toggle group (layers, time
 * windows, metric filters, history ranges) — one consistent style and a11y.
 */
export function TogglePill({ label, active, onSelect, ariaLabel }: TogglePillProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      aria-label={ariaLabel}
      className={`rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-colors ${
        active
          ? 'border-accent/50 bg-accent/10 text-accent'
          : 'border-white/10 text-slate-400 hover:border-white/25 hover:text-slate-200'
      }`}
    >
      {label}
    </button>
  )
}
