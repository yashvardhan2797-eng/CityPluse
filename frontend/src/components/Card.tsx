import type { ReactNode } from 'react'
import { motion } from 'framer-motion'

interface CardProps {
  title: string
  subtitle?: string
  right?: ReactNode
  children: ReactNode
  className?: string
}

/** Panel shell used by every dashboard section for a consistent look. */
export default function Card({ title, subtitle, right, children, className = '' }: CardProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className={`rounded-2xl border border-white/5 bg-navy-900/80 shadow-card backdrop-blur-sm ${className}`}
    >
      <header className="flex items-center justify-between gap-3 border-b border-white/5 px-4 py-3 sm:px-5">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-slate-100">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
        </div>
        {right}
      </header>
      <div className="p-4 sm:p-5">{children}</div>
    </motion.section>
  )
}
