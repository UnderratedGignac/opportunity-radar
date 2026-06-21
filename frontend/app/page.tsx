'use client'

import { useState, useCallback } from 'react'
import useSWR from 'swr'
import { OpportunityCard } from '../components/OpportunityCard'
import { FilterBar } from '../components/FilterBar'
import { api } from '../lib/api'
import type { Opportunity } from '../lib/types'

const fetcher = ([, params]: [string, Parameters<typeof api.opportunities.list>[0]]) =>
  api.opportunities.list(params)

const SIGNAL_TYPES = [
  { value: '', label: 'All signals' },
  { value: 'funding', label: 'Funding' },
  { value: 'hiring', label: 'Hiring' },
  { value: 'exec_change', label: 'Exec change' },
  { value: 'tech_change', label: 'Tech change' },
  { value: 'website_change', label: 'Website change' },
  { value: 'news', label: 'News' },
]

export default function FeedPage() {
  const [minScore, setMinScore] = useState(60)
  const [status, setStatus] = useState('')
  const [signalFilter, setSignalFilter] = useState('')
  const [scanDomains, setScanDomains] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [exporting, setExporting] = useState(false)

  const { data, error, isLoading, mutate } = useSWR(
    ['opportunities', { min_score: minScore, status: status || undefined, limit: 50 }],
    fetcher,
    { refreshInterval: 30_000 }
  )

  const allOpps: Opportunity[] = data?.data ?? []

  const opps = allOpps
    .filter(o => !dismissed.has(o.id))
    .filter(o => {
      if (!signalFilter) return true
      return (o.signals || []).some(
        s => (s.signal?.type || (s as any).type) === signalFilter
      )
    })

  const handleScan = async () => {
    const domains = scanDomains
      .split(/[\n,\s]+/)
      .map(d => d.trim().toLowerCase())
      .filter(Boolean)
    if (!domains.length) return
    setScanning(true)
    setScanMsg('')
    try {
      const res = await api.scan.trigger(domains, minScore)
      if (res.scan_id) setScanId(res.scan_id)
      setScanMsg(`Scanning ${domains.length} domain(s)... Results appear below in 2–5 minutes.`)
      // Poll scan status
      if (res.scan_id) {
        const sid = res.scan_id
        const poll = setInterval(async () => {
          try {
            const st = await api.scan.status(sid)
            if (st.status === 'complete') {
              clearInterval(poll)
              setScanMsg(`Scan complete — found ${st.found} opportunities.`)
              mutate()
              setTimeout(() => setScanMsg(''), 5000)
            } else if (st.status === 'error') {
              clearInterval(poll)
              setScanMsg(`Scan error: ${st.error}`)
            }
          } catch {}
        }, 5000)
        setTimeout(() => clearInterval(poll), 300_000)
      } else {
        setTimeout(() => { setScanMsg(''); mutate() }, 6000)
      }
    } catch (e: any) {
      setScanMsg(`Error: ${e.message}`)
    } finally {
      setScanning(false)
    }
  }

  const handleFeedback = useCallback((oppId: string, action: 'pursued' | 'not_relevant') => {
    api.opportunities.feedback(oppId, { action }).catch(() => {})
    setDismissed(prev => new Set([...prev, oppId]))
  }, [])

  const handleExport = async () => {
    setExporting(true)
    try {
      await api.opportunities.downloadCSV(minScore)
    } catch (e: any) {
      setScanMsg(`Export failed: ${e.message}`)
    } finally {
      setExporting(false)
    }
  }

  const scoreHighlights = allOpps.filter(o => o.opportunity_score >= 80).length

  return (
    <div>
      {/* Header KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {[
          { label: 'Total', value: data?.count ?? 0 },
          { label: 'Score 80+', value: scoreHighlights },
          { label: 'Pursued', value: allOpps.filter(o => o.status === 'pursued').length },
          { label: 'Converted', value: allOpps.filter(o => o.status === 'converted').length },
        ].map(kpi => (
          <div key={kpi.label} className="card p-4">
            <p className="text-2xl font-bold text-white">{kpi.value}</p>
            <p className="text-xs text-slate-500 mt-1">{kpi.label}</p>
          </div>
        ))}
      </div>

      {/* Scan trigger */}
      <div className="card p-4 mb-4">
        <div className="flex gap-3 items-start">
          <textarea
            value={scanDomains}
            onChange={e => setScanDomains(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleScan() }}
            rows={3}
            placeholder={"stripe.com\nhubspot.com\nsalesforce.com"}
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder-slate-600 outline-none resize-none leading-relaxed"
          />
          <div className="flex flex-col gap-2">
            <button
              onClick={handleScan}
              disabled={scanning || !scanDomains.trim()}
              className="text-sm px-4 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 transition-colors whitespace-nowrap"
            >
              {scanning ? 'Scanning…' : 'Scan →'}
            </button>
            <button
              onClick={handleExport}
              disabled={exporting}
              className="text-sm px-4 py-1.5 rounded border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 disabled:opacity-40 transition-colors whitespace-nowrap"
            >
              {exporting ? 'Exporting…' : '↓ CSV'}
            </button>
          </div>
        </div>
        <p className="text-xs text-slate-600 mt-2">One domain per line, or comma-separated. Ctrl+Enter to scan.</p>
      </div>
      {scanMsg && (
        <p className={`text-sm mb-4 ${scanMsg.startsWith('Error') ? 'text-red-400' : 'text-blue-400'}`}>
          {scanMsg}
        </p>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6 items-center">
        <FilterBar
          minScore={minScore}
          status={status}
          onMinScoreChange={setMinScore}
          onStatusChange={setStatus}
          total={opps.length}
        />
        <select
          value={signalFilter}
          onChange={e => setSignalFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 text-slate-300 text-sm rounded px-3 py-1.5 outline-none focus:border-blue-500"
        >
          {SIGNAL_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {dismissed.size > 0 && (
          <button
            onClick={() => setDismissed(new Set())}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            Restore {dismissed.size} dismissed
          </button>
        )}
      </div>

      {/* Feed */}
      {isLoading && (
        <div className="text-center py-16 text-slate-500">Loading opportunities…</div>
      )}
      {error && (
        <div className="text-center py-16 text-red-400">
          Error loading data. Check your API key in Settings.
        </div>
      )}
      {!isLoading && opps.length === 0 && !error && (
        <div className="text-center py-16 text-slate-500">
          <p className="text-lg mb-2">No opportunities yet.</p>
          <p className="text-sm">Enter company domains above and click Scan to get started.</p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {opps.map(opp => (
          <div key={opp.id} className="relative group">
            <OpportunityCard opp={opp} onFeedback={() => mutate()} />
            {/* Quick action buttons */}
            <div className="flex gap-2 mt-1 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={() => handleFeedback(opp.id, 'pursued')}
                className="text-xs px-3 py-1 rounded border border-blue-500/30 text-blue-400 hover:bg-blue-500/10 transition-colors"
              >
                ✓ Pursue
              </button>
              <button
                onClick={() => handleFeedback(opp.id, 'not_relevant')}
                className="text-xs px-3 py-1 rounded border border-slate-600/50 text-slate-500 hover:bg-slate-700/30 transition-colors"
              >
                ✕ Not relevant
              </button>
              <a
                href={`/opportunities/${opp.id}`}
                className="text-xs px-3 py-1 rounded border border-slate-700 text-slate-500 hover:text-slate-300 transition-colors ml-auto"
              >
                Details →
              </a>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
