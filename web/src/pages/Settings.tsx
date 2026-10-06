import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError } from '../lib/api'
import type { Instance, ThresholdRow } from '../lib/types'

type Secret = { set: boolean }
interface Values {
  'openai.api_key': Secret
  'transcription.provider': 'openai' | 'cloudflare'
  'transcription.openai_model': string
  'transcription.cloudflare_account_id': string | null
  'transcription.cloudflare_api_token': Secret
  'transcription.cloudflare_model': string
  'classification.model': string
  'classification.context_window_size': number
  'classification.context_max_age_hours': number
  'scope.monitor_from_me': boolean
  'scope.monitor_direct': boolean
  'scope.monitor_groups': boolean
  'alerts.sender_instance_id': number | null
  'alerts.recipient': string | null
  'alerts.cooldown_minutes': number
  'alerts.alert_on_review': boolean
  'alerts.timezone': string
  'retention.message_days': number
  'retention.alert_days': number
}
interface TestResult {
  ok: boolean
  detail: string
}
type Change = string | number | boolean | null | Record<string, { low: number; high: number }>

const input =
  'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'
const TABS = ['Providers', 'Classification', 'Alerts', 'Scope', 'Retention', 'Account'] as const
type Tab = (typeof TABS)[number]
const SECRETS = ['openai.api_key', 'transcription.cloudflare_api_token']
const NUMBERS = [
  'alerts.cooldown_minutes',
  'classification.context_window_size',
  'classification.context_max_age_hours',
  'retention.message_days',
  'retention.alert_days',
]
const BOOLEANS = [
  'alerts.alert_on_review',
  'scope.monitor_from_me',
  'scope.monitor_direct',
  'scope.monitor_groups',
]

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {children}
    </label>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded border border-slate-200 p-4 dark:border-slate-800">
      <h2 className="font-medium">{title}</h2>
      {children}
    </section>
  )
}

function SecretInput({
  value,
  isSet,
  onChange,
  onClear,
}: {
  value: string
  isSet: boolean
  onChange: (v: string) => void
  onClear: () => void
}) {
  return (
    <span className="flex items-center gap-2">
      <input
        className={input}
        type="password"
        autoComplete="off"
        value={value}
        placeholder={isSet ? '•••••••• (saved, leave blank to keep)' : 'Not set'}
        onChange={(e) => onChange(e.target.value)}
      />
      {isSet && (
        <button type="button" className="rounded border px-2 py-1 text-xs" onClick={onClear}>
          Clear
        </button>
      )}
    </span>
  )
}

function TestButton({
  target,
  body,
}: {
  target: string
  body: Record<string, string | undefined>
}) {
  const test = useMutation({
    mutationFn: () =>
      api<TestResult>(`/api/settings/test/${target}`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  })
  return (
    <span className="flex items-center gap-2 text-sm">
      <button
        type="button"
        className="rounded border px-2 py-1"
        onClick={() => test.mutate()}
        disabled={test.isPending}
      >
        {test.isPending ? 'Testing…' : 'Test'}
      </button>
      {test.data && (
        <span role="status" className={test.data.ok ? 'text-green-700' : 'text-red-600'}>
          {test.data.ok ? '✓ ' : '✗ '}
          {test.data.detail}
        </span>
      )}
      {test.error && <span className="text-red-600">{String(test.error.message)}</span>}
    </span>
  )
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

function ThresholdsTable({
  edits,
  onEdit,
  onReset,
}: {
  edits: Record<string, { low: string; high: string }>
  onEdit: (cat: string, field: 'low' | 'high', v: string) => void
  onReset: () => void
}) {
  const { data } = useQuery({
    queryKey: ['thresholds'],
    queryFn: () => api<ThresholdRow[]>('/api/settings/thresholds'),
  })
  if (!data) return null
  return (
    <div className="flex flex-col gap-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500">
            <th>Category</th>
            <th>Low (review)</th>
            <th>High (alert)</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r) => (
            <tr key={r.category}>
              <td className="py-1">{r.category}</td>
              {(['low', 'high'] as const).map((f) => (
                <td key={f}>
                  <input
                    className={`${input} w-24`}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    aria-label={`${r.category} ${f}`}
                    value={edits[r.category]?.[f] ?? String(r[f])}
                    onChange={(e) => onEdit(r.category, f, e.target.value)}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="self-start rounded border px-2 py-1 text-xs"
        onClick={onReset}
      >
        Reset all to defaults
      </button>
      <p className="text-xs text-slate-500">
        A score at or above High is harmful. Between Low and High it is inconclusive: re-checked
        with the chat context, then sent to the review queue if still unclear.
      </p>
    </div>
  )
}

function Account() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [msg, setMsg] = useState<string | null>(null)
  async function submit(e: FormEvent) {
    e.preventDefault()
    setMsg(null)
    if (form.next !== form.confirm) return setMsg('The new passwords do not match.')
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: form.current, new_password: form.next }),
      })
      setForm({ current: '', next: '', confirm: '' })
      setMsg('Password changed. Any other signed-in sessions were signed out.')
    } catch (err) {
      setMsg(err instanceof ApiError ? err.message : 'Failed')
    }
  }
  return (
    <Section title="Change password">
      <form onSubmit={submit} className="flex flex-col gap-3">
        <Field label="Current password">
          <input
            className={input}
            type="password"
            autoComplete="current-password"
            value={form.current}
            onChange={(e) => setForm({ ...form, current: e.target.value })}
          />
        </Field>
        <Field label="New password (at least 8 characters)">
          <input
            className={input}
            type="password"
            autoComplete="new-password"
            value={form.next}
            onChange={(e) => setForm({ ...form, next: e.target.value })}
          />
        </Field>
        <Field label="Repeat new password">
          <input
            className={input}
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
          />
        </Field>
        <button className="self-start rounded border px-3 py-1 text-sm">Change password</button>
        {msg && (
          <p role="status" className="text-sm">
            {msg}
          </p>
        )}
      </form>
    </Section>
  )
}

export function Settings() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: () => api<Values>('/api/settings') })
  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const [tab, setTab] = useState<Tab>('Providers')
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [thresholdEdits, setThresholdEdits] = useState<
    Record<string, { low: string; high: string }>
  >({})
  const [msg, setMsg] = useState<string | null>(null)
  const { data: thresholdRows } = useQuery({
    queryKey: ['thresholds'],
    queryFn: () => api<ThresholdRow[]>('/api/settings/thresholds'),
  })
  if (!data) return null

  // Secrets are write-only: the API only says whether they are set, so the field starts blank.
  const get = (k: keyof Values): string => {
    if (k in edit) return edit[k]
    const v = data[k]
    return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : ''
  }
  const set = (k: keyof Values) => (v: string) => setEdit((e) => ({ ...e, [k]: v }))
  const provider = get('transcription.provider')

  async function save(changes: Record<string, Change>, clearKeys: string[] = Object.keys(changes)) {
    setMsg(null)
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify({ settings: changes }) })
      // Only the saved keys leave the draft: other unsaved edits survive (e.g. after "Clear").
      setEdit((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !clearKeys.includes(k))))
      if ('classification.thresholds' in changes) setThresholdEdits({})
      await qc.invalidateQueries()
      setMsg('Saved.')
    } catch (e) {
      setMsg(e instanceof ApiError ? `Not saved: ${e.message}` : 'Not saved')
    }
  }

  function thresholdOverrides(): Record<string, { low: number; high: number }> | null {
    if (!thresholdRows || Object.keys(thresholdEdits).length === 0) return null
    const out: Record<string, { low: number; high: number }> = {}
    for (const r of thresholdRows) {
      const e = thresholdEdits[r.category]
      const low = e ? Number(e.low) : r.low
      const high = e ? Number(e.high) : r.high
      if (low !== r.default_low || high !== r.default_high) out[r.category] = { low, high }
    }
    return out
  }

  function saveAll() {
    const changes: Record<string, Change> = {}
    for (const [k, v] of Object.entries(edit)) {
      if (SECRETS.includes(k) && v === '') continue // blank secret = keep
      if (NUMBERS.includes(k)) changes[k] = Number(v)
      else if (k === 'alerts.sender_instance_id') changes[k] = v === '' ? null : Number(v)
      else if (BOOLEANS.includes(k)) changes[k] = v === 'true'
      else changes[k] = v
    }
    const overrides = thresholdOverrides()
    if (overrides) changes['classification.thresholds'] = overrides
    void save(changes)
  }

  const dirty = Object.keys(edit).length > 0 || Object.keys(thresholdEdits).length > 0
  const bool = (k: keyof Values, label: string) => (
    <Toggle label={label} checked={get(k) === 'true'} onChange={(v) => set(k)(String(v))} />
  )

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      <div
        role="tablist"
        className="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800"
      >
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`px-3 py-1 text-sm ${tab === t ? 'border-b-2 border-indigo-600 font-medium' : 'text-slate-600 dark:text-slate-400'}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'Providers' && (
        <>
          <Section title="OpenAI (moderation)">
            <Field label="API key">
              <SecretInput
                value={get('openai.api_key')}
                isSet={data['openai.api_key'].set}
                onChange={set('openai.api_key')}
                onClear={() => void save({ 'openai.api_key': null })}
              />
            </Field>
            <TestButton target="openai" body={{ api_key: edit['openai.api_key'] || undefined }} />
          </Section>
          <Section title="Transcription">
            <Field label="Provider">
              <select
                className={input}
                value={provider}
                onChange={(e) => set('transcription.provider')(e.target.value)}
              >
                <option value="openai">OpenAI</option>
                <option value="cloudflare">Cloudflare Workers AI</option>
              </select>
            </Field>
            {provider === 'openai' ? (
              <Field label="OpenAI model">
                <select
                  className={input}
                  value={get('transcription.openai_model')}
                  onChange={(e) => set('transcription.openai_model')(e.target.value)}
                >
                  <option value="gpt-4o-mini-transcribe">gpt-4o-mini-transcribe</option>
                  <option value="whisper-1">whisper-1</option>
                </select>
              </Field>
            ) : (
              <>
                <Field label="Cloudflare account ID">
                  <input
                    className={input}
                    value={get('transcription.cloudflare_account_id')}
                    onChange={(e) => set('transcription.cloudflare_account_id')(e.target.value)}
                  />
                </Field>
                <Field label="Cloudflare API token">
                  <SecretInput
                    value={get('transcription.cloudflare_api_token')}
                    isSet={data['transcription.cloudflare_api_token'].set}
                    onChange={set('transcription.cloudflare_api_token')}
                    onClear={() => void save({ 'transcription.cloudflare_api_token': null })}
                  />
                </Field>
                <Field label="Model">
                  <input
                    className={input}
                    value={get('transcription.cloudflare_model')}
                    onChange={(e) => set('transcription.cloudflare_model')(e.target.value)}
                  />
                </Field>
                <TestButton
                  target="cloudflare"
                  body={{
                    account_id: edit['transcription.cloudflare_account_id'] || undefined,
                    api_token: edit['transcription.cloudflare_api_token'] || undefined,
                    model: edit['transcription.cloudflare_model'] || undefined,
                  }}
                />
              </>
            )}
          </Section>
        </>
      )}

      {tab === 'Classification' && (
        <>
          <Section title="Moderation">
            <Field label="Moderation model">
              <input
                className={input}
                value={get('classification.model')}
                onChange={(e) => set('classification.model')(e.target.value)}
              />
            </Field>
            <Field label="Context window (previous messages, 1 to 20)">
              <input
                className={input}
                type="number"
                min={1}
                max={20}
                value={get('classification.context_window_size')}
                onChange={(e) => set('classification.context_window_size')(e.target.value)}
              />
            </Field>
            <Field label="Context max age (hours)">
              <input
                className={input}
                type="number"
                min={1}
                max={168}
                value={get('classification.context_max_age_hours')}
                onChange={(e) => set('classification.context_max_age_hours')(e.target.value)}
              />
            </Field>
          </Section>
          <Section title="Thresholds">
            <ThresholdsTable
              edits={thresholdEdits}
              onEdit={(cat, f, v) =>
                setThresholdEdits((e) => {
                  const row = thresholdRows?.find((r) => r.category === cat)
                  const cur = e[cat] ?? {
                    low: String(row?.low ?? ''),
                    high: String(row?.high ?? ''),
                  }
                  return { ...e, [cat]: { ...cur, [f]: v } }
                })
              }
              onReset={() => void save({ 'classification.thresholds': {} })}
            />
          </Section>
        </>
      )}

      {tab === 'Alerts' && (
        <Section title="Alerts">
          <Field label="Send alerts from (OpenWA instance)">
            <select
              className={input}
              value={get('alerts.sender_instance_id')}
              onChange={(e) => set('alerts.sender_instance_id')(e.target.value)}
            >
              <option value="">Not set</option>
              {instances?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.kid_name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Recipient (phone number in international format, or a chat ID)">
            <input
              className={input}
              dir="ltr"
              placeholder="972501234567"
              value={get('alerts.recipient')}
              onChange={(e) => set('alerts.recipient')(e.target.value)}
            />
          </Field>
          <Field label="Cooldown per chat (minutes)">
            <input
              className={input}
              type="number"
              min={0}
              max={1440}
              value={get('alerts.cooldown_minutes')}
              onChange={(e) => set('alerts.cooldown_minutes')(e.target.value)}
            />
          </Field>
          <Field label="Time zone">
            <input
              className={input}
              value={get('alerts.timezone')}
              onChange={(e) => set('alerts.timezone')(e.target.value)}
            />
          </Field>
          {bool('alerts.alert_on_review', 'Also alert on items needing review')}
          <TestButton
            target="alert"
            body={{
              sender_instance_id: get('alerts.sender_instance_id') || undefined,
              recipient: get('alerts.recipient') || undefined,
            }}
          />
        </Section>
      )}

      {tab === 'Scope' && (
        <Section title="What to monitor">
          {bool('scope.monitor_from_me', 'Messages sent by the kid')}
          {bool('scope.monitor_direct', 'Direct chats')}
          {bool('scope.monitor_groups', 'Groups')}
        </Section>
      )}

      {tab === 'Retention' && (
        <Section title="Retention">
          <Field label="Keep messages for (days)">
            <input
              className={input}
              type="number"
              min={1}
              value={get('retention.message_days')}
              onChange={(e) => set('retention.message_days')(e.target.value)}
            />
          </Field>
          <Field label="Keep alerts for (days)">
            <input
              className={input}
              type="number"
              min={1}
              value={get('retention.alert_days')}
              onChange={(e) => set('retention.alert_days')(e.target.value)}
            />
          </Field>
          <p className="text-xs text-slate-500">
            Messages tied to an alert you have not dismissed are kept. Media is never stored beyond
            processing.
          </p>
        </Section>
      )}

      {tab === 'Account' ? (
        <Account />
      ) : (
        <div className="flex items-center gap-3">
          <button
            className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-40"
            onClick={saveAll}
            disabled={!dirty}
          >
            Save
          </button>
          {msg && (
            <span role="status" className="text-sm">
              {msg}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
