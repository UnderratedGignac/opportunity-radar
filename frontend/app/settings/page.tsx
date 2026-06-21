'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import { api } from '../../lib/api'

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('')
  const [keySaved, setKeySaved] = useState(false)
  const [slack, setSlack] = useState('')
  const [slackStatus, setSlackStatus] = useState<'idle' | 'saving' | 'saved' | 'testing' | 'ok' | 'fail'>('idle')
  const [specialty, setSpecialty] = useState('')
  const [specialtySaved, setSpecialtySaved] = useState(false)

  const { data: customer } = useSWR(
    typeof window !== 'undefined' && localStorage.getItem('radar_api_key') ? 'me' : null,
    api.customers.me,
  )

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setApiKey(localStorage.getItem('radar_api_key') || '')
    }
  }, [])

  useEffect(() => {
    if (customer) {
      if ((customer as any).slack_webhook_url) setSlack((customer as any).slack_webhook_url)
      if ((customer as any).agency_specialty) setSpecialty((customer as any).agency_specialty)
    }
  }, [customer])

  const saveApiKey = () => {
    localStorage.setItem('radar_api_key', apiKey)
    setKeySaved(true)
    setTimeout(() => { setKeySaved(false); window.location.reload() }, 1500)
  }

  const saveSlack = async () => {
    setSlackStatus('saving')
    try {
      await api.customers.update({ slack_webhook_url: slack })
      setSlackStatus('saved')
      setTimeout(() => setSlackStatus('idle'), 2000)
    } catch {
      setSlackStatus('fail')
      setTimeout(() => setSlackStatus('idle'), 2000)
    }
  }

  const testSlack = async () => {
    setSlackStatus('testing')
    try {
      const res = await api.customers.testSlack(slack)
      setSlackStatus(res.ok ? 'ok' : 'fail')
      setTimeout(() => setSlackStatus('idle'), 3000)
    } catch {
      setSlackStatus('fail')
      setTimeout(() => setSlackStatus('idle'), 3000)
    }
  }

  const saveSpecialty = async () => {
    try {
      await api.customers.update({ agency_specialty: specialty })
      setSpecialtySaved(true)
      setTimeout(() => setSpecialtySaved(false), 2000)
    } catch {}
  }

  const slackLabel = {
    idle: 'Save', saving: 'Saving…', saved: '✓ Saved', testing: 'Testing…', ok: '✓ Working!', fail: '✗ Failed',
  }[slackStatus]

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-xl font-bold text-white mb-6">Settings</h1>

      {/* API Key */}
      <section className="card p-6 mb-5">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">API Key</h2>
        <div className="flex gap-2">
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder="radar_..."
            className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors"
          />
          <button onClick={saveApiKey}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition-colors">
            {keySaved ? '✓ Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2">
          Stored in your browser. Get yours from the onboarding email or /customers/signup.
        </p>
      </section>

      {/* Account info */}
      {customer && (
        <section className="card p-6 mb-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Account</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-500">Agency</span>
              <span className="text-slate-200">{customer.agency_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Email</span>
              <span className="text-slate-200">{customer.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Plan</span>
              <span className="text-blue-400 capitalize font-medium">{customer.plan}</span>
            </div>
          </div>
        </section>
      )}

      {/* Agency specialty */}
      <section className="card p-6 mb-5">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Agency Specialty</h2>
        <div className="flex gap-2">
          <input
            value={specialty}
            onChange={e => setSpecialty(e.target.value)}
            placeholder="e.g. AI automation for B2B SaaS companies"
            className="flex-1 bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors"
          />
          <button onClick={saveSpecialty}
            className="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 transition-colors">
            {specialtySaved ? '✓ Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2">Used in AI-generated outreach copy.</p>
      </section>

      {/* Notifications */}
      <section className="card p-6">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Slack Notifications</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Webhook URL</label>
            <input
              value={slack}
              onChange={e => setSlack(e.target.value)}
              placeholder="https://hooks.slack.com/services/..."
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors"
            />
            <p className="text-xs text-slate-600 mt-1">Alerts for opportunities scoring 80+.</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={saveSlack}
              disabled={!slack || slackStatus === 'saving'}
              className="px-4 py-2 bg-slate-700 text-white text-sm rounded hover:bg-slate-600 disabled:opacity-40 transition-colors"
            >
              {slackLabel}
            </button>
            <button
              onClick={testSlack}
              disabled={!slack || slackStatus === 'testing'}
              className="px-4 py-2 border border-slate-700 text-slate-400 text-sm rounded hover:border-slate-500 hover:text-slate-200 disabled:opacity-40 transition-colors"
            >
              Send Test
            </button>
            {(slackStatus === 'ok' || slackStatus === 'fail') && (
              <span className={`text-sm self-center ${slackStatus === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
                {slackStatus === 'ok' ? '✓ Webhook working!' : '✗ Webhook failed'}
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
