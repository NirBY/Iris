import { Pagination } from '../components/Pagination'
import { useUrlState } from '../lib/urlState'
import { ConfirmDialog } from '../components/ui/dialog'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CircleHelp, ListChecks, MessagesSquare, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { EmptyState } from '../components/EmptyState'
import { KidStack } from '../components/KidAvatar'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { RevealableMessage } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { Scores } from '../components/Scores'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { relativeTime } from '../lib/format'
import type { ReviewPage } from '../lib/types'
import { useMe } from '../lib/auth'
import { QueryError } from '../components/QueryError'

export function Review() {
  const { get, page, update } = useUrlState()
  const view = get('view') === 'missing_data' ? 'missing_data' : 'pending'
  const pageSize = 25
  const qc = useQueryClient()
  const { data: me } = useMe()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review', view, page],
    queryFn: () => api<ReviewPage>(`/api/review?page=${page}&page_size=${pageSize}&view=${view}`),
  })
  const purge = useMutation({
    mutationFn: () => api('/api/media', { method: 'DELETE' }),
    onSuccess: () => {
      toast.success('Saved media scheduled for deletion.')
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not delete media.'),
  })
  const resolve = useMutation({
    mutationFn: (v: { id: number; resolution: 'safe' | 'harmful' | 'missing_data' }) =>
      api(`/api/review/${v.id}${v.resolution === 'missing_data' ? '/data-issue' : ''}`, {
        method: 'POST',
        body: JSON.stringify(
          v.resolution === 'missing_data'
            ? { issue: 'missing_data' }
            : { resolution: v.resolution },
        ),
      }),
    onSuccess: (_d, v) => {
      toast.success(
        v.resolution === 'missing_data'
          ? 'Ignored because data is missing. Saved for later design review.'
          : v.resolution === 'safe'
            ? 'Marked safe.'
            : 'Marked harmful. An alert was created.',
      )
      return qc.invalidateQueries()
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Could not save your decision. Try again.'),
  })
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title="Review"
        description="Messages Iris could not decide on, even with the chat around them. Your call. Parents and admins can resolve reviews. Decisions are recorded without changing future AI classifications."
      />
      {['admin', 'parent'].includes(me?.role || '') && (
        <ConfirmDialog
          trigger={
            <Button variant="outline" disabled={purge.isPending}>
              Delete all saved media evidence
            </Button>
          }
          title="Delete all saved media evidence?"
          description="This permanently removes all saved media copies. Message records and review decisions remain."
          confirmLabel="Delete media"
          onConfirm={() => purge.mutateAsync().then(() => undefined)}
        />
      )}
      <div className="flex flex-wrap gap-2" aria-label="Review views">
        <Button
          variant={view === 'pending' ? 'primary' : 'outline'}
          onClick={() => update({ view: '' })}
        >
          Awaiting review
        </Button>
        <Button
          variant={view === 'missing_data' ? 'primary' : 'outline'}
          onClick={() => update({ view: 'missing_data' })}
        >
          Ignored: missing data
        </Button>
      </div>
      {data && (
        <p className="text-sm text-muted-foreground">
          {data.total} {view === 'missing_data' ? 'ignored for missing data' : 'awaiting review'};{' '}
          {data.reviewed_total ?? 0} judged. Human labels are review records, not proof of AI
          accuracy.
        </p>
      )}
      {isLoading && <Skeleton className="h-40" />}
      {isError && <QueryError what="the review queue" onRetry={() => void refetch()} />}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState
            icon={ListChecks}
            title={view === 'missing_data' ? 'No missing-data reports' : 'Nothing to review'}
          >
            {view === 'missing_data'
              ? 'Items ignored because data is missing appear here for later design review.'
              : 'When Iris cannot tell whether a message is harmful, it waits here for you.'}
          </EmptyState>
        </div>
      )}
      <ul className="flex flex-col gap-4">
        {data?.items.map(({ message: m, classifications, missing_data: missingData }) => (
          <li
            key={m.id}
            className={cn(
              'flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5',
              revokedClass(m, 'row'),
            )}
          >
            <div className="flex flex-wrap items-center gap-3">
              <KidStack names={m.kids.map((k) => k.kid_name)} />
              <span className="font-medium">{m.kids.map((k) => k.kid_name).join(' and ')}</span>
              {m.chat_name && (
                <span className="text-sm text-muted-foreground">in {m.chat_name}</span>
              )}
              <span className="ms-auto text-xs text-muted-foreground">
                {relativeTime(m.sent_at)}
              </span>
            </div>
            <p className="max-w-prose text-lg leading-relaxed">
              {m.sender_name && (
                <span className="me-2 text-sm text-muted-foreground">{m.sender_name}:</span>
              )}
              <RevealableMessage m={m} />
            </p>
            <div className="flex flex-wrap items-center gap-1.5 empty:hidden">
              <MessageFlags m={m} history />
            </div>
            {missingData && (
              <p role="status" className="rounded-md bg-warning-soft p-3 text-sm text-warning">
                Ignored because data is missing. This report is saved separately from safety
                decisions.
              </p>
            )}
            {m.review_reason && <p className="text-sm text-muted-foreground">{m.review_reason}</p>}
            {classifications.slice(-1).map((c) => (
              <details key={c.id} className="group rounded-md bg-surface-2/60 p-3">
                <summary className="cursor-pointer text-sm font-medium">Why it is unclear</summary>
                <div className="mt-3">
                  <Scores scores={c.scores} min={0.05} />
                </div>
              </details>
            ))}
            <div className="grid grid-cols-1 gap-2 min-[400px]:grid-cols-2 sm:flex sm:flex-wrap [&>button]:min-w-0 [&>button]:whitespace-normal">
              <Button
                variant="outline"
                size="lg"
                disabled={resolve.isPending || !['admin', 'parent'].includes(me?.role || '')}
                onClick={() => resolve.mutate({ id: m.id, resolution: 'safe' })}
              >
                <Check /> Mark safe
              </Button>
              <Button
                variant="danger"
                size="lg"
                disabled={resolve.isPending || !['admin', 'parent'].includes(me?.role || '')}
                onClick={() => resolve.mutate({ id: m.id, resolution: 'harmful' })}
              >
                <ShieldAlert /> Mark harmful
              </Button>
              <Button
                variant="outline"
                size="lg"
                title="Ignore this item and save a missing-data report without judging safety."
                className="min-[400px]:col-span-2 sm:col-span-1"
                disabled={
                  resolve.isPending || missingData || !['admin', 'parent'].includes(me?.role || '')
                }
                onClick={() => resolve.mutate({ id: m.id, resolution: 'missing_data' })}
              >
                <CircleHelp /> {missingData ? 'Missing data reported' : 'Ignore — missing data'}
              </Button>
              <Button
                asChild
                variant="ghost"
                size="lg"
                className="min-w-0 whitespace-normal min-[400px]:col-span-2 sm:col-span-1"
              >
                <Link to={`/messages/${m.id}`}>
                  <MessagesSquare /> See the conversation
                </Link>
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {data && (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data.total}
          onPage={(p) => update({ page: String(p) })}
          noun={['message', 'messages']}
        />
      )}
    </div>
  )
}
