'use client'

import { useState } from 'react'
import { ScoreBadge } from './ScoreBadge'
import { SignalChip } from './SignalChip'
import type { Opportunity } from '../lib/types'
import { api } from '../lib/api'

interface Props {
  opp: Opportunity
  onFeedback?: (id: string, action: string) => void
}

export function OpportunityCard({ opp, onFeedback }: Props) {
  const [status, setStatus] = useState(opp.status)
  const [submitting, setSubmitting] = useState(false)

  const handleFeedback = async (action: string) => {
    setSubmitting(true)
    try {
      await api.opportunities.feedback(opp.id, { action: action as any })
      setStatus(action === 'converted' ? 'converted' : action === 'not_relevant' ? 'not_relevant' : 'pursued')
      onFeedback?.(opp.id, action)
    } catch (e) {
      console.error(e)
    } finally {
      setSubmitting(false)
    }
  }

  const copyToClipboard = (text: string) => navigator.clipboard.writeText(text)

  const outreach = opp.outreach_packages?.[0]
  const signals = opp.signals?.slice(0, 4) || []
  const needs = opp.likely_needs?.slice(0, 3) || []

  const statusColors: Record<string, string> = {
    new: 'text-slate-400', viewed: 'text-slate-400',
    pursued: 'text-blue-400', converted: 'text-green-400', not_relevant: 'text-slate-600',
  }

  return (
    <div className="card p-5 flex flex-col gap-4 hover:border-slate-600 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-semibold text-white text-base">{opp.company_name}</h3>
            <span className={`text-xs ${statusColors[status] ?? 'text-slate-400'}`}>
              {status !== 'new' && `• ${status}`}
            </span>
          </div>
          <p className="text-xs text-slate-500">{opp.company_domain}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-500">Confidence {opp.confidence_score}%</span>
          <ScoreBadge score={opp.opportunity_score} />
        </div>
      </div>

      {/* Signals */}
      {signals.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {signals.map((s, i) => (
            <SignalChip key={i} type={s.signal.type} detail={s.signal.detail} />
          ))}
        </div>
      )}

      {/* Likely needs */}
      {needs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {needs.map((n, i) => (
            <span key={i} className="text-xs bg-slate-800 text-slate-300 rounded px-2 py-0.5 border border-slate-700">
              {n}
            </span>
          ))}
        </div>
      )}

      {/* Why now */}
      {opp.timing_rationale && (
        <p className="text-xs text-slate-400 italic border-l-2 border-slate-700 pl-3">
          {opp.timing_rationale}
        </p>
      )}

      {/* Outreach copy */}
      {outreach?.email_body && (
        <details className="text-xs">
          <summary className="cursor-pointer text-blue-400 hover:text-blue-300 select-none mb-2">
            View outreach copy →
          </summary>
          <div className="space-y-2 mt-1">
            {outreach.email_subject && (
              <div className="bg-slate-800/60 rounded p-3 border border-slate-700">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-slate-500 font-medium">Subject</span>
                  <button onClick={() => copyToClipboard(outreach.email_subject)}
                    className="text-slate-500 hover:text-slate-300 text-xs">copy</button>
                </div>
                <p className="text-slate-200">{outreach.email_subject}</p>
              </div>
            )}
            <div className="bg-slate-800/60 rounded p-3 border border-slate-700">
              <div className="flex justify-between items-center mb-1">
                <span className="text-slate-500 font-medium">Email</span>
                <button onClick={() => copyToClipboard(outreach.email_body)}
                  className="text-slate-500 hover:text-slate-300 text-xs">copy</button>
              </div>
              <p className="text-slate-200 whitespace-pre-wrap leading-relaxed">{outreach.email_body}</p>
            </div>
            {outreach.linkedin_message && (
              <div className="bg-slate-800/60 rounded p-3 border border-slate-700">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-slate-500 font-medium">LinkedIn</span>
                  <button onClick={() => copyToClipboard(outreach.linkedin_message)}
                    className="text-slate-500 hover:text-slate-300 text-xs">copy</button>
                </div>
                <p className="text-slate-200">{outreach.linkedin_message}</p>
              </div>
            )}
          </div>
        </details>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-1 border-t border-slate-800">
        <a href={`/opportunities/${opp.id}`}
          className="text-xs text-slate-400 hover:text-white transition-colors px-3 py-1.5 rounded border border-slate-700 hover:border-slate-500">
          Full report →
        </a>
        <button disabled={submitting} onClick={() => handleFeedback('pursued')}
          className="text-xs px-3 py-1.5 rounded bg-blue-600/20 text-blue-400 border border-blue-500/30 hover:bg-blue-600/30 transition-colors disabled:opacity-50">
          Mark Pursued
        </button>
        <button disabled={submitting} onClick={() => handleFeedback('converted')}
          className="text-xs px-3 py-1.5 rounded bg-green-600/20 text-green-400 border border-green-500/30 hover:bg-green-600/30 transition-colors disabled:opacity-50">
          Converted ✓
        </button>
        <button disabled={submitting} onClick={() => handleFeedback('not_relevant')}
          className="text-xs px-3 py-1.5 rounded text-slate-600 hover:text-slate-400 transition-colors disabled:opacity-50 ml-auto">
          Not relevant
        </button>
      </div>
    </div>
  )
}
