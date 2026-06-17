'use client'

import { use, useState } from 'react'
import useSWR from 'swr'
import { ScoreBadge } from '../../../components/ScoreBadge'
import { SignalChip } from '../../../components/SignalChip'
import { api } from '../../../lib/api'

export default function OpportunityDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const { data: opp, error, isLoading } = useSWR(id ? ['opportunity', id] : null, ([, i]) => api.opportunities.get(i))
  const [copied, setCopied] = useState<string | null>(null)

  if (isLoading) return <div className="text-slate-500 py-16 text-center">Loading...</div>
  if (error || !opp) return <div className="text-red-400 py-16 text-center">Opportunity not found.</div>

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  const outreach = opp.outreach_packages?.[0]

  return (
    <div className="max-w-3xl mx-auto">
      {/* Back */}
      <a href="/" className="text-sm text-slate-500 hover:text-slate-300 mb-6 inline-block">← Back to feed</a>

      {/* Header */}
      <div className="card p-6 mb-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-white mb-1">{opp.company_name}</h1>
            <p className="text-slate-500 text-sm">{opp.company_domain}</p>
          </div>
          <ScoreBadge score={opp.opportunity_score} size="lg" />
        </div>
        {opp.timing_rationale && (
          <p className="text-slate-300 text-sm italic border-l-2 border-blue-500/40 pl-4">
            {opp.timing_rationale}
          </p>
        )}
        <div className="mt-4 flex items-center gap-4 text-xs text-slate-500">
          <span>Confidence: {opp.confidence_score}%</span>
          <span>Detected: {new Date(opp.created_at).toLocaleDateString()}</span>
          <span>Status: {opp.status}</span>
        </div>
      </div>

      {/* Signals */}
      <section className="card p-6 mb-6">
        <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Signals Detected</h2>
        <div className="space-y-2">
          {(opp.signals || []).map((s, i) => (
            <div key={i} className="flex items-center gap-3">
              <SignalChip type={s.signal.type} detail={s.signal.detail} />
              <span className="text-xs text-slate-600 ml-auto">
                {s.weighted_score.toFixed(1)} pts
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* Score breakdown */}
      {(opp.score_breakdown || []).length > 0 && (
        <section className="card p-6 mb-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Score Breakdown</h2>
          <div className="space-y-3">
            {opp.score_breakdown.map((item: any, i: number) => {
              const pct = Math.min(100, (item.weighted / 35) * 100)
              return (
                <div key={i}>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span>{item.signal}</span>
                    <span className="text-slate-300 font-medium">{item.weighted?.toFixed(1)} pts</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500/60 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* Likely needs + Decision makers */}
      <div className="grid sm:grid-cols-2 gap-4 mb-6">
        <div className="card p-5">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Likely Needs</h2>
          <ul className="space-y-2">
            {(opp.likely_needs || []).map((n, i) => (
              <li key={i} className="text-sm text-slate-200 flex gap-2">
                <span className="text-blue-500 mt-0.5">•</span>{n}
              </li>
            ))}
          </ul>
        </div>
        <div className="card p-5">
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Decision Makers</h2>
          <ul className="space-y-2">
            {(opp.decision_maker_titles || []).map((t, i) => (
              <li key={i} className="text-sm text-slate-200 flex gap-2">
                <span className="text-purple-400 mt-0.5">→</span>{t}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Outreach copy */}
      {outreach && (
        <section className="card p-6 mb-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Outreach Copy</h2>
          <div className="space-y-4">
            {[
              { label: 'Email Subject', key: 'subject', text: outreach.email_subject },
              { label: 'Cold Email', key: 'email', text: outreach.email_body },
              { label: 'LinkedIn Message', key: 'linkedin', text: outreach.linkedin_message },
              { label: 'Call Opener', key: 'call', text: outreach.call_opener },
            ].filter(f => f.text).map(field => (
              <div key={field.key} className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs text-slate-500 font-semibold uppercase tracking-wide">{field.label}</span>
                  <button onClick={() => copy(field.text, field.key)}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
                    {copied === field.key ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
                <p className="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">{field.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Feedback actions */}
      <section className="card p-6">
        <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Outcome Tracking</h2>
        <div className="flex gap-3 flex-wrap">
          {[
            { action: 'pursued', label: 'Mark Pursued', cls: 'bg-blue-600/20 text-blue-400 border-blue-500/30' },
            { action: 'demo_booked', label: 'Demo Booked', cls: 'bg-purple-600/20 text-purple-400 border-purple-500/30' },
            { action: 'converted', label: 'Converted ✓', cls: 'bg-green-600/20 text-green-400 border-green-500/30' },
            { action: 'not_relevant', label: 'Not Relevant', cls: 'bg-slate-700/40 text-slate-400 border-slate-600/30' },
          ].map(btn => (
            <button key={btn.action}
              onClick={() => api.opportunities.feedback(opp.id, { action: btn.action as any })}
              className={`text-sm px-4 py-2 rounded border transition-colors ${btn.cls}`}>
              {btn.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-600 mt-3">
          Your feedback trains the scoring model — each outcome improves future predictions.
        </p>
      </section>
    </div>
  )
}
