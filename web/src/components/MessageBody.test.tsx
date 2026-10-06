import { render, screen } from '@testing-library/react'
import { Failure, VerdictBadge } from './MessageBody'

test('a failed message shows "failed" and its reason, never "pending"', () => {
  const m = { verdict: null, status: 'failed', failure: 'OpenWA has no stored media' }
  render(
    <>
      <VerdictBadge m={m} />
      <Failure m={m} />
    </>,
  )
  expect(screen.getByText('failed')).toBeInTheDocument()
  expect(screen.queryByText('pending')).not.toBeInTheDocument()
  expect(screen.getByText(/OpenWA has no stored media/)).toBeInTheDocument()
})

test('the verdict wins over the status, and other statuses show as themselves', () => {
  const { rerender } = render(
    <VerdictBadge m={{ verdict: 'harmful', status: 'done', failure: null }} />,
  )
  expect(screen.getByText('harmful')).toBeInTheDocument()
  rerender(<VerdictBadge m={{ verdict: null, status: 'skipped', failure: null }} />)
  expect(screen.getByText('skipped')).toBeInTheDocument()
})
