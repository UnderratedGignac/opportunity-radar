export interface Signal {
  type: string
  detail: string
}

export interface ScoredSignal {
  signal: Signal
  base_weight: number
  recency_multiplier: number
  weighted_score: number
}

export interface OutreachPackage {
  email_subject: string
  email_body: string
  linkedin_message: string
  call_opener: string
}

export interface Opportunity {
  id: string
  company_name: string
  company_domain: string
  opportunity_score: number
  confidence_score: number
  signals: ScoredSignal[]
  likely_needs: string[]
  decision_maker_titles: string[]
  timing_rationale: string
  score_breakdown: Array<{ signal: string; contribution: number }>
  status: 'new' | 'viewed' | 'pursued' | 'converted' | 'not_relevant'
  created_at: string
  outreach_packages?: OutreachPackage[]
  companies?: {
    name: string
    domain: string
    industry?: string
    employee_count?: number
    tech_stack?: string[]
  }
}

export interface FeedbackPayload {
  action: 'pursued' | 'not_relevant' | 'demo_booked' | 'converted'
  deal_size_usd?: number
  notes?: string
}

export type Plan = 'pilot' | 'growth' | 'scale'

export interface Customer {
  id: string
  agency_name: string
  owner_name: string
  email: string
  plan: Plan
  agency_specialty?: string
  target_verticals?: string[]
  slack_webhook_url?: string
  status: 'active' | 'churned' | 'paused'
}

export interface ScanStatus {
  id: string
  domains: string[]
  status: 'running' | 'complete' | 'error'
  started_at: string
  completed_at: string | null
  found: number
  error: string | null
}
