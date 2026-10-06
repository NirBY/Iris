import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../lib/api'
import { dateTime } from '../lib/format'
import type { Job } from '../lib/types'

export function Jobs() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['jobs'], queryFn: () => api<Job[]>('/api/jobs') })
  const retry = useMutation({
    mutationFn: (id: number) => api(`/api/jobs/${id}/retry`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  })
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Jobs</h1>
      <p className="text-sm text-slate-500">Jobs that failed or ran out of attempts.</p>
      {retry.error && (
        <p role="alert" className="text-sm text-red-600">
          {retry.error instanceof ApiError ? retry.error.message : 'Retry failed'}
        </p>
      )}
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {data?.map((j) => (
          <li key={j.id} className="flex flex-col gap-1 p-3 text-sm">
            <span className="flex flex-wrap items-center gap-2">
              <strong>#{j.id}</strong>
              <span>{j.type}</span>
              <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800 dark:bg-red-900 dark:text-red-100">
                {j.status}
              </span>
              <span className="text-xs text-slate-500">
                attempt {j.attempts}/{j.max_attempts} · {dateTime(j.created_at)}
              </span>
              {j.message_id && (
                <Link to={`/messages/${j.message_id}`} className="text-xs underline">
                  message
                </Link>
              )}
            </span>
            {j.last_error && (
              <span className="text-xs text-red-600 dark:text-red-400">⚠ {j.last_error}</span>
            )}
            <button
              className="self-start rounded border px-2 py-1 text-xs"
              onClick={() => retry.mutate(j.id)}
            >
              Retry
            </button>
          </li>
        ))}
        {data?.length === 0 && <li className="p-3 text-sm text-slate-500">No failed jobs.</li>}
      </ul>
    </div>
  )
}
