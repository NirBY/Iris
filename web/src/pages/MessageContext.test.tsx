import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithApp } from '../test-utils'
import { MessageContext } from './MessageContext'

const base = {
  chat_id: 1,
  chat_name: 'Class',
  is_group: true,
  sender_name: 'Dan',
  from_me: false,
  type: 'text',
  transcript: null,
  snippet: null,
  sent_at: '2026-10-06T10:00:00Z',
  status: 'done',
  verdict: 'safe',
  redacted: false,
  edited_at: null,
  revoked_at: null,
  kids: [{ id: 1, kid_name: 'Noa' }],
  failure: null,
}
const target = { ...base, id: 2, text: 'the second line' }
const detail = { ...target, classifications: [], revisions: [], media: null }

function page(redacted = false) {
  return renderWithApp(
    <Routes>
      <Route path="/messages/:id" element={<MessageContext />} />
    </Routes>,
    {
      '/api/messages/2/context': [
        { ...base, id: 1, text: 'the first line' },
        redacted ? { ...target, redacted: true, text: null } : target,
      ],
      '/api/messages/2': redacted ? { ...detail, redacted: true, text: null } : detail,
    },
    '/messages/2',
  )
}

test('the whole conversation is hidden until the eye is pressed', async () => {
  page()
  await screen.findAllByText('Content hidden')
  expect(screen.queryByText('the first line')).not.toBeInTheDocument()
  expect(screen.queryByText('the second line')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(await screen.findByText('the first line')).toBeInTheDocument()
  expect(screen.getByText('the second line')).toBeInTheDocument()
})

test('a withheld message stays withheld and has no eye', async () => {
  page(true)
  expect(await screen.findAllByText(/withheld on purpose and never stored/)).not.toHaveLength(0)
  expect(screen.queryByRole('button', { name: /Show content/ })).not.toBeInTheDocument()
})
