import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CategoryChips } from '../components/Scores'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { AlertPage, Stats } from '../lib/types'

const REFRESH_MS = 60_000

function Card({ label, value, to }: { label: string; value: number | string; to?: string }) {
  const body = (
    <>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      <span className="text-xs text-slate-500">{label}</span>
    </>
  )
  const cls = 'flex flex-col gap-1 rounded border border-slate-200 p-3 dark:border-slate-800'
  return to ? (
    <Link to={to} className={`${cls} hover:bg-slate-50 dark:hover:bg-slate-900`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

function Banner({ children }: { children: React.ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
    >
      {children}
    </p>
  )
}

export function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('/api/stats'),
    refetchInterval: REFRESH_MS,
  })
  const { data: alerts } = useQuery({
    queryKey: ['alerts', 'recent'],
    queryFn: () => api<AlertPage>('/api/alerts?page_size=5'),
    refetchInterval: REFRESH_MS,
  })
  if (!stats) return null
  const open = stats.alerts_by_status['new'] ?? 0
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      {!stats.delivery_configured && (
        <Banner>
          Alert delivery is not configured: alerts are recorded but not sent.{' '}
          <Link to="/settings" className="underline">
            Set up delivery
          </Link>
          .
        </Banner>
      )}
      {stats.failed_jobs > 0 && (
        <Banner>
          {stats.failed_jobs} job{stats.failed_jobs === 1 ? '' : 's'} failed.{' '}
          <Link to="/jobs" className="underline">
            See why and retry
          </Link>
          .
        </Banner>
      )}
      {stats.silent_instances > 0 && (
        <Banner>
          {stats.silent_instances} instance{stats.silent_instances === 1 ? ' has' : 's have'} never
          received a webhook.{' '}
          <Link to="/instances" className="underline">
            Check the webhook setup
          </Link>
          .
        </Banner>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label="Messages today" value={stats.messages_today} to="/messages" />
        <Card label="Messages, 7 days" value={stats.messages_7d} to="/messages" />
        <Card label="New alerts" value={open} to="/alerts" />
        <Card label="To review" value={stats.review_queue} to="/review" />
        <Card label="Jobs in queue" value={stats.queue_depth} />
        <Card label="Failed jobs" value={stats.failed_jobs} to="/jobs" />
        <Card label="Instances" value={stats.instances} to="/instances" />
        <Card
          label="Alerts failed to send"
          value={stats.alerts_by_delivery['failed'] ?? 0}
          to="/alerts"
        />
      </div>
      <section className="flex flex-col gap-2">
        <h2 className="font-medium">Recent alerts</h2>
        <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {alerts?.items.map((a) => (
            <li key={a.id}>
              <Link
                to={`/alerts/${a.id}`}
                className="flex flex-wrap items-center gap-2 p-3 text-sm hover:bg-slate-50 dark:hover:bg-slate-900"
              >
                <span className="text-xs text-slate-500">{dateTime(a.created_at)}</span>
                <span>{a.kid_names.join(', ')}</span>
                <CategoryChips categories={a.categories} score={a.max_score} />
              </Link>
            </li>
          ))}
          {alerts && alerts.items.length === 0 && (
            <li className="p-3 text-sm text-slate-500">No alerts yet.</li>
          )}
        </ul>
      </section>
    </div>
  )
}
