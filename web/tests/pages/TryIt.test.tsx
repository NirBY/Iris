import { cleanup, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithApp } from '../test-utils'
import { TryIt } from '../../src/pages/TryIt'
import { NAV } from '../../src/components/nav'

const rows = [
  ['violence', 0.2, 0.7],
  ['harassment', 0.2, 0.7],
].map(([category, low, high]) => ({
  category,
  low,
  high,
  default_low: low,
  default_high: high,
}))
const response = {
  model: 'omni-moderation-latest',
  verdict: 'review',
  thresholds: rows,
  stages: [{ stage: 'moderation', scores: { violence: 0.4, harassment: 0.01 } }],
}

beforeEach(() => sessionStorage.clear())

async function check(routes: Record<string, unknown> = { '/api/classify/test': response }) {
  const calls = renderWithApp(<TryIt />, routes)
  await userEvent.type(screen.getByLabelText(/^Message to check/), 'hello there')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  await screen.findByText('Thresholds')
  return calls
}

test('the check button needs text', () => {
  renderWithApp(<TryIt />, {})
  expect(screen.getByRole('button', { name: /Check/ })).toBeDisabled()
})

test('sends the text and the context lines, one per line', async () => {
  const calls = renderWithApp(<TryIt />, { '/api/classify/test': response })
  await userEvent.type(screen.getByLabelText(/^Message to check/), 'final')
  await userEvent.type(screen.getByLabelText(/Earlier messages/), 'one{enter}{enter}two')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  await screen.findByText('Thresholds')
  const post = calls.find((c) => c.url === '/api/classify/test')
  expect(post!.body).toEqual({ text: 'final', context: ['one', 'two'] })
})

test('shows the verdict from the saved thresholds', async () => {
  await check()
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
})

test('editing a threshold changes the verdict without another request', async () => {
  const calls = await check()
  const before = calls.filter((c) => c.url === '/api/classify/test').length
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  expect(screen.getByRole('heading', { name: 'Harmful' })).toBeInTheDocument()
  expect(calls.filter((c) => c.url === '/api/classify/test')).toHaveLength(before)
})

test('save sends only the rows that differ from the defaults', async () => {
  const calls = await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Save these thresholds/ }))
  const put = calls.find((c) => c.method === 'PUT')
  expect(put!.body).toEqual({
    settings: { 'classification.thresholds': { violence: { low: 0.2, high: 0.35 } } },
  })
})

test('an invalid range cannot be saved and says why', async () => {
  const calls = await check()
  const low = screen.getByLabelText('violence needs a look')
  await userEvent.clear(low)
  await userEvent.type(low, '0.9')
  expect(screen.getByRole('button', { name: /Save these thresholds/ })).toBeDisabled()
  expect(screen.getByText(/Fix the highlighted values/)).toBeInTheDocument()
  expect(calls.some((c) => c.method === 'PUT')).toBe(false)
})

test('a half-typed value does not change the verdict', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high) // blank
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
  await userEvent.type(high, '-')
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
})

test('threshold edits survive checking another phrase', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  expect(await screen.findByRole('heading', { name: 'Harmful' })).toBeInTheDocument()
  expect(screen.getByLabelText('violence harmful')).toHaveValue(0.35)
})

test('too many context lines are refused before sending', async () => {
  const calls = renderWithApp(<TryIt />, { '/api/classify/test': response })
  await userEvent.type(screen.getByLabelText(/^Message to check/), 'x')
  await userEvent.type(
    screen.getByLabelText(/Earlier messages/),
    Array.from({ length: 21 }, (_, i) => `l${i}`).join('{enter}'),
  )
  await userEvent.click(screen.getByRole('button', { name: /Check/ }))
  expect(await screen.findByText(/at most 20 earlier messages/)).toBeInTheDocument()
  expect(calls.some((c) => c.url === '/api/classify/test')).toBe(false)
})

test('reset returns to the saved values', async () => {
  await check()
  const high = screen.getByLabelText('violence harmful')
  await userEvent.clear(high)
  await userEvent.type(high, '0.35')
  await userEvent.click(screen.getByRole('button', { name: /Reset to saved/ }))
  expect(screen.getByLabelText('violence harmful')).toHaveValue(0.7)
})

test('the page is in the navigation', () => {
  expect(NAV.some((n) => n.to === '/try' && n.label === 'Try it')).toBe(true)
})

test.each(['ollama', 'openai'])(
  'privacy explanation uses the configured %s provider',
  async (provider) => {
    renderWithApp(<TryIt />, { '/api/settings': { 'runtime.classification_provider': provider } })
    const copy =
      provider === 'ollama'
        ? 'The text is sent to your configured Ollama server for classification and is not stored by Iris.'
        : 'The text is sent to OpenAI for moderation and is not stored by Iris.'
    expect(await screen.findByText(copy)).toBeInTheDocument()
    if (provider === 'ollama') expect(screen.queryByText(/sent to OpenAI/)).not.toBeInTheDocument()
  },
)

test('unknown provider does not claim text is sent to OpenAI', async () => {
  renderWithApp(<TryIt />, { '/api/settings': {} })
  expect(
    await screen.findByText(
      'The text is checked by your configured classification provider and is not stored by Iris.',
    ),
  ).toBeInTheDocument()
  expect(screen.queryByText(/sent to OpenAI/)).not.toBeInTheDocument()
})

test('leaving the page and coming back keeps the text and the result', async () => {
  await check()
  cleanup()
  renderWithApp(<TryIt />, { '/api/classify/test': response })
  expect(screen.getByLabelText(/^Message to check/)).toHaveValue('hello there')
  expect(screen.getByRole('heading', { name: 'Needs a look' })).toBeInTheDocument()
})

test('a result for different text says so, and Clear empties the page', async () => {
  await check()
  await userEvent.type(screen.getByLabelText(/^Message to check/), ' again')
  expect(screen.getByText(/This result is for the previous text/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Clear/ }))
  expect(screen.getByLabelText(/^Message to check/)).toHaveValue('')
  expect(screen.queryByText('Thresholds')).not.toBeInTheDocument()
  expect(sessionStorage.getItem('iris.try.result')).toBeNull()
})

test('examples explain the two fields by filling them', async () => {
  renderWithApp(<TryIt />, {})
  expect(screen.getByText('How to use this page')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Game talk (with earlier messages)' }))
  expect(screen.getByLabelText(/^Message to check/)).toHaveValue(
    "I'm going to kill you in the next round 😂",
  )
  expect(screen.getByLabelText(/Earlier messages/)).toHaveValue(
    "Want to play FIFA tonight?\nYes! I'm online at 8",
  )
  await userEvent.click(screen.getByRole('button', { name: 'Same words, no earlier messages' }))
  expect(screen.getByLabelText(/Earlier messages/)).toHaveValue('')
})
