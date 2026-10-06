import { render, screen } from '@testing-library/react'
import { Highlight } from './Highlight'

test('wraps only marked text and never renders HTML', () => {
  render(<Highlight snippet={'a \x02שלום\x03 <b>x</b>'} />)
  expect(screen.getByText('שלום').tagName).toBe('MARK')
  expect(screen.getByText(/<b>x<\/b>/)).toBeInTheDocument()
})
