import { useSyncExternalStore } from 'react'

const KEY = 'iris-show-content'
const listeners = new Set<() => void>()
// Only used while storage is blocked, so the switch still works for this page view.
let memory: boolean | null = null

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false // storage can be blocked (private windows): stay hidden
  }
}

/** Whether stored content starts shown on this browser. Off unless the owner turns it on. */
export function getShowContentByDefault(): boolean {
  return memory ?? stored()
}

export function setShowContentByDefault(on: boolean): void {
  memory = null
  try {
    if (on) localStorage.setItem(KEY, '1')
    else localStorage.removeItem(KEY)
  } catch {
    memory = on
  }
  listeners.forEach((l) => l())
}

function subscribe(notify: () => void) {
  listeners.add(notify)
  // Another tab of this browser changed it: follow, so a shared screen cannot stay revealed.
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY || e.key === null) notify()
  }
  window.addEventListener('storage', onStorage)
  return () => {
    listeners.delete(notify)
    window.removeEventListener('storage', onStorage)
  }
}

export function useShowContentByDefault(): boolean {
  return useSyncExternalStore(subscribe, getShowContentByDefault, () => false)
}
