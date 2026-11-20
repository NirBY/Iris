import { t } from '../lib/i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { SkippedGroups } from '../components/SkippedGroups'
import { Play, Smartphone } from 'lucide-react'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/ui/skeleton'
import { QueryError } from '../components/QueryError'
import { AddPhone, PhoneCard } from '../components/PhoneConnections'
import { api, ApiError } from '../lib/api'
import { toast } from '../lib/notify'
import { Button } from '../components/ui/button'
import type { Instance } from '../lib/types'

export function Instances() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
    refetchInterval: 10_000,
  })
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<Record<string, unknown>>('/api/settings'),
  })
  const qc = useQueryClient()
  const startAll = useMutation({
    mutationFn: () =>
      api<{ started: number; already_running: number; failed: number }>(
        '/api/instances/start-all',
        { method: 'POST' },
      ),
    onSuccess: (r) => {
      const msg =
        `${t('Starting phones:')} ${r.started}, ${t('already running:')} ${r.already_running}` +
        (r.failed ? `, ${t('could not start:')} ${r.failed}` : '')
      if (r.failed) toast.error(msg)
      else toast.success(msg)
      return qc.invalidateQueries({ queryKey: ['instances'] })
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : t('Could not start the phones.')),
  })
  const senderId = Number(settings?.['alerts.sender_instance_id'])
  const children = data?.filter((phone) => phone.role !== 'parent' && phone.id !== senderId)
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title={t('Phones')}
        description={t(
          'Manage monitored children. Parent recipients and sender connections are in Settings → Notifications.',
        )}
      />
      <Link
        to="/settings?tab=Notifications#parent-alert-recipients"
        className="text-sm text-primary underline"
      >
        {t('Manage parent recipients and sender connections')}
      </Link>
      <Link to="/setup" className="text-sm text-primary underline">
        {t('Return to setup checklist')}
      </Link>
      <Button
        className="w-fit"
        variant="outline"
        disabled={startAll.isPending || !data?.length}
        onClick={() => startAll.mutate()}
      >
        <Play /> {startAll.isPending ? t('Starting…') : t('Start all phones')}
      </Button>
      {isLoading && <Skeleton className="h-48" />}
      {isError && <QueryError what="your phones" onRetry={() => void refetch()} />}
      <h2 className="text-lg font-semibold">{t('Children')}</h2>
      <AddPhone defaultRole="child" />
      <SkippedGroups />
      <ul className="flex flex-col gap-4">
        {children?.map((phone) => (
          <PhoneCard key={phone.id} i={phone} />
        ))}
      </ul>
      {children?.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState icon={Smartphone} title={t('No phones yet')}>
            {t(
              "Add the first child's number to start watching. You will need an OpenWA session for it.",
            )}
          </EmptyState>
        </div>
      )}
    </div>
  )
}
