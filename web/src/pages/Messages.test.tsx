import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Messages } from './Messages'

test('renders messages with a highlighted snippet and kid names', async () => {
  const page = {
    items: [
      {
        id: 1,
        chat_id: 1,
        chat_name: 'Class',
        is_group: true,
        sender_name: 'Dan',
        from_me: false,
        type: 'text',
        text: 'שלום עולם',
        transcript: null,
        snippet: '\x02שלום\x03 עולם',
        sent_at: '2026-10-06T10:00:00Z',
        status: 'pending',
        verdict: null,
        redacted: false,
        kids: [{ id: 1, kid_name: 'Noa' }],
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(JSON.stringify(url.startsWith('/api/instances') ? [] : page), { status: 200 }),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Messages />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect((await screen.findByText('שלום')).tagName).toBe('MARK')
  expect(screen.getByText(/Noa/)).toBeInTheDocument()
})
