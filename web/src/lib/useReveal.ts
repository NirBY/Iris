import { useState } from 'react'

/**
 * Whether stored content is shown. It always starts hidden and is never remembered. Pass a `scope`
 * (a page's id) so that moving to another item hides it again even if the component is reused.
 */
export function useReveal(scope = '') {
  const [shownFor, setShownFor] = useState<string | null>(null)
  const revealed = shownFor === scope
  return { revealed, toggle: () => setShownFor(revealed ? null : scope) }
}
