import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePersistedFilters } from './usePersistedFilters'

describe('usePersistedFilters', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
    localStorage.clear()
  })

  it('restores filters from localStorage', () => {
    localStorage.setItem('filters', JSON.stringify({ role: 'Backend', grade: 'Senior' }))

    const { result } = renderHook(() => usePersistedFilters('filters', { role: '', grade: '' }))

    expect(result.current[0]).toEqual({ role: 'Backend', grade: 'Senior' })
  })

  it('persists filter updates after debounce', () => {
    const { result } = renderHook(() => usePersistedFilters('filters', { role: '', grade: '' }))

    act(() => {
      result.current[1]({ role: 'Data Analyst', grade: 'Middle' })
    })

    expect(localStorage.getItem('filters')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(500)
    })

    expect(JSON.parse(localStorage.getItem('filters') ?? '{}')).toEqual({
      role: 'Data Analyst',
      grade: 'Middle',
    })
  })
})
