import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Concealed, Masked, RevealButton } from './Reveal'
import { useReveal } from '../lib/useReveal'

function Demo() {
  const { revealed, toggle } = useReveal()
  return (
    <>
      <RevealButton revealed={revealed} onToggle={toggle} />
      <p>
        <Concealed revealed={revealed} length={11}>
          secret text
        </Concealed>
      </p>
    </>
  )
}

test('starts hidden: the real text is not on the page, only a mask', () => {
  const { container } = render(<Demo />)
  expect(container).not.toHaveTextContent('secret')
  expect(screen.getByText('Content hidden')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Show content' })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
})

test('the eye shows and hides it again', async () => {
  render(<Demo />)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  expect(screen.getByText('secret text')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Hide content' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Hide content' }))
  expect(screen.queryByText('secret text')).not.toBeInTheDocument()
})

test('a fresh view always starts hidden again', async () => {
  const first = render(<Demo />)
  await userEvent.click(screen.getByRole('button', { name: 'Show content' }))
  first.unmount()
  render(<Demo />)
  expect(screen.queryByText('secret text')).not.toBeInTheDocument()
})

test('the mask keeps the length in the layout but never the characters', () => {
  const { container } = render(<Masked length={30} />)
  expect(container.textContent).toMatch(/^[• ]+Content hidden$/)
  expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull()
})
