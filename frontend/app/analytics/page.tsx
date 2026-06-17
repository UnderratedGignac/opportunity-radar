'use client'

import useSWR from 'swr'
import { api } from '../../lib/api'
import type { Opportunity } from '../../lib/types'

const fetcher = () => api.opportunities.list({ limit: 100 })

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card p-5">
      <p className="text-3xl font-bold text-white">{value}</p>
      <p className="text-sm text-slate-400 mt-1">{label}</p>
      {sub && <p className="text-xs text-slate-600 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function AnalyticsPage() {
  const { data, isLoading } = useSWR('analytics', fetcher)
  const opps: Opportunity[] = data?.data ?? []

  const total = opps.length
  const pursued = opps.filter(o => ['pursued', 'demo_booked', 'converted'].includes(o.status)).length
  const converted = opps.filter(o => o.status === 'converted').length
  const avgScore = total ? Math.round(opps.reduce((s, o) => s + o.opportunity_score, 0) / total) : 0
  const pursuitRate = total ? Math.round((pursued / total) * 100) : 0
  const convRate = pursued ? Math.round((converted / pursued) * 100) : 0

  // Signal type breakdown
  const signalCounts: Record<string, number> = {}
  for (const opp of opps) {
    for (const s of (opp.signals || [])) {
      signalCounts[s.signal.type] = (signalCounts[s.signal.type] ?? 0) + 1
    }
  }
  const topSignals = Object.entries(signalCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)

  // Score distribution
  const buckets = { '80-100': 0, '65-79': 0, '0-64': 0 }
  for (const opp of opps) {
    if (opp.opportunity_score >= 80) buckets['80-100']++
    else if (opp.opportunity_score >= 65) buckets['65-79']++
    else buckets['0-64']++
  }

  if (isLoading) return <div className="text-slate-500 py-16 text-center">Loading analytics...</div>

  return (
    <div>
      <h1 className="text-xl font-bold text-white mb-6">Analytics</h1>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
        <StatCard label="Total opportunities" value={total} />
        <StatCard label="Avg score" value={avgScore} />
        <StatCard label="Pursued" value={pursued} />
        <StatCard label="Converted" value={converted} />
        <StatCard label="Pursuit rate" value={`${pursuitRate}%`} sub="of total" />
        <StatCard label="Conversion rate" value={`${convRate}%`} sub="of pursued" />
      </div>

      <div className="grid sm:grid-cols-2 gap-6">
        {/* Score distribution */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Score Distribution</h2>
          {Object.entries(buckets).map(([label, count]) => {
            const pct = total ? Math.round((count / total) * 100) : 0
            const color = label === '80-100' ? 'bg-green-500' : label === '65-79' ? 'bg-amber-500' : 'bg-slate-600'
            return (
              <div key={label} className="mb-3">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Score {label}</span>
                  <span>{count} ({pct}%)</span>
                </div>
                <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            )
          })}
        </div>

        {/* Signal type breakdown */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Top Signal Types</h2>
          <div className="space-y-3">
            {topSignals.map(([type, count]) => {
              const pct = total ? Math.round((count / total) * 100) : 0
              return (
                <div key={type}>
                  <div className="flex justify-between text-xs text-slate-400 mb-1">
                    <span className="capitalize">{type.replace('_', ' ')}</span>
                    <span>{count}</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500/70 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
            {topSignals.length === 0 && (
              <p className="text-sm text-slate-600">No signal data yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
