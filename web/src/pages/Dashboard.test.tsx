import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Dashboard } from './Dashboard'

const stats = {
  messages_today: 12,
  messages_7d: 80,
  alerts_by_status: { new: 3 },
  alerts_by_delivery: { failed: 1 },
  review_queue: 2,
  jobs_by_status: {},
  queue_depth: 0,
  failed_jobs: 4,
  delivery_configured: false,
  instances: 2,
  silent_instances: 1,
}

function renderPage(over: Partial<typeof stats> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(url.startsWith('/api/stats') ? { ...stats, ...over } : { items: [] }),
          { status: 200 },
        ),
    ),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('shows the numbers and every warning banner', async () => {
  renderPage()
  expect(await screen.findByText('12')).toBeInTheDocument()
  expect(screen.getByText('80')).toBeInTheDocument()
  const banners = screen.getAllByRole('alert').map((b) => b.textContent)
  expect(banners.some((t) => t?.includes('Alert delivery is not configured'))).toBe(true)
  expect(banners.some((t) => t?.includes('4 jobs failed'))).toBe(true)
  expect(banners.some((t) => t?.includes('never received a webhook'))).toBe(true)
})

test('no banners when everything is healthy', async () => {
  renderPage({ delivery_configured: true, failed_jobs: 0, silent_instances: 0 })
  expect(await screen.findByText('12')).toBeInTheDocument()
  expect(screen.queryAllByRole('alert')).toHaveLength(0)
})
