import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithApp } from '../test-utils'
import { AlertDetail } from './AlertDetail'

const alert = {
  id: 3,
  message_id: 4,
  chat_id: 1,
  categories: ['violence'],
  max_score: 0.94,
  kid_names: ['Noa'],
  chat_name: 'Class',
  sender_name: 'Dan',
  quote: 'I will find you',
  redacted: false,
  status: 'new',
  delivery_status: 'sent',
  delivery_error: null,
  notified_at: '2026-10-06T10:00:00Z',
  created_at: '2026-10-06T10:00:00Z',
  edited_at: null,
  revoked_at: null,
  message_type: 'image',
  sent_at: '2026-10-06T09:59:00Z',
  classifications: [],
}
const media = { id: 7, kind: 'image', content_type: 'image/png', size_bytes: 2048, inline: true }

function page(a: unknown) {
  return renderWithApp(
    <Routes>
      <Route path="/alerts/:id" element={<AlertDetail />} />
    </Routes>,
    { '/api/alerts/3': a },
    '/alerts/3',
  )
}

test('everything stored is hidden until the eye is pressed', async () => {
  const calls = page({ ...alert, media })
  await screen.findByRole('heading', { name: 'Kept media' })
  expect(screen.queryByText('I will find you')).not.toBeInTheDocument()
  expect(screen.queryByRole('img', { name: /photo kept/ })).not.toBeInTheDocument()
  expect(screen.getByText('Photo hidden')).toBeInTheDocument()
  expect(calls.every((c) => !c.url.includes('/api/media/7'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(await screen.findByText('I will find you')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /photo kept/ })).toHaveAttribute('src', '/api/media/7')
  await userEvent.click(screen.getByRole('button', { name: 'Hide content' }))
  expect(screen.queryByText('I will find you')).not.toBeInTheDocument()
})

test('keeps a link to the media on its own page', async () => {
  page({ ...alert, media })
  expect(await screen.findByRole('link', { name: 'Open on its own page' })).toHaveAttribute(
    'href',
    '/media/7',
  )
})

test('has no media section when nothing is kept', async () => {
  page({ ...alert, media: null })
  await screen.findByRole('heading', { name: 'The message' })
  expect(screen.queryByRole('heading', { name: 'Kept media' })).not.toBeInTheDocument()
})

test('a withheld alert says why there is nothing to show, and has no eye', async () => {
  page({ ...alert, redacted: true, quote: null, media })
  expect(
    await screen.findByText(/Withheld on purpose, so there is nothing to show/),
  ).toBeInTheDocument()
  expect(screen.getByText(/never stored the content/)).toBeInTheDocument()
  expect(screen.getByText(/open the chat directly in WhatsApp/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Show content/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('img', { name: /photo kept/ })).not.toBeInTheDocument()
})
