import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { UserSettings } from '../../src/pages/UserSettings'
import { NotificationsSettings } from '../../src/pages/NotificationsSettings'

const config = { smtp: {}, password_set: false, enabled: false }
const admin = { id: 1, username: 'admin', role: 'admin', email: null, whatsapp_number: null }

test('2FA stays disabled before providers and contacts are ready', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  expect(await screen.findByRole('button', { name: 'Enable 2FA' })).toBeDisabled()
  expect(screen.queryByLabelText('SMTP host')).not.toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Watch only' })).toBeInTheDocument()
})

test.each(['email', 'whatsapp', 'mixed'])('2FA accepts approved %s channels', async (channel) => {
  const enrolled =
    channel === 'email'
      ? { ...admin, email: 'admin@example.com', email_verified: true }
      : { ...admin, whatsapp_number: '+15551234567', whatsapp_verified: true }
  const users =
    channel === 'mixed'
      ? [
          enrolled,
          {
            ...admin,
            id: 2,
            username: 'parent',
            role: 'parent',
            email: 'parent@example.com',
            email_verified: true,
          },
        ]
      : [enrolled]
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': {
      ...config,
      smtp: { verified: channel !== 'whatsapp' },
      green_api: { verified: channel !== 'email' },
    },
    '/api/users': users,
  })
  const enable = await screen.findByRole('button', { name: 'Enable 2FA' })
  await waitFor(() => expect(enable).toBeEnabled())
  await userEvent.click(enable)
  await waitFor(() =>
    expect(
      calls.some((c) => c.url === '/api/users/security/two-factor' && c.method === 'PUT'),
    ).toBe(true),
  )
})

test('editing a user clearly labels admin password reset and personal WhatsApp', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('Reset this user’s password (optional)')).toBeInTheDocument()
  expect(screen.getByLabelText('Personal WhatsApp number')).toBeInTheDocument()
  expect(screen.queryByText('OpenWA phone')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Delete admin/ })).not.toBeInTheDocument()
})

test('invalid user email has a readable error', async () => {
  renderWithApp(<UserSettings />, { '/api/users/security/config': config, '/api/users': [admin] })
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  await userEvent.type(screen.getByLabelText('Email'), 'invalid@gmail')
  await userEvent.click(screen.getByRole('button', { name: 'Save user' }))
  expect(await screen.findByRole('alert')).not.toHaveTextContent('[object Object]')
})

test('contact approval uses the user contact endpoint', async () => {
  const calls = renderWithApp(<UserSettings />, {
    '/api/users/security/config': { ...config, smtp: { verified: true } },
    '/api/users': [{ ...admin, email: 'admin@example.com', email_verified: false }],
  })
  await userEvent.click(
    await screen.findByRole('button', { name: 'Send email approval for admin' }),
  )
  await waitFor(() =>
    expect(calls.some((c) => c.url === '/api/users/1/approve-contact' && c.method === 'POST')).toBe(
      true,
    ),
  )
})

test('notifications supports generic SMTP and GreenAPI', async () => {
  renderWithApp(<NotificationsSettings />, { '/api/users/security/config': config })
  expect(await screen.findByRole('heading', { name: 'SMTP server' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: /GreenAPI/ })).toBeInTheDocument()
  expect(
    screen.queryByRole('heading', { name: 'Two-factor authentication' }),
  ).not.toBeInTheDocument()
})
