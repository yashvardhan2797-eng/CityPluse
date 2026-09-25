import { useState } from 'react'
import { motion } from 'framer-motion'
import type { CompanionResponse } from '../types'
import { formatClock } from '../lib/ui'
import { TextSkeleton } from './Skeletons'

interface CompanionPanelProps {
  answer: CompanionResponse | undefined
  loading: boolean
  error: Error | null
  onAsk: (question: string) => void
  windowHours: number
}

const SUGGESTED = [
  'What is the PM2.5 right now?',
  'Any anomalies today?',
  'Is air quality related to temperature?',
  'How fresh is the data?',
]

/** Phase 3 civic companion: grounded Q&A — answers cite evidence or say the data does not cover it. */
export default function CompanionPanel({ answer, loading, error, onAsk, windowHours }: CompanionPanelProps) {
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
          placeholder={`Ask about ${windowHours}h of civic evidence…`}
          aria-label="Ask the civic companion"
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
          <p className="text-xs text-rose-300">The companion could not answer: {error.message}</p>
        </div>
      ) : loading ? (
        <TextSkeleton lines={3} />
      ) : answer ? (
        <motion.div
          key={answer.generated_at + answer.question.slice(0, 20)}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border border-white/10 bg-navy-800/50 p-3"
        >
          <p className="text-xs leading-relaxed text-slate-200">{answer.answer}</p>
          <p className="mt-2 text-[10px] text-slate-500">
            {answer.answered_by === 'deterministic-retriever' ? 'Deterministic evidence retriever' : `AI (${answer.answered_by})`}
            {' · '}{formatClock(answer.generated_at)}Z · grounded in {answer.grounded_in?.observations?.length ?? 0} latest observations
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-600">{answer.disclaimer}</p>
        </motion.div>
      ) : (
        <p className="text-[11px] text-slate-500">
          Ask a question — answers come only from stored observations, anomaly flags, and
          association statistics. The companion cannot invent facts beyond the evidence.
        </p>
      )}
    </div>
  )
}
