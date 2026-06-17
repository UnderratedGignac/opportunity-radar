import clsx from 'clsx'

interface Props { score: number; size?: 'sm' | 'md' | 'lg' }

export function ScoreBadge({ score, size = 'md' }: Props) {
  const color =
    score >= 80 ? 'bg-green-500/20 text-green-400 border-green-500/30' :
    score >= 65 ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                  'bg-slate-700/40 text-slate-400 border-slate-600/30'

  const sizeClass =
    size === 'sm' ? 'text-xs px-2 py-0.5' :
    size === 'lg' ? 'text-2xl px-4 py-2 font-bold' :
                    'text-sm px-3 py-1 font-semibold'

  return (
    <span className={clsx('rounded-full border inline-block', color, sizeClass)}>
      {score}
    </span>
  )
}
