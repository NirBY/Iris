import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MessageBody } from '../components/MessageBody'
import { Scores } from '../components/Scores'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { ReviewPage } from '../lib/types'

export function Review() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['review'], queryFn: () => api<ReviewPage>('/api/review') })
  const resolve = useMutation({
    mutationFn: (v: { id: number; resolution: 'safe' | 'harmful' }) =>
      api(`/api/review/${v.id}`, {
        method: 'POST',
        body: JSON.stringify({ resolution: v.resolution }),
      }),
    onSuccess: () => qc.invalidateQueries(),
  })
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Review queue</h1>
      <p className="text-sm text-slate-500">
        Messages Iris could not decide, even with the surrounding chat.
      </p>
      {data?.items.length === 0 && <p className="text-sm text-slate-500">Nothing to review.</p>}
      {data?.items.map(({ message: m, classifications }) => (
        <article
          key={m.id}
          className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-800"
        >
          <p className="text-xs text-slate-500">
            {dateTime(m.sent_at)} · {m.kids.map((k) => k.kid_name).join(', ')} ·{' '}
            {m.chat_name ?? 'chat'} · {m.sender_name ?? '?'}
          </p>
          <p className="text-sm">
            <MessageBody m={m} />
          </p>
          {classifications.slice(-1).map((c) => (
            <div key={c.id}>
              <Scores scores={c.scores} min={0.05} />
            </div>
          ))}
          <div className="flex flex-wrap gap-2 text-sm">
            <button
              className="rounded border px-2 py-1"
              onClick={() => resolve.mutate({ id: m.id, resolution: 'safe' })}
            >
              Mark safe
            </button>
            <button
              className="rounded border border-red-300 px-2 py-1 text-red-700"
              onClick={() => resolve.mutate({ id: m.id, resolution: 'harmful' })}
            >
              Mark harmful
            </button>
            <Link to={`/messages/${m.id}`} className="self-center underline">
              In context
            </Link>
          </div>
        </article>
      ))}
    </div>
  )
}
