import { useCallback, useRef, useState, type SetStateAction } from 'react'

function read<T>(storageKey: string): { ok: true; value: T | undefined } | { ok: false } {
  try {
    const saved = window.sessionStorage.getItem(storageKey)
    return { ok: true, value: saved === null ? undefined : (JSON.parse(saved) as T) }
  } catch {
    return { ok: false }
  }
}

/** useState that survives leaving and returning to a page in the same browser tab.
 *
 * Writes go to sessionStorage immediately, so a result that arrives after the user opened
 * another page is still there when they come back. sessionStorage is per tab and cleared when
 * the tab closes; when it is unavailable the hook behaves like ordinary component state. */
export function useSessionState<T>(key: string, initial: T) {
  const storageKey = 'iris.' + key
  const [value, setValue] = useState<T>(() => {
    const saved = read<T>(storageKey)
    return saved.ok && saved.value !== undefined ? saved.value : initial
  })
  const latest = useRef(value)
  const set = useCallback(
    (next: SetStateAction<T>) => {
      let previous = latest.current
      const saved = read<T>(storageKey)
      if (saved.ok) previous = saved.value === undefined ? initial : saved.value
      const resolved = typeof next === 'function' ? (next as (previous: T) => T)(previous) : next
      latest.current = resolved
      try {
        if (resolved === null || resolved === '' || resolved === initial)
          window.sessionStorage.removeItem(storageKey)
        else window.sessionStorage.setItem(storageKey, JSON.stringify(resolved))
      } catch {
        // Storage full or blocked: the page keeps working with in-memory state.
      }
      setValue(resolved)
    },
    // `initial` is a constant for each call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [storageKey],
  )
  return [value, set] as const
}
