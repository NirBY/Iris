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
  'alerts.sender_instance_id': null,
  'alerts.recipient': null,
  'alerts.cooldown_minutes': 10,
  'alerts.alert_on_review': false,
  'alerts.timezone': 'Asia/Jerusalem',
}

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
