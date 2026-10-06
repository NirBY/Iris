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

const BADGE: Record<string, string> = {
  harmful: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100',
  review: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100',
  safe: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100',
}

/** The verdict when there is one, otherwise the processing status (failed, skipped, pending...). */
export function VerdictBadge({ m }: { m: Pick<Message, 'verdict' | 'status' | 'failure'> }) {
  const label = m.verdict ?? m.status
  const color = BADGE[label] ?? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${color}`} title={m.failure ?? undefined}>
      {label}
    </span>
  )
}

export function Failure({ m }: { m: Pick<Message, 'failure'> }) {
  if (!m.failure) return null
  return <span className="text-xs text-red-600 dark:text-red-400">⚠ {m.failure}</span>
}
