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
    list: (params?: { min_score?: number; status?: string; limit?: number; offset?: number }) => {
      const q = new URLSearchParams()
      if (params?.min_score != null) q.set('min_score', String(params.min_score))
      if (params?.status) q.set('status', params.status)
      if (params?.limit) q.set('limit', String(params.limit))
      if (params?.offset) q.set('offset', String(params.offset))
      return req<{ data: Opportunity[]; count: number }>(`/opportunities?${q}`)
    },
    get: (id: string) => req<Opportunity>(`/opportunities/${id}`),
    setStatus: (id: string, status: string) =>
      req(`/opportunities/${id}/status?new_status=${status}`, { method: 'PATCH' }),
    feedback: (id: string, payload: FeedbackPayload) =>
      req(`/opportunities/${id}/feedback`, { method: 'POST', body: JSON.stringify(payload) }),
  },
  scan: {
    trigger: (domains: string[], minScore = 60) =>
      req('/scan', { method: 'POST', body: JSON.stringify({ domains, min_score: minScore }) }),
  },
  customers: {
    me: () => req<{ agency_name: string; plan: string; email: string }>('/customers/me'),
  },
}
