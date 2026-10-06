import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { CategoryChips, Scores } from '../components/Scores'
import { api, ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import type { AlertDetail as Detail } from '../lib/types'

export function AlertDetail() {
  const { id } = useParams()
  const qc = useQueryClient()
  const { data: a } = useQuery({
    queryKey: ['alert', id],
    queryFn: () => api<Detail>(`/api/alerts/${id}`),
  })
  const refresh = () => qc.invalidateQueries()
  const patch = useMutation({
    mutationFn: (status: string) =>
      api(`/api/alerts/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
    onSuccess: refresh,
  })
  const resend = useMutation({
    mutationFn: () => api(`/api/alerts/${id}/resend`, { method: 'POST' }),
    onSuccess: refresh,
  })
  if (!a) return null
  const err = resend.error instanceof ApiError ? resend.error.message : null
  const btn = 'rounded border px-2 py-1 text-sm disabled:opacity-40'

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <Link to="/alerts" className="text-sm underline">
        ← Alerts
      </Link>
      <h1 className="text-xl font-semibold">Alert #{a.id}</h1>
      <p className="text-sm text-slate-500">
        {dateTime(a.sent_at)} · {a.kid_names.join(', ')} · {a.chat_name ?? 'chat'} ·{' '}
        {a.sender_name ?? '?'}
      </p>
      <CategoryChips categories={a.categories} score={a.max_score} />
      {a.redacted ? (
        <p className="rounded border border-slate-300 p-3 text-sm dark:border-slate-700">
          Content withheld (sexual content). Review the chat directly in WhatsApp.
        </p>
      ) : (
        <blockquote
          className="rounded border-l-4 border-red-400 bg-slate-50 p-3 text-sm dark:bg-slate-900"
          dir="auto"
        >
          {a.quote}
        </blockquote>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm">
          Status: <strong>{a.status}</strong>
        </span>
        <button
          className={btn}
          disabled={a.status === 'acknowledged'}
          onClick={() => patch.mutate('acknowledged')}
        >
          Acknowledge
        </button>
        <button
          className={btn}
          disabled={a.status === 'dismissed'}
          onClick={() => patch.mutate('dismissed')}
        >
          Dismiss
        </button>
        {a.status !== 'new' && (
          <button className={btn} onClick={() => patch.mutate('new')}>
            Reopen
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          Delivery: <strong>{a.delivery_status}</strong>
          {a.notified_at ? ` (${dateTime(a.notified_at)})` : ''}
        </span>
        {a.delivery_error && <span className="text-red-600">⚠ {a.delivery_error}</span>}
        <button className={btn} onClick={() => resend.mutate()} disabled={resend.isPending}>
          Resend
        </button>
        {err && (
          <span role="alert" className="text-red-600">
            {err}
          </span>
        )}
      </div>
      <Link to={`/messages/${a.message_id}`} className="text-sm underline">
        View in chat context
      </Link>
      <section className="flex flex-col gap-3">
        <h2 className="font-medium">Classification</h2>
        {a.classifications.map((c) => (
          <div key={c.id} className="rounded border border-slate-200 p-3 dark:border-slate-800">
            <p className="mb-2 text-sm">
              <strong>{c.stage}</strong> · {c.band} · {c.input_kind} · {c.model}
            </p>
            <Scores scores={c.scores} />
          </div>
        ))}
      </section>
    </div>
  )
}
