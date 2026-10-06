import type { Message } from '../lib/types'

export function MessageBody({ m }: { m: Message }) {
  if (m.redacted)
    return <em className="text-slate-500">Content withheld (redacted), metadata only.</em>
  const body = m.text || m.transcript
  if (!body) return <em className="text-slate-500">[{m.type}]</em>
  return (
    <span dir="auto">
      {m.transcript && !m.text ? '🎤 ' : ''}
      {body}
    </span>
  )
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  const color =
    verdict === 'harmful'
      ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100'
      : verdict === 'review'
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100'
        : verdict === 'safe'
          ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100'
          : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
  return <span className={`rounded px-2 py-0.5 text-xs ${color}`}>{verdict ?? 'pending'}</span>
}
