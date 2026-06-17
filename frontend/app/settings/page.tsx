'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import { api } from '../../lib/api'

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('')
  const [saved, setSaved] = useState(false)
  const [slack, setSlack] = useState('')
  const [specialty, setSpecialty] = useState('')

  const { data: customer } = useSWR(
    typeof window !== 'undefined' && localStorage.getItem('radar_api_key') ? 'me' : null,
    api.customers.me,
  )

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setApiKey(localStorage.getItem('radar_api_key') || '')
    }
  }, [])

  const saveApiKey = () => {
    localStorage.setItem('radar_api_key', apiKey)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
    window.location.reload()
  }

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
            {saved ? '✓ Saved' : 'Save'}
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2">
          Your API key is stored locally in your browser. Get yours from the onboarding email.
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

      {/* Notifications */}
      <section className="card p-6">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">Notifications</h2>
        <div className="space-y-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Slack Webhook URL</label>
            <input
              value={slack}
              onChange={e => setSlack(e.target.value)}
              placeholder="https://hooks.slack.com/services/..."
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 outline-none focus:border-blue-500 transition-colors"
            />
            <p className="text-xs text-slate-600 mt-1">Real-time alerts for opportunities scoring 80+</p>
          </div>
        </div>
      </section>
    </div>
  )
}
