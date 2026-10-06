import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Failure, MessageBody, VerdictBadge } from '../components/MessageBody'
import { typeIcon } from '../lib/icons'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { Message, MessageDetail } from '../lib/types'

export function MessageContext() {
  const { id } = useParams()
  const { data: detail } = useQuery({
    queryKey: ['message', id],
    queryFn: () => api<MessageDetail>(`/api/messages/${id}`),
  })
  const qc = useQueryClient()
  const reprocess = useMutation({
    mutationFn: () => api(`/api/messages/${id}/reprocess`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const { data: context } = useQuery({
    queryKey: ['message-context', id],
    queryFn: () => api<Message[]>(`/api/messages/${id}/context`),
  })

  return (
    <div className="flex flex-col gap-4">
      <Link to="/messages" className="text-sm underline">
        ← Messages
      </Link>
      {detail && (
        <p className="text-sm text-slate-500">
          {detail.chat_name ?? (detail.is_group ? 'Group' : 'Chat')} ·{' '}
          {detail.kids.map((k) => k.kid_name).join(', ')}
        </p>
      )}
      <ol className="flex max-w-2xl flex-col gap-2">
        {context?.map((m) => (
          <li
            key={m.id}
            id={`m${m.id}`}
            className={`flex flex-col gap-1 rounded-lg p-3 ${m.from_me ? 'self-end bg-indigo-50 dark:bg-indigo-950' : 'self-start bg-slate-100 dark:bg-slate-900'} ${String(m.id) === id ? 'ring-2 ring-indigo-500' : ''}`}
          >
            <span className="text-xs text-slate-500">
              {typeIcon(m.type)} {m.sender_name ?? '?'} · {dateTime(m.sent_at)}
            </span>
            <span className="text-sm">
              <MessageBody m={m} />
            </span>
            <span className="flex flex-wrap items-center gap-2">
              <VerdictBadge m={m} />
              <Failure m={m} />
            </span>
          </li>
        ))}
      </ol>
      {detail && !detail.redacted && (
        <button
          className="self-start rounded border px-2 py-1 text-sm"
          onClick={() => reprocess.mutate()}
          disabled={reprocess.isPending}
        >
          Reprocess
        </button>
      )}
      {reprocess.error && (
        <p role="alert" className="text-sm text-red-600">
          {String(reprocess.error.message)}
        </p>
      )}
      {detail && (
        <section className="max-w-2xl">
          <h2 className="mb-2 font-medium">Classifications</h2>
          {detail.classifications.length === 0 ? (
            <p className="text-sm text-slate-500">Not classified yet.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {detail.classifications.map((c) => (
                <li
                  key={c.id}
                  className="rounded border border-slate-200 p-2 dark:border-slate-800"
                >
                  <strong>{c.stage}</strong> · {c.band} · {c.model}
                  {c.flagged_categories.length > 0 && ` · ${c.flagged_categories.join(', ')}`}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  )
}
