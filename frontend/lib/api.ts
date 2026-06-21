import type { FeedbackPayload, Opportunity } from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function headers(): HeadersInit {
  const key = typeof window !== 'undefined' ? localStorage.getItem('radar_api_key') : ''
  return {
    'Content-Type': 'application/json',
    ...(key ? { 'X-API-Key': key } : {}),
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...init, headers: headers() })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  opportunities: {
    list: (params?: {
      min_score?: number
      status?: string
      limit?: number
      offset?: number
      signal_type?: string
    }) => {
      const q = new URLSearchParams()
      if (params?.min_score != null) q.set('min_score', String(params.min_score))
      if (params?.status) q.set('status', params.status)
      if (params?.limit) q.set('limit', String(params.limit))
      if (params?.offset) q.set('offset', String(params.offset))
      if (params?.signal_type) q.set('signal_type', params.signal_type)
      return req<{ data: Opportunity[]; count: number }>(`/opportunities?${q}`)
    },
    get: (id: string) => req<Opportunity>(`/opportunities/${id}`),
    setStatus: (id: string, status: string) =>
      req(`/opportunities/${id}/status?new_status=${status}`, { method: 'PATCH' }),
    feedback: (id: string, payload: FeedbackPayload) =>
      req(`/opportunities/${id}/feedback`, { method: 'POST', body: JSON.stringify(payload) }),
    exportUrl: (minScore = 60) => {
      const key = typeof window !== 'undefined' ? localStorage.getItem('radar_api_key') || '' : ''
      return `${BASE}/opportunities/export?min_score=${minScore}&key=${encodeURIComponent(key)}`
    },
    downloadCSV: async (minScore = 60) => {
      const key = typeof window !== 'undefined' ? localStorage.getItem('radar_api_key') || '' : ''
      const res = await fetch(`${BASE}/opportunities/export?min_score=${minScore}`, {
        headers: { 'X-API-Key': key },
      })
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'opportunities.csv'
      a.click()
      URL.revokeObjectURL(url)
    },
  },
  scan: {
    trigger: (domains: string[], minScore = 60) =>
      req<{ status: string; scan_id?: string; domains: string[]; message: string }>(
        '/scan',
        { method: 'POST', body: JSON.stringify({ domains, min_score: minScore }) }
      ),
    status: (scanId: string) =>
      req<{ id: string; status: string; found: number; error: string | null; completed_at: string | null }>(
        `/scan/status/${scanId}`
      ),
    bulk: (file: File, minScore = 20) => {
      const key = typeof window !== 'undefined' ? localStorage.getItem('radar_api_key') || '' : ''
      const form = new FormData()
      form.append('file', file)
      return fetch(`${BASE}/scan/bulk?min_score=${minScore}`, {
        method: 'POST',
        headers: { 'X-API-Key': key },
        body: form,
      }).then(r => r.json())
    },
  },
  customers: {
    me: () => req<{ agency_name: string; plan: string; email: string; slack_webhook_url?: string; agency_specialty?: string }>('/customers/me'),
    update: (data: { slack_webhook_url?: string; agency_specialty?: string }) =>
      req<{ ok: boolean }>('/customers/me', { method: 'PATCH', body: JSON.stringify(data) }),
    testSlack: (webhookUrl: string) =>
      req<{ ok: boolean }>('/customers/slack-test', { method: 'POST', body: JSON.stringify({ webhook_url: webhookUrl }) }),
  },
}
