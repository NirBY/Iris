import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { Review } from '../../src/pages/Review'

const item = {
  message: {
    id: 9,
    chat_id: 1,
    chat_name: 'Maya',
    is_group: false,
    sender_name: 'Maya',
    from_me: false,
    type: 'text',
    text: "lol you're dead meat",
    transcript: null,
    snippet: null,
    sent_at: '2026-10-06T10:00:00Z',
    status: 'done',
    verdict: 'review',
    redacted: false,
    kids: [{ id: 1, kid_name: 'Noa' }],
    failure: null,
  },
  classifications: [
    {
      id: 1,
      stage: 'context',
      input_kind: 'text',
      model: 'm',
      scores: { harassment: 0.41 },
      flagged_categories: ['harassment'],
      band: 'inconclusive',
      context_message_ids: [],
      latency_ms: 1,
    },
  ],
}

test('shows the message with who and where, and explains why it is unclear on request', async () => {
  renderWithApp(<Review />, {
    '/api/auth/me': { username: 'admin', role: 'admin', id: 1 },
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  await screen.findByText(/in Maya/)
  expect(screen.queryByText("lol you're dead meat")).not.toBeInTheDocument() // hidden until shown
  await userEvent.click(screen.getByRole('button', { name: /^Show content/ }))
  expect(await screen.findByText("lol you're dead meat")).toBeInTheDocument()
  await userEvent.click(screen.getByText('Why it is unclear'))
  expect(screen.getByText('harassment')).toBeInTheDocument()
})

test('marking harmful and marking safe each send the decision', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/auth/me': { username: 'admin', role: 'admin', id: 1 },
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  await userEvent.click(await screen.findByRole('button', { name: /Mark harmful/ }))
  expect(calls.find((c) => c.method === 'POST')).toMatchObject({
    url: '/api/review/9',
    body: { resolution: 'harmful' },
  })
  expect(await screen.findByText('Marked harmful. An alert was created.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Mark safe/ }))
  expect(calls.filter((c) => c.method === 'POST')[1]).toMatchObject({
    body: { resolution: 'safe' },
  })
})

test('an empty queue is an invitation, not a blank page', async () => {
  renderWithApp(<Review />, {
    '/api/auth/me': { username: 'admin', role: 'admin', id: 1 },
    '/api/review': { items: [], total: 0, page: 1, page_size: 25 },
  })
  expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
})

test("each card's eye says whose message it belongs to", async () => {
  renderWithApp(<Review />, {
    '/api/auth/me': { username: 'admin', role: 'admin', id: 1 },
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  expect(
    await screen.findByRole('button', { name: 'Show content, message from Maya' }),
  ).toBeInTheDocument()
})

test('watch users cannot resolve reviews or delete evidence', async () => {
  renderWithApp(<Review />, {
    '/api/auth/me': { username: 'viewer', role: 'watch', id: 2 },
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  expect(await screen.findByRole('button', { name: /Mark safe/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Mark harmful/ })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Ignore — missing data' })).toBeDisabled()
  expect(
    screen.queryByRole('button', { name: 'Delete all saved media evidence' }),
  ).not.toBeInTheDocument()
})

test('parents can resolve reviews and delete saved evidence with confirmation', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/auth/me': { username: 'parent', role: 'parent', id: 2 },
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  await userEvent.click(
    await screen.findByRole('button', { name: 'Delete all saved media evidence' }),
  )
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Delete media' }))
  expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/media')).toBe(true)
  expect(screen.getByRole('button', { name: /Mark safe/ })).toBeEnabled()
})

test('review pagination opens items beyond the first 25', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/review?page=1': { items: [item], total: 40, page: 1, page_size: 25 },
    '/api/review?page=2': {
      items: [{ ...item, message: { ...item.message, id: 26, chat_name: 'Page two' } }],
      total: 40,
      page: 2,
      page_size: 25,
    },
  })
  await userEvent.click(await screen.findByRole('button', { name: /Next/ }))
  expect(await screen.findByText('in Page two')).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/review?page=2&page_size=25&view=pending')).toBe(true)
})

test('missing data sends a separate review response', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/review': { items: [item], total: 1, page: 1, page_size: 25 },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Ignore — missing data' }))
  expect(calls.find((c) => c.method === 'POST')).toMatchObject({
    url: '/api/review/9/data-issue',
    body: { issue: 'missing_data' },
  })
  expect(
    await screen.findByText('Ignored because data is missing. Saved for later design review.'),
  ).toBeInTheDocument()
})

test('a saved missing-data response stays visible while a final decision is still possible', async () => {
  renderWithApp(<Review />, {
    '/api/review': {
      items: [{ ...item, missing_data: true }],
      total: 1,
      reviewed_total: 0,
      page: 1,
      page_size: 25,
    },
  })
  expect(await screen.findByRole('status')).toHaveTextContent(
    'saved separately from safety decisions',
  )
  expect(screen.getByRole('button', { name: 'Missing data reported' })).toBeDisabled()
  expect(screen.getByRole('button', { name: /Mark safe/ })).toBeEnabled()
  expect(screen.getByRole('button', { name: /Mark harmful/ })).toBeEnabled()
})

test('ignored view can be selected separately from the active queue', async () => {
  const calls = renderWithApp(<Review />, {
    '/api/review': { items: [], total: 0, page: 1, page_size: 25 },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Ignored: missing data' }))
  expect(await screen.findByText('No missing-data reports')).toBeInTheDocument()
  expect(calls.some((c) => c.url.includes('view=missing_data'))).toBe(true)
})
