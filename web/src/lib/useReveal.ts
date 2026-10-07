import { useState } from 'react'
import { useShowContentByDefault } from './prefs'

/**
 * Whether stored content is shown. It starts hidden unless the owner turned on "show content by
 * default" on this browser; pressing the eye overrides that for this item until the page changes.
 * Pass a `scope` (a page's id) so that moving to another item starts over even if the component
 * is reused.
 */
export function useReveal(scope = '') {
  const byDefault = useShowContentByDefault()
  const [choice, setChoice] = useState<{ scope: string; shown: boolean } | null>(null)
  const revealed = choice && choice.scope === scope ? choice.shown : byDefault
  return { revealed, toggle: () => setChoice({ scope, shown: !revealed }) }
}
