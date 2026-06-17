import clsx from 'clsx'

const TYPE_STYLES: Record<string, string> = {
  funding:        'bg-blue-500/15 text-blue-300 border-blue-500/25',
  exec_change:    'bg-purple-500/15 text-purple-300 border-purple-500/25',
  hiring:         'bg-green-500/15 text-green-300 border-green-500/25',
  tech_change:    'bg-orange-500/15 text-orange-300 border-orange-500/25',
  website_change: 'bg-teal-500/15 text-teal-300 border-teal-500/25',
  news:           'bg-slate-600/30 text-slate-300 border-slate-600/30',
}

const TYPE_LABELS: Record<string, string> = {
  funding: 'Funding', exec_change: 'Exec Change',
  hiring: 'Hiring', tech_change: 'Tech', website_change: 'Website', news: 'News',
}

interface Props { type: string; detail: string }

export function SignalChip({ type, detail }: Props) {
  return (
    <div className={clsx('flex items-start gap-2 rounded-md border px-2.5 py-1.5', TYPE_STYLES[type] ?? TYPE_STYLES.news)}>
      <span className="text-xs font-semibold mt-0.5 shrink-0 uppercase tracking-wide opacity-70">
        {TYPE_LABELS[type] ?? type}
      </span>
      <span className="text-xs leading-snug">{detail}</span>
    </div>
  )
}
