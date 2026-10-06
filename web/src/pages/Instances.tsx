import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Instance } from '../lib/types'

const input =
  'rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

function Row({ i }: { i: Instance }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState<string | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['instances'] })
  const act = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: refresh,
    onError: (e) => setMsg(e instanceof ApiError ? e.message : 'Failed'),
  })
  const post = (path: string) => () => api(`/api/instances/${i.id}/${path}`, { method: 'POST' })
  return (
    <li className="flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <strong>{i.kid_name}</strong>
        <span className="text-xs text-slate-500">
          {i.openwa_base_url} · {i.openwa_instance_id.slice(0, 8)}…
        </span>
        <span className="text-xs">Last webhook: {relativeTime(i.last_webhook_at)}</span>
        {!i.enabled && (
          <span className="rounded bg-slate-200 px-2 text-xs dark:bg-slate-700">disabled</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <code className="break-all rounded bg-slate-100 px-2 py-1 text-xs dark:bg-slate-900">
          {i.webhook_url}
        </code>
        <button
          className="rounded border px-2 py-1 text-xs"
          onClick={() => navigator.clipboard?.writeText(i.webhook_url)}
        >
          Copy
        </button>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <button
          className="rounded border px-2 py-1"
          onClick={() => act.mutate(post('register-webhook'))}
        >
          Register webhook in OpenWA
        </button>
        <button
          className="rounded border px-2 py-1"
          onClick={() =>
            confirm('Rotate token? The old URL stops working immediately.') &&
            act.mutate(post('rotate-token'))
          }
        >
          Rotate token
        </button>
        <button
          className="rounded border px-2 py-1"
          onClick={() =>
            act.mutate(() =>
              api(`/api/instances/${i.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ enabled: !i.enabled }),
              }),
            )
          }
        >
          {i.enabled ? 'Disable' : 'Enable'}
        </button>
        <button
          className="rounded border border-red-300 px-2 py-1 text-red-700"
          onClick={() =>
            confirm(`Delete ${i.kid_name}?`) &&
            act.mutate(() => api(`/api/instances/${i.id}`, { method: 'DELETE' }))
          }
        >
          Delete
        </button>
      </div>
      {act.isSuccess && !msg && <p className="text-xs text-green-700">Done.</p>}
      {msg && (
        <p role="alert" className="text-xs text-red-600">
          {msg}
        </p>
      )}
    </li>
  )
}

export function Instances() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const [form, setForm] = useState({
    kid_name: '',
    phone_number: '',
    openwa_base_url: '',
    openwa_instance_id: '',
    openwa_api_key: '',
  })
  const [error, setError] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api('/api/instances', {
        method: 'POST',
        body: JSON.stringify({ ...form, phone_number: form.phone_number || null }),
      })
      setForm({
        kid_name: '',
        phone_number: '',
        openwa_base_url: '',
        openwa_instance_id: '',
        openwa_api_key: '',
      })
      await qc.invalidateQueries({ queryKey: ['instances'] })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed')
    }
  }
  const f = (k: keyof typeof form) => ({
    value: form[k],
    onChange: (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value }),
  })

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Instances</h1>
      <p className="text-sm text-slate-500">
        One instance per kid's WhatsApp number (an OpenWA session).
      </p>
      <ul className="divide-y divide-slate-200 rounded border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
        {data?.map((i) => (
          <Row key={i.id} i={i} />
        ))}
        {data?.length === 0 && <li className="p-3 text-sm text-slate-500">No instances yet.</li>}
      </ul>
      <form
        onSubmit={add}
        className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-800"
      >
        <h2 className="font-medium">Add instance</h2>
        <input className={input} placeholder="Kid name" required {...f('kid_name')} />
        <input className={input} placeholder="Phone number (display only)" {...f('phone_number')} />
        <input className={input} placeholder="OpenWA base URL" required {...f('openwa_base_url')} />
        <input
          className={input}
          placeholder="OpenWA session ID"
          required
          {...f('openwa_instance_id')}
        />
        <input
          className={input}
          type="password"
          placeholder="OpenWA API key"
          autoComplete="off"
          {...f('openwa_api_key')}
        />
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button className="self-start rounded bg-indigo-600 px-3 py-1 text-sm text-white">
          Add
        </button>
      </form>
    </div>
  )
}
