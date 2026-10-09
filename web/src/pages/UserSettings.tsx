import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { ConfirmDialog } from '../components/ui/dialog'
import { Button } from '../components/ui/button'
import { Field, Input, Select } from '../components/ui/field'

type User = {
  id: number
  username: string
  role: 'admin' | 'parent' | 'watch'
  email: string | null
  whatsapp_number: string | null
  email_verified?: boolean
  whatsapp_verified?: boolean
}
type SMTP = {
  host: string
  port: number
  tls: string
  username: string
  sender: string
  verified?: boolean
}
const emptyUser = {
  username: '',
  role: 'watch' as const,
  email: '',
  whatsapp_number: '',
  password: '',
}

export function UserSettings() {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/api/users') })
  const security = useQuery({
    queryKey: ['security'],
    queryFn: () =>
      api<{
        smtp: Partial<SMTP>
        green_api?: { verified?: boolean }
        enabled: boolean
        password_set: boolean
      }>('/api/users/security/config'),
  })
  const [form, setForm] = useState<Omit<User, 'id'> & { password: string }>(emptyUser)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [saveError, setSaveError] = useState('')
  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setSaveError('')
    try {
      await action()
      await qc.invalidateQueries({ queryKey: ['security'] })
      await qc.invalidateQueries({ queryKey: ['users'] })
      await qc.invalidateQueries({ queryKey: ['me'] })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not save'
      setSaveError(message)
      toast.error(message)
    } finally {
      setBusy(false)
    }
  }
  const canEnable =
    users.data?.length &&
    users.data.every(
      (u) =>
        (u.email_verified && security.data?.smtp.verified) ||
        (u.whatsapp_verified && security.data?.green_api?.verified),
    )
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-semibold">Users and roles</h2>
        <p className="text-sm text-muted-foreground">
          Watch users have read-only access to Home, Alerts, Review, Messages and Chats. Parents can
          resolve reviews, resend alerts, reprocess messages and delete saved media evidence. Admins
          also manage settings, users and phones. For 2FA, each user needs an approved email or
          personal WhatsApp number.
        </p>
        {users.isError && <p role="alert">Could not load users.</p>}
        <ul className="my-4 flex flex-col gap-2">
          {users.data?.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center gap-3 rounded-md border p-3">
              <span>
                {u.username} · {u.role} · {u.email || 'No email'} ·{' '}
                {u.whatsapp_number || 'No WhatsApp number'}
              </span>
              {u.email &&
                (u.email_verified ? (
                  <span className="text-sm text-success">Email approved</span>
                ) : (
                  <Button
                    disabled={busy || !security.data?.smtp.verified}
                    aria-label={`Send email approval for ${u.username}`}
                    onClick={() =>
                      void run(async () => {
                        await api(`/api/users/${u.id}/approve-contact`, {
                          method: 'POST',
                          body: JSON.stringify({ channel: 'email' }),
                        })
                        toast.success('Email approval link sent.')
                      })
                    }
                  >
                    Approve email
                  </Button>
                ))}
              {u.whatsapp_number &&
                (u.whatsapp_verified ? (
                  <span className="text-sm text-success">WhatsApp approved</span>
                ) : (
                  <Button
                    disabled={busy || !security.data?.green_api?.verified}
                    aria-label={`Send WhatsApp approval for ${u.username}`}
                    onClick={() =>
                      void run(async () => {
                        await api(`/api/users/${u.id}/approve-contact`, {
                          method: 'POST',
                          body: JSON.stringify({ channel: 'whatsapp' }),
                        })
                        toast.success('WhatsApp approval link sent.')
                      })
                    }
                  >
                    Approve WhatsApp
                  </Button>
                ))}
              <Button
                onClick={() => {
                  setSaveError('')
                  setEditing(u.id)
                  setForm({ ...u, password: '' })
                }}
              >
                Edit
              </Button>
              {u.role !== 'admin' && (
                <ConfirmDialog
                  title={`Delete ${u.username}?`}
                  description="This removes the user account and its login access. Monitored phones and messages are retained."
                  confirmLabel="Delete user"
                  pending={busy}
                  trigger={
                    <Button
                      variant="danger"
                      disabled={busy}
                      aria-label={`Delete user ${u.username}`}
                    >
                      Delete user
                    </Button>
                  }
                  onConfirm={() =>
                    run(async () => {
                      await api(`/api/users/${u.id}`, { method: 'DELETE' })
                      if (editing === u.id) {
                        setEditing(null)
                        setForm(emptyUser)
                      }
                      toast.success('User deleted.')
                    })
                  }
                />
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="mb-4 text-lg font-semibold">{editing ? 'Edit user' : 'Add user'}</h2>
        {saveError && (
          <p role="alert" className="mb-3 text-sm text-danger">
            {saveError}
          </p>
        )}
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (form.email && !/^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$/.test(form.email.trim())) {
              setSaveError('Enter a valid email address, for example name@example.com.')
              return
            }
            void run(async () => {
              await api(editing ? `/api/users/${editing}` : '/api/users', {
                method: editing ? 'PUT' : 'POST',
                body: JSON.stringify({
                  username: form.username,
                  role: form.role,
                  email: form.email || null,
                  whatsapp_number: form.whatsapp_number || null,
                  password: form.password || undefined,
                }),
              })
              setEditing(null)
              setForm(emptyUser)
              toast.success('User saved.')
            })
          }}
        >
          <Field label="Username">
            <Input
              required
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
            />
          </Field>
          <Field label={editing ? 'Reset this user’s password (optional)' : 'Password'}>
            <Input
              type="password"
              minLength={8}
              required={!editing}
              value={form.password}
              autoComplete="new-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </Field>
          <Field label="Role">
            <Select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value as User['role'] })}
            >
              <option value="parent">Parent</option>
              <option value="watch">Watch only</option>
              <option value="admin">Admin</option>
            </Select>
          </Field>
          <Field label="Email">
            <Input
              type="email"
              value={form.email || ''}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </Field>
          <Field label="Personal WhatsApp number">
            <Input
              type="tel"
              aria-label="Personal WhatsApp number"
              autoComplete="tel"
              placeholder="+972501234567"
              value={form.whatsapp_number || ''}
              onChange={(e) => setForm({ ...form, whatsapp_number: e.target.value })}
            />
            <p className="text-sm text-muted-foreground">
              Your personal number for receiving 2FA codes. Include + and country code. Codes are
              sent through GreenAPI configured in Settings → Notifications.
            </p>
          </Field>
          <div className="flex items-end gap-2">
            <Button type="submit" disabled={busy}>
              Save user
            </Button>
            {editing && (
              <Button
                type="button"
                onClick={() => {
                  setEditing(null)
                  setForm(emptyUser)
                }}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>
      </section>
      <section className="rounded-lg border bg-surface p-5">
        <h2 className="text-lg font-semibold">Two-factor authentication</h2>
        <p className="mb-3 text-sm">
          {security.data?.enabled
            ? '2FA is required at login. New users need a contact with a tested provider and must approve it before login. Disable 2FA before changing delivery providers.'
            : 'Test SMTP or GreenAPI in Settings → Notifications, then approve at least one contact per user to enable 2FA.'}
        </p>
        <p className="mb-3 text-sm text-muted-foreground">
          Email codes use SMTP. WhatsApp 2FA uses GreenAPI only and includes a Copy code button. An
          approved email with tested SMTP or an approved WhatsApp number with tested GreenAPI is
          enough; both are optional alternatives. Approval links use Iris base URL in Settings →
          Alerts.
        </p>
        <p className="mb-3 text-sm text-muted-foreground">
          If code delivery fails, emergency recovery requires access to the Iris Docker container
          and its predefined recovery key. No recovery-key bypass is available on this login page.
        </p>
        <Button
          disabled={busy || security.isLoading || (!security.data?.enabled && !canEnable)}
          onClick={() =>
            void run(async () => {
              await api('/api/users/security/two-factor', {
                method: 'PUT',
                body: JSON.stringify({ enabled: !security.data?.enabled }),
              })
              toast.success('2FA settings saved.')
            })
          }
        >
          {security.data?.enabled ? 'Disable 2FA' : 'Enable 2FA'}
        </Button>
      </section>
    </div>
  )
}
