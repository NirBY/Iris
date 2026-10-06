import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../lib/api'

type Secret = { set: boolean }
interface Values {
  'openai.api_key': Secret
  'transcription.provider': 'openai' | 'cloudflare'
  'transcription.openai_model': string
  'transcription.cloudflare_account_id': string | null
  'transcription.cloudflare_api_token': Secret
  'transcription.cloudflare_model': string
}
interface TestResult {
  ok: boolean
  detail: string
}

const input =
  'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {children}
    </label>
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

export function Settings() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['settings'], queryFn: () => api<Values>('/api/settings') })
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<string | null>(null)
  if (!data) return null

  // Secrets are write-only: the API only says whether they are set, so the field starts blank.
  const get = (k: keyof Values): string => {
    if (k in edit) return edit[k]
    const v = data[k]
    return typeof v === 'string' ? v : ''
  }
  const set = (k: keyof Values) => (v: string) => setEdit((e) => ({ ...e, [k]: v }))
  const provider = get('transcription.provider')

  async function save(changes: Record<string, string | null>) {
    setMsg(null)
    try {
      await api('/api/settings', { method: 'PUT', body: JSON.stringify({ settings: changes }) })
      // Only the saved keys leave the draft: other unsaved edits survive (e.g. after "Clear").
      setEdit((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !(k in changes))))
      await qc.invalidateQueries({ queryKey: ['settings'] })
      setMsg('Saved.')
    } catch (e) {
      setMsg(e instanceof ApiError ? `Not saved: ${e.message}` : 'Not saved')
    }
  }

  function saveAll() {
    const changes: Record<string, string | null> = {}
    for (const [k, v] of Object.entries(edit)) {
      const isSecret = k === 'openai.api_key' || k === 'transcription.cloudflare_api_token'
      if (isSecret && v === '') continue // blank secret = keep
      changes[k] = v
    }
    void save(changes)
  }

  return (
    <div className="flex max-w-xl flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings · Providers</h1>

      <section className="flex flex-col gap-3 rounded border border-slate-200 p-4 dark:border-slate-800">
        <h2 className="font-medium">OpenAI (moderation)</h2>
        <Field label="API key">
          <SecretInput
            value={get('openai.api_key')}
            isSet={data['openai.api_key'].set}
            onChange={set('openai.api_key')}
            onClear={() => void save({ 'openai.api_key': null })}
          />
        </Field>
        <TestButton target="openai" body={{ api_key: edit['openai.api_key'] || undefined }} />
      </section>

      <section className="flex flex-col gap-3 rounded border border-slate-200 p-4 dark:border-slate-800">
        <h2 className="font-medium">Transcription</h2>
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
      </section>

      <div className="flex items-center gap-3">
        <button
          className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-40"
          onClick={saveAll}
          disabled={Object.keys(edit).length === 0}
        >
          Save
        </button>
        {msg && (
          <span role="status" className="text-sm">
            {msg}
          </span>
        )}
      </div>
    </div>
  )
}
