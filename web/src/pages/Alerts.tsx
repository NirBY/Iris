import { useMe } from '../lib/auth'
import { useQuery } from '@tanstack/react-query'
import { BellRing, Settings } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AlertRow } from '../components/AlertRow'
import { EmptyState } from '../components/EmptyState'
import { Chips, FilterBar } from '../components/FilterBar'
import { PageHeader } from '../components/PageHeader'
import { RevealButton } from '../components/Reveal'
import { useReveal } from '../lib/useReveal'
import { Pagination } from '../components/Pagination'
import { Button } from '../components/ui/button'
import { Field, Select } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { CATEGORIES } from '../lib/categories'
import { useUrlState } from '../lib/urlState'
import type { AlertPage, Instance, Stats } from '../lib/types'

const STATUS = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'acknowledged', label: 'Seen' },
  { value: 'dismissed', label: 'Dismissed' },
]
const PAGE_SIZE = 25

export function Alerts() {
  const { data: me } = useMe()
  const { revealed, toggle } = useReveal()
  const { get, page, update, clear } = useUrlState()
  const status = get('status')
  const kid = get('instance_id')
  const category = get('category')
  const chatId = get('chat_id')

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  for (const [k, v] of [
    ['status', status],
    ['instance_id', kid],
    ['category', category],
    ['chat_id', chatId],
  ])
    if (v) params.set(k, v)

  const { data: instances } = useQuery({
    queryKey: ['auth-phones'],
    queryFn: () => api<Instance[]>('/api/auth/phones'),
  })
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['alerts', params.toString()],
    queryFn: () => api<AlertPage>(`/api/alerts?${params}`),
  })
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('/api/stats'),
  })
  const notConfigured = stats?.delivery_configured === false
  const active = [kid, category, chatId].filter(Boolean).length + (status ? 1 : 0)

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Alerts"
        description="Messages Iris judged harmful, newest first."
        actions={<RevealButton revealed={revealed} onToggle={toggle} />}
      />

      {notConfigured && (
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-warning-soft p-3 text-sm text-warning"
        >
          Alert delivery is not set up, so alerts are saved here but not sent to your WhatsApp.
          {me?.role === 'admin' && (
            <Button asChild variant="link" size="sm" className="h-auto min-h-0 p-0">
              <Link to="/settings?tab=Alerts">
                <Settings /> Set up delivery
              </Link>
            </Button>
          )}
        </p>
      )}

      <FilterBar
        active={active}
        onClear={clear}
        leading={
          <Chips
            label="Status"
            value={status}
            options={STATUS}
            onChange={(v) => update({ status: v })}
          />
        }
      >
        <Field label="Phone" className="md:w-44">
          <Select value={kid} onChange={(e) => update({ instance_id: e.target.value })}>
            <option value="">All phones</option>
            {instances?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.kid_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Category" className="md:w-52">
          <Select value={category} onChange={(e) => update({ category: e.target.value })}>
            <option value="">Any category</option>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </Select>
        </Field>
      </FilterBar>

      <ul className="divide-y overflow-hidden rounded-lg border bg-surface" aria-busy={isLoading}>
        {isLoading &&
          Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="p-4">
              <Skeleton className="h-16" />
            </li>
          ))}
        {isError && (
          <li className="p-4 text-sm text-danger" role="alert">
            Could not load alerts.{' '}
            <button className="underline" onClick={() => void refetch()}>
              Retry
            </button>
          </li>
        )}
        {data?.items.map((a) => (
          <AlertRow key={a.id} alert={a} revealed={revealed} />
        ))}
        {data && data.items.length === 0 && (
          <li>
            {active > 0 ? (
              <EmptyState
                icon={BellRing}
                title="No alerts match these filters"
                action={
                  <Button variant="outline" onClick={clear}>
                    Clear filters
                  </Button>
                }
              >
                Try a different status, phone or category.
              </EmptyState>
            ) : (
              <EmptyState icon={BellRing} title="No alerts yet">
                When a message needs your attention, Iris lists it here and sends it to your
                WhatsApp.
              </EmptyState>
            )}
          </li>
        )}
      </ul>
      {data && (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={data.total}
          noun={['alert', 'alerts']}
          onPage={(p) => update({ page: String(p) })}
        />
      )}
    </div>
  )
}
