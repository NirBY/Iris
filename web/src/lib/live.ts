import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

export type LiveStatus = 'live' | 'reconnecting' | 'unsupported'

/** Which query keys each server topic makes stale. The stream carries no content, only topics. */
const KEYS: Record<string, string[]> = {
  messages: ['messages', 'message', 'message-context', 'timeline'],
  alerts: ['alerts', 'alert'],
  review: ['review'],
  jobs: ['jobs'],
  stats: ['stats'],
  instances: ['instances'],
  chats: ['chats'],
}

export function invalidateTopics(qc: QueryClient, topics: string[]) {
  for (const t of topics) {
    for (const key of KEYS[t] ?? []) void qc.invalidateQueries({ queryKey: [key] })
  }
}

function parse(data: string): { topics?: unknown; id?: unknown } | null {
  try {
    const v: unknown = JSON.parse(data)
    return v && typeof v === 'object' ? v : null
  } catch {
    return null
  }
}

/**
 * Keeps the open page current: opens /api/events, refetches what the server says changed, and
 * catches up on everything after a (re)connect or when the tab comes back. Polling stays as the
 * fallback, so a blocked or buffered stream only costs freshness.
 */
export function useLiveUpdates(onAlert: (id: number | null) => void): LiveStatus {
  const qc = useQueryClient()
  const alertRef = useRef(onAlert)
  useEffect(() => {
    alertRef.current = onAlert
  })
  const [status, setStatus] = useState<LiveStatus>(
    typeof EventSource === 'undefined' ? 'unsupported' : 'reconnecting',
  )
  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const source = new EventSource('/api/events')
    const everything = () => void qc.invalidateQueries()
    source.addEventListener('hello', () => {
      setStatus('live')
      everything() // whatever happened while we were not listening
    })
    source.addEventListener('change', (e) => {
      const topics = parse((e as MessageEvent<string>).data)?.topics
      if (Array.isArray(topics)) {
        invalidateTopics(
          qc,
          topics.filter((t): t is string => typeof t === 'string'),
        )
      }
    })
    source.addEventListener('alert', (e) => {
      const id = parse((e as MessageEvent<string>).data)?.id
      alertRef.current(typeof id === 'number' ? id : null)
    })
    source.onerror = () => setStatus('reconnecting') // the browser retries by itself
    const onVisible = () => {
      if (document.visibilityState === 'visible') everything()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      source.close()
    }
  }, [qc])
  return status
}
