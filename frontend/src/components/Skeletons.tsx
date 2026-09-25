/** Reusable loading skeletons — one source of truth for every loading state. */

const BASE = 'animate-pulse rounded-lg bg-navy-800/70'

export function KpiSkeletonRow({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="h-[86px] animate-pulse rounded-xl bg-navy-800/70" />
      ))}
    </div>
  )
}

export function ListSkeleton({ rows = 5, className = 'h-12' }: { rows?: number; className?: string }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={`${BASE} ${className}`} />
      ))}
    </div>
  )
}

export function ChartSkeleton({ className = 'h-52' }: { className?: string }) {
  return <div className={`${BASE} ${className}`} />
}

/** Multi-line text skeleton (companion answers, summaries). */
export function TextSkeleton({ lines = 3 }: { lines?: number }) {
  const widths = ['w-3/4', 'w-full', 'w-2/3', 'w-5/6']
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`h-3 animate-pulse rounded bg-navy-800/70 ${widths[i % widths.length]}`} />
      ))}
    </div>
  )
}
