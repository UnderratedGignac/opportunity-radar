'use client'

interface Props {
  minScore: number
  status: string
  onMinScoreChange: (v: number) => void
  onStatusChange: (v: string) => void
  total: number
}

const STATUSES = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'pursued', label: 'Pursued' },
  { value: 'converted', label: 'Converted' },
  { value: 'not_relevant', label: 'Not relevant' },
]

export function FilterBar({ minScore, status, onMinScoreChange, onStatusChange, total }: Props) {
  return (
    <div className="flex items-center gap-4 flex-wrap mb-6">
      <span className="text-sm text-slate-500">{total} opportunities</span>

      <div className="flex items-center gap-2">
        <label className="text-xs text-slate-500 whitespace-nowrap">Min score</label>
        <input
          type="range" min={0} max={100} step={5} value={minScore}
          onChange={e => onMinScoreChange(Number(e.target.value))}
          className="w-28 accent-blue-500"
        />
        <span className="text-xs text-slate-300 w-8">{minScore}</span>
      </div>

      <div className="flex items-center gap-1">
        {STATUSES.map(s => (
          <button key={s.value}
            onClick={() => onStatusChange(s.value)}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
              status === s.value
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-300'
                : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600'
            }`}>
            {s.label}
          </button>
        ))}
      </div>
    </div>
  )
}
