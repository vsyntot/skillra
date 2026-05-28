import { render, screen } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import DataFreshnessIndicator from './DataFreshnessIndicator'

const mocks = vi.hoisted(() => ({
  useDatasetMeta: vi.fn(),
}))

vi.mock('../hooks/useDataset', () => ({
  useDatasetMeta: mocks.useDatasetMeta,
}))

describe('DataFreshnessIndicator', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-19T12:00:00Z'))
    mocks.useDatasetMeta.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows fresh dataset date and record count', () => {
    mocks.useDatasetMeta.mockReturnValue({
      data: { last_updated: '2026-05-19T00:00:00Z', records_count: 12345 },
      isError: false,
      isLoading: false,
    })

    render(<DataFreshnessIndicator />)

    expect(screen.getByText(/Данные актуальны по 19 мая 2026/)).toBeInTheDocument()
    expect(screen.getByText(/12 345 записей/)).toBeInTheDocument()
  })

  it('uses warning tone for week-old data', () => {
    mocks.useDatasetMeta.mockReturnValue({
      data: { last_updated: '2026-05-09T00:00:00Z', records_count: 10 },
      isError: false,
      isLoading: false,
    })

    render(<DataFreshnessIndicator />)

    const indicator = screen.getByText(/Обновлено 10 дней назад/)
    expect(indicator).toHaveClass('bg-amber-50')
  })

  it('shows unavailable state when metadata cannot be loaded', () => {
    mocks.useDatasetMeta.mockReturnValue({
      data: undefined,
      isError: true,
      isLoading: false,
    })

    render(<DataFreshnessIndicator />)

    expect(screen.getByText('Свежесть данных недоступна')).toBeInTheDocument()
  })
})
