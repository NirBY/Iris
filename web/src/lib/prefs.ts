import { useSyncExternalStore } from 'react'

const KEY = 'iris-show-content'
const listeners = new Set<() => void>()

/** Whether stored content starts shown on this browser. Off unless the owner turns it on. */
export function getShowContentByDefault(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false // storage can be blocked (private windows): stay hidden
  }
}

export function setShowContentByDefault(on: boolean): void {
  try {
    if (on) localStorage.setItem(KEY, '1')
    else localStorage.removeItem(KEY)
  } catch {
    // the choice still applies until the page is reloaded
    memory = on
  }
  listeners.forEach((l) => l())
}

let memory: boolean | null = null

function read(): boolean {
  const stored = getShowContentByDefault()
  return memory !== null && !stored ? memory : stored
}

export function useShowContentByDefault(): boolean {
  return useSyncExternalStore(
    (notify) => {
      listeners.add(notify)
      return () => {
        listeners.delete(notify)
      }
    },
    read,
    () => false,
  )
}
