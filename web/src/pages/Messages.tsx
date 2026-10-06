import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Highlight } from '../components/Highlight'
import { Failure, MessageBody, VerdictBadge } from '../components/MessageBody'
import { typeIcon } from '../lib/icons'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { Instance, MessagePage } from '../lib/types'

const TYPES = ['text', 'image', 'audio', 'voice', 'video', 'sticker', 'document', 'other']
const VERDICTS = ['safe', 'harmful', 'review', 'none']

export function Messages() {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [filters, setFilters] = useState({
    instance_id: '',
    type: '',
    verdict: '',
    sender: '',
    from: '',
    to: '',
  })
  const [page, setPage] = useState(1)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(t)
  }, [q])

  const params = new URLSearchParams({ page: String(page), page_size: '25' })
  if (debouncedQ) params.set('q', debouncedQ)
  for (const [k, v] of Object.entries(filters)) {
    if (!v) continue
    params.set(k, k === 'from' || k === 'to' ? new Date(v).toISOString() : v)
  }

  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const { data, isFetching, error } = useQuery({
    queryKey: ['messages', params.toString()],
    queryFn: () => api<MessagePage>(`/api/messages?${params}`),
  })

  const set = (k: keyof typeof filters) => (v: string) => {
    setFilters((f) => ({ ...f, [k]: v }))
    setPage(1)
  }
  const input =
    'rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Messages</h1>
      <div className="flex flex-wrap gap-2">
        <input
          className={`${input} min-w-48 flex-1`}
          dir="auto"
          placeholder="Search text and transcripts…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setPage(1)
          }}
        />
        <select
          className={input}
          aria-label="Kid"
          value={filters.instance_id}
          onChange={(e) => set('instance_id')(e.target.value)}
        >
          <option value="">All kids</option>
          {instances?.map((i) => (
            <option key={i.id} value={i.id}>
              {i.kid_name}
            </option>
          ))}
        </select>
        <select
          className={input}
          aria-label="Type"
          value={filters.type}
          onChange={(e) => set('type')(e.target.value)}
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        <select
          className={input}
          aria-label="Verdict"
          value={filters.verdict}
          onChange={(e) => set('verdict')(e.target.value)}
        >
          <option value="">Any verdict</option>
          {VERDICTS.map((v) => (
            <option key={v} value={v}>
              {v === 'none' ? 'pending' : v}
            </option>
          ))}
        </select>
        <input
          className={input}
          dir="auto"
          placeholder="Sender"
          value={filters.sender}
          onChange={(e) => set('sender')(e.target.value)}
        />
        <input
          className={input}
          type="datetime-local"
          aria-label="From"
          value={filters.from}
          onChange={(e) => set('from')(e.target.value)}
        />
        <input
          className={input}
          type="datetime-local"
          aria-label="To"
          value={filters.to}
          onChange={(e) => set('to')(e.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {String(error.message)}
        </p>
      )}
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {data?.items.map((m) => (
          <li key={m.id}>
            <Link
              to={`/messages/${m.id}`}
              className="flex flex-col gap-1 p-3 hover:bg-slate-50 dark:hover:bg-slate-900"
            >
              <span className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{typeIcon(m.type)}</span>
                <span>{dateTime(m.sent_at)}</span>
                <span>{m.kids.map((k) => k.kid_name).join(', ')}</span>
                <span>· {m.chat_name ?? (m.is_group ? 'group' : 'chat')}</span>
                <span>
                  · {m.sender_name ?? '?'}
                  {m.from_me ? ' (kid)' : ''}
                </span>
                <VerdictBadge m={m} />
              </span>
              <span className="text-sm">
                {m.snippet ? <Highlight snippet={m.snippet} /> : <MessageBody m={m} />}
              </span>
              <Failure m={m} />
            </Link>
          </li>
        ))}
        {data && data.items.length === 0 && (
          <li className="p-4 text-sm text-slate-500">No messages.</li>
        )}
      </ul>
      <div className="flex items-center gap-3 text-sm">
        <button
          className="rounded border px-2 py-1 disabled:opacity-40"
          disabled={page <= 1}
          onClick={() => setPage(page - 1)}
        >
          Prev
        </button>
        <span>
          Page {page} of {pages} ({data?.total ?? 0} messages){isFetching ? ' …' : ''}
        </span>
        <button
          className="rounded border px-2 py-1 disabled:opacity-40"
          disabled={page >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
