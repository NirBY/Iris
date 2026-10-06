import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CategoryChips } from '../components/Scores'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { AlertPage, Instance } from '../lib/types'

const STATUSES = ['new', 'acknowledged', 'dismissed']
const input =
  'rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

export function Alerts() {
  const [filters, setFilters] = useState({ status: '', instance_id: '', category: '' })
  const [page, setPage] = useState(1)
  const params = new URLSearchParams({ page: String(page), page_size: '25' })
  for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v)

  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const { data } = useQuery({
    queryKey: ['alerts', params.toString()],
    queryFn: () => api<AlertPage>(`/api/alerts?${params}`),
  })
  const notConfigured = data?.items.some(
    (a) => a.delivery_error === 'alert delivery not configured',
  )
  const set = (k: keyof typeof filters) => (v: string) => {
    setFilters((f) => ({ ...f, [k]: v }))
    setPage(1)
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Alerts</h1>
      {notConfigured && (
        <p
          role="alert"
          className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
        >
          Alert delivery is not configured, so alerts are recorded here but not sent.{' '}
          <Link to="/settings" className="underline">
            Set up the sender and recipient
          </Link>
          .
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <select
          className={input}
          aria-label="Status"
          value={filters.status}
          onChange={(e) => set('status')(e.target.value)}
        >
          <option value="">Any status</option>
          {STATUSES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
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
        <input
          className={input}
          placeholder="Category (e.g. violence)"
          value={filters.category}
          onChange={(e) => set('category')(e.target.value)}
        />
      </div>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {data?.items.map((a) => (
          <li key={a.id}>
            <Link
              to={`/alerts/${a.id}`}
              className="flex flex-col gap-1 p-3 hover:bg-slate-50 dark:hover:bg-slate-900"
            >
              <span className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>{dateTime(a.created_at)}</span>
                <span>{a.kid_names.join(', ')}</span>
                <span>· {a.chat_name ?? 'chat'}</span>
                <span>· {a.sender_name ?? '?'}</span>
                <CategoryChips categories={a.categories} score={a.max_score} />
                <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-slate-800">
                  {a.status}
                </span>
                <span
                  className={`rounded px-2 py-0.5 ${a.delivery_status === 'failed' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100' : 'bg-slate-100 dark:bg-slate-800'}`}
                  title={a.delivery_error ?? undefined}
                >
                  {a.delivery_status}
                </span>
              </span>
              <span className="text-sm" dir="auto">
                {a.redacted ? (
                  <em className="text-slate-500">Content withheld (sexual content)</em>
                ) : (
                  (a.quote ?? '')
                )}
              </span>
            </Link>
          </li>
        ))}
        {data && data.items.length === 0 && (
          <li className="p-4 text-sm text-slate-500">No alerts.</li>
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
          Page {page} of {pages} ({data?.total ?? 0} alerts)
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
