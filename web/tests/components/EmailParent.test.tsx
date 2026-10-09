import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ParentConnections } from '../../src/components/PhoneConnections'
import { renderWithApp } from '../test-utils'

test('an email-only registered parent can be selected as an alert recipient', async () => {
  const calls = renderWithApp(<ParentConnections showSender={false} />, {
    '/api/settings': { 'alerts.recipient': null },
    '/api/instances': [],
    '/api/users': [
      {
        id: 2,
        username: 'Parent',
        role: 'parent',
        email: 'parent@example.com',
        email_verified: true,
        whatsapp_number: null,
      },
    ],
  })
  await userEvent.selectOptions(
    await screen.findByLabelText('Add a registered parent by email'),
    'parent@example.com',
  )
  await waitFor(() =>
    expect(
      calls.some(
        (call) => call.method === 'PUT' && JSON.stringify(call.body).includes('parent@example.com'),
      ),
    ).toBe(true),
  )
})
