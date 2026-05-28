import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SalaryTrendChart from './SalaryTrendChart'

const mocks = vi.hoisted(() => ({
  useSalaryTrend: vi.fn(),
}))

vi.mock('../hooks/useTrends', () => ({
  useSalaryTrend: mocks.useSalaryTrend,
}))

vi.mock('recharts', () => ({
  Line: () => <div data-testid="line" />,
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Tooltip: () => <div data-testid="tooltip" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
}))

describe('SalaryTrendChart', () => {
  beforeEach(() => {
    mocks.useSalaryTrend.mockReset()
  })

  it('renders the latest salary trend point', () => {
    mocks.useSalaryTrend.mockReturnValue({
      data: {
        role: 'Data Analyst',
        grade: 'Middle',
        metric: 'p50',
        currency: 'RUB',
        data: [
          { week_start: '2026-05-04', value: 220000 },
          { week_start: '2026-05-11', value: 240000 },
        ],
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    })

    render(<SalaryTrendChart role="Data Analyst" grade="Middle" />)

    expect(screen.getByText('Тренд зарплаты')).toBeInTheDocument()
    expect(screen.getByText('Data Analyst · Middle')).toBeInTheDocument()
    expect(screen.getByText('240k ₽')).toBeInTheDocument()
    expect(screen.getByTestId('line-chart')).toBeInTheDocument()
  })

  it('shows an empty state when the trend has no points', () => {
    mocks.useSalaryTrend.mockReturnValue({
      data: { role: 'Data Analyst', grade: 'Middle', metric: 'p50', currency: 'RUB', data: [] },
      isLoading: false,
      isFetching: false,
      isError: false,
    })

    render(<SalaryTrendChart role="Data Analyst" grade="Middle" />)

    expect(screen.getByText('Для выбранного сегмента пока нет истории зарплат.')).toBeInTheDocument()
  })

  it('shows a trust warning when trend claims are blocked', () => {
    mocks.useSalaryTrend.mockReturnValue({
      data: {
        role: 'Data Analyst',
        grade: 'Middle',
        metric: 'p50',
        currency: 'RUB',
        claim_status: 'blocked',
        warnings: ['Историческая динамика сейчас заблокирована: gates not passed.'],
        data: [],
      },
      isLoading: false,
      isFetching: false,
      isError: false,
    })

    render(<SalaryTrendChart role="Data Analyst" grade="Middle" />)

    expect(screen.getByText(/Историческая динамика сейчас заблокирована/)).toBeInTheDocument()
  })

  it('degrades cleanly when the trend endpoint is unavailable', () => {
    mocks.useSalaryTrend.mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetching: false,
      isError: true,
    })

    render(<SalaryTrendChart role="Data Analyst" grade="Middle" />)

    expect(screen.getByText('Тренд зарплат пока недоступен.')).toBeInTheDocument()
  })
})
