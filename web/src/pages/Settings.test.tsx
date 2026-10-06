import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Settings } from './Settings'

const settings = {
  'openai.api_key': { set: true },
  'transcription.provider': 'openai',
  'transcription.openai_model': 'gpt-4o-mini-transcribe',
  'transcription.cloudflare_account_id': null,
  'transcription.cloudflare_api_token': { set: false },
  'transcription.cloudflare_model': '@cf/openai/whisper-large-v3-turbo',
  'classification.model': 'omni-moderation-latest',
  'classification.context_window_size': 8,
  'classification.context_max_age_hours': 6,
  'scope.monitor_from_me': true,
  'scope.monitor_direct': true,
  'scope.monitor_groups': true,
  'retention.message_days': 90,
  'retention.alert_days': 365,
  'alerts.sender_instance_id': null,
  'alerts.recipient': null,
  'alerts.cooldown_minutes': 10,
  'alerts.alert_on_review': false,
  'alerts.timezone': 'Asia/Jerusalem',
}

const thresholds = [
  { category: 'violence', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
  { category: 'hate', low: 0.2, high: 0.7, default_low: 0.2, default_high: 0.7 },
]

function renderPage() {
  const calls: { url: string; body?: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body as string | undefined })
      const body = url.startsWith('/api/settings/test')
        ? { ok: true, detail: 'OpenAI Moderation answered' }
        : url.startsWith('/api/instances')
          ? []
          : url.startsWith('/api/settings/thresholds')
            ? thresholds
            : settings
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Settings />
    </QueryClientProvider>,
  )
  return calls
}

test('never shows the saved key, and blank secret is not sent on save', async () => {
  const calls = renderPage()
  expect(await screen.findByPlaceholderText(/saved, leave blank/)).toHaveValue('')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'cloudflare')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({ 'transcription.provider': 'cloudflare' })
})

test('test button reports the result', async () => {
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Test' }))[0])
  expect(await screen.findByText(/OpenAI Moderation answered/)).toBeInTheDocument()
})

test('alert settings are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Alerts' }))
  const cooldown = await screen.findByLabelText(/Cooldown per chat/)
  await userEvent.clear(cooldown)
  await userEvent.type(cooldown, '30')
  await userEvent.click(screen.getByLabelText(/Also alert on items needing review/))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'alerts.cooldown_minutes': 30,
    'alerts.alert_on_review': true,
  })
})

test('only changed thresholds are sent, as overrides of the defaults', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Classification' }))
  const high = await screen.findByLabelText('violence high')
  await userEvent.clear(high)
  await userEvent.type(high, '0.9')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'classification.thresholds': { violence: { low: 0.2, high: 0.9 } },
  })
})

test('scope toggles and retention are sent with the right types', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Scope' }))
  await userEvent.click(await screen.findByLabelText('Groups'))
  await userEvent.click(screen.getByRole('tab', { name: 'Retention' }))
  const days = await screen.findByLabelText(/Keep messages for/)
  await userEvent.clear(days)
  await userEvent.type(days, '30')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  const put = calls.find((c) => c.url === '/api/settings' && c.body)
  expect(JSON.parse(put!.body!).settings).toEqual({
    'scope.monitor_groups': false,
    'retention.message_days': 30,
  })
})

test('password change checks the confirmation before calling the API', async () => {
  const calls = renderPage()
  await userEvent.click(await screen.findByRole('tab', { name: 'Account' }))
  await userEvent.type(screen.getByLabelText('Current password'), 'old-password')
  await userEvent.type(screen.getByLabelText(/^New password/), 'new-password-1')
  await userEvent.type(screen.getByLabelText('Repeat new password'), 'different')
  await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText(/do not match/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/auth/password')).toBe(false)
})
