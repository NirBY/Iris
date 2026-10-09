import { render, screen } from '@testing-library/react'
import { OriginalMedia } from '../../src/components/OriginalMedia'

test('does not request media while concealed and shows stickers through Iris when revealed', () => {
  const view = render(<OriginalMedia id={12} type="sticker" revealed={false} />)
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  view.rerender(<OriginalMedia id={12} type="sticker" revealed />)
  expect(screen.getByRole('img', { name: 'Sticker' })).toHaveAttribute(
    'src',
    '/api/media/message/12',
  )
})

test('video uses an authenticated Iris source with playback controls', () => {
  const { container } = render(<OriginalMedia id={13} type="video" revealed />)
  expect(container.querySelector('video')).toHaveAttribute('src', '/api/media/message/13')
  expect(container.querySelector('video')).toHaveAttribute('controls')
})
