import { useEffect, useRef } from 'react'

/** Polls a function at the given interval while `enabled` is true */
export function usePolling(fn: () => void, intervalMs: number, enabled: boolean) {
  const savedFn = useRef(fn)
  savedFn.current = fn

  useEffect(() => {
    if (!enabled) return
    const id = setInterval(() => savedFn.current(), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs, enabled])
}
