'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { OpportunityCard } from '../components/OpportunityCard'
import { FilterBar } from '../components/FilterBar'
import { api } from '../lib/api'
import type { Opportunity } from '../lib/types'

const fetcher = ([, params]: [string, Parameters<typeof api.opportunities.list>[0]]) =>
  api.opportunities.list(params)

export default function FeedPage() {
  const [minScore, setMinScore] = useState(60)
  const [status, setStatus] = useState('')
  const [scanDomains, setScanDomains] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')

  const { data, error, isLoading, mutate } = useSWR(
    ['opportunities', { min_score: minScore, status: status || undefined, limit: 30 }],
    fetcher,
    { refreshInterval: 60_000 }
  )

  const opps: Opportunity[] = data?.data ?? []

  const handleScan = async () => {
    const domains = scanDomains.split(/[\s,]+/).filter(Boolean)
    if (!domains.length) return
    setScanning(true)
    try {
      const res = await api.scan.trigger(domains, minScore)
      setScanMsg(`Scan started for ${domains.length} domain(s). Check back in 2-5 minutes.`)
      setTimeout(() => { setScanMsg(''); mutate() }, 6000)
    } catch (e: any) {
      setScanMsg(`Error: ${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  const scoreHighlights = opps.filter(o => o.opportunity_score >= 80).length

  return (
    <div>
      {/* Header KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {[
          { label: 'Total opportunities', value: data?.count ?? 0 },
          { label: 'Score 80+', value: scoreHighlights },
          { label: 'Pursued', value: opps.filter(o => o.status === 'pursued').length },
          { label: 'Converted', value: opps.filter(o => o.status === 'converted').length },
        ].map(kpi => (
          <div key={kpi.label} className="card p-4">
            <p className="text-2xl font-bold text-white">{kpi.value}</p>
            <p className="text-xs text-slate-500 mt-1">{kpi.label}</p>
          </div>
        ))}
      </div>

      {/* Scan trigger */}
      <div className="card p-4 mb-6 flex items-center gap-3">
        <input
          value={scanDomains}
          onChange={e => setScanDomains(e.target.value)}
          placeholder="Scan domains: acme.com, growthstack.io, ..."
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none"
        />
        <button
          onClick={handleScan}
          disabled={scanning || !scanDomains.trim()}
          className="text-sm px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors whitespace-nowrap"
        >
          {scanning ? 'Scanning...' : 'Scan →'}
        </button>
      </div>
      {scanMsg && <p className="text-sm text-blue-400 mb-4">{scanMsg}</p>}

      {/* Filters */}
      <FilterBar
        minScore={minScore}
        status={status}
        onMinScoreChange={setMinScore}
        onStatusChange={setStatus}
        total={opps.length}
      />

      {/* Feed */}
      {isLoading && (
        <div className="text-center py-16 text-slate-500">Loading opportunities...</div>
      )}
      {error && (
        <div className="text-center py-16 text-red-400">
          Error loading data. Check your API key in Settings.
        </div>
      )}
      {!isLoading && opps.length === 0 && (
        <div className="text-center py-16 text-slate-500">
          <p className="text-lg mb-2">No opportunities yet.</p>
          <p className="text-sm">Enter company domains above and click Scan to get started.</p>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {opps.map(opp => (
          <OpportunityCard key={opp.id} opp={opp} onFeedback={() => mutate()} />
        ))}
      </div>
    </div>
  )
}
