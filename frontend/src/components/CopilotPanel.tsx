import { useState } from 'react'
import { motion } from 'framer-motion'
import type { CopilotResponse } from '../types'
import { formatClock } from '../lib/ui'
import { TextSkeleton } from './Skeletons'

interface CopilotPanelProps {
  answer: CopilotResponse | undefined
  loading: boolean
  error: Error | null
  onAsk: (question: string) => void
  windowHours: number
}

const SUGGESTED = [
  'How resilient is the city right now?',
  'What if we divert 40% of traffic?',
  'Any anomalies today?',
  'Compare zones for pm25',
  'What incidents are open?',
]

const TOOL_LABELS: Record<string, string> = {
  get_metric: 'metric lookup',
  get_anomalies: 'anomaly scan',
  compare_zones: 'zone compare',
  list_events: 'event query',
  run_scenario: 'scenario model',
  get_resilience: 'resilience score',
}

/** Phase 9 Operations Copilot: read-only tools + grounded, cited answers. */
export default function CopilotPanel({ answer, loading, error, onAsk, windowHours: _windowHours }: CopilotPanelProps) {
  const [question, setQuestion] = useState('')

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || loading) return
    onAsk(trimmed.slice(0, 500))
  }

  return (
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit(question)
        }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={question}
          maxLength={500}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={`Ask the copilot — tools cover metrics, zones, events, scenarios…`}
          aria-label="Ask the operations copilot"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-navy-800/70 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent/50 focus:outline-none"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-xs font-semibold text-accent transition-colors hover:bg-accent/20 disabled:opacity-40"
        >
          {loading ? '…' : 'Ask'}
        </button>
      </form>

      <div className="flex flex-wrap gap-1.5">
        {SUGGESTED.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQuestion(s)
              submit(s)
            }}
            disabled={loading}
            className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-slate-400 transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      {error ? (
        <div className="rounded-lg border border-rose-400/30 bg-rose-500/5 p-3">
          <p className="text-xs text-rose-300">The copilot could not answer: {error.message}</p>
        </div>
      ) : loading ? (
        <TextSkeleton lines={3} />
      ) : answer ? (
        <motion.div
          key={(answer.generated_at ?? '') + answer.answer.slice(0, 20)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border border-white/10 bg-navy-800/50 p-3"
        >
          {answer.mode === 'copilot_tools' && answer.tools_used.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {answer.tools_used.map((tool) => (
                <span
                  key={tool}
                  className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-accent"
                  title="Validated read-only tool — no raw SQL, no direct DB access"
                >
                  {TOOL_LABELS[tool] ?? tool}
                </span>
              ))}
            </div>
          )}
          <p className="text-xs leading-relaxed text-slate-200">{answer.answer}</p>
          <p className="mt-2 text-[10px] text-slate-500">
            {answer.mode === 'copilot_tools'
              ? `${answer.tools_used.length} read-only tool${answer.tools_used.length === 1 ? '' : 's'} · validated inputs`
              : 'deterministic evidence retriever'}
            {answer.generated_at ? ` · ${formatClock(answer.generated_at)}Z` : ''}
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-600">{answer.disclaimer}</p>
        </motion.div>
      ) : (
        <p className="text-[11px] text-slate-500">
          Ask a question — the copilot runs validated, read-only tools (metric lookups, anomaly scans,
          zone comparisons, event queries, labeled scenario models) and answers only from their output.
          It cannot write to the database or run SQL.
        </p>
      )}
    </div>
  )
}
