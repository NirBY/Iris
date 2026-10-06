import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import type { Chat } from '../lib/types'

export function Chats() {
  const { data } = useQuery({ queryKey: ['chats'], queryFn: () => api<Chat[]>('/api/chats') })
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Chats</h1>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {data?.map((c) => (
          <li key={c.id} className="flex flex-col gap-1 p-3">
            <span className="flex flex-wrap items-center gap-2">
              <span>{c.is_group ? '👥' : '👤'}</span>
              <Link to={`/messages?chat=${c.id}`} className="font-medium underline" dir="auto">
                {c.name ?? c.wa_chat_id}
              </Link>
              <span className="text-xs text-slate-500">{c.is_group ? 'group' : 'direct'}</span>
            </span>
            <span className="flex flex-wrap gap-3 text-xs text-slate-500">
              <span>Kids: {c.kids.map((k) => k.kid_name).join(', ') || '-'}</span>
              <span>{c.message_count} messages</span>
              <span>{c.alert_count} alerts</span>
              {c.last_message_at && <span>last {dateTime(c.last_message_at)}</span>}
            </span>
          </li>
        ))}
        {data?.length === 0 && <li className="p-3 text-sm text-slate-500">No chats yet.</li>}
      </ul>
    </div>
  )
}
