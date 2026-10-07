import { useState } from 'react'

/** Whether stored content is shown. It always starts hidden and is never remembered. */
export function useReveal() {
  const [revealed, setRevealed] = useState(false)
  return { revealed, toggle: () => setRevealed((r) => !r) }
}
