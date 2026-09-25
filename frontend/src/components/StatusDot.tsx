interface StatusDotProps {
  tone: 'ok' | 'warn' | 'down'
  label: string
  detail?: string
}

const TONE_STYLES: Record<StatusDotProps['tone'], { dot: string; text: string; pulse: boolean }> = {
  ok: { dot: 'bg-emerald-400', text: 'text-emerald-300', pulse: true },
  warn: { dot: 'bg-amber-400', text: 'text-amber-300', pulse: true },
  down: { dot: 'bg-rose-500', text: 'text-rose-300', pulse: false },
}

/** Small live-status indicator (dot + label) used across panels. */
export default function StatusDot({ tone, label, detail }: StatusDotProps) {
  const styles = TONE_STYLES[tone]
  return (
    <div className="flex items-start gap-2.5">
      <span className="relative mt-1.5 flex h-2.5 w-2.5 shrink-0">
        {styles.pulse && (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${styles.dot} opacity-40`} />
        )}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${styles.dot}`} />
      </span>
      <div className="min-w-0">
        <p className={`text-xs font-semibold ${styles.text}`}>{label}</p>
        {detail && <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{detail}</p>}
      </div>
    </div>
  )
}
