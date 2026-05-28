import { useEffect, useState, type Dispatch, type SetStateAction } from 'react'

function readPersistedFilters<T extends object>(key: string, defaults: T): T {
  if (typeof window === 'undefined') return defaults

  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return defaults
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return defaults
    return { ...defaults, ...parsed }
  } catch {
    return defaults
  }
}

export function usePersistedFilters<T extends object>(
  key: string,
  defaults: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [filters, setFilters] = useState<T>(() => readPersistedFilters(key, defaults))

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        window.localStorage.setItem(key, JSON.stringify(filters))
      } catch {
        // localStorage may be unavailable in private mode; filters should still work in memory.
      }
    }, 500)

    return () => window.clearTimeout(timer)
  }, [filters, key])

  return [filters, setFilters]
}
