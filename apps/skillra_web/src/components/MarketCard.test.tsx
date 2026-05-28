/**
 * MarketCard component unit tests
 * Sprint-006 TASK-10
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import MarketCard from '../components/MarketCard'
import { SegmentSummary } from '../api/client'

const mockSummary: SegmentSummary = {
  vacancy_count: 150,
  sample_size: 150,
  salary_sample_size: 90,
  salary_coverage_share: 0.6,
  confidence: 'medium',
  salary_median: 200000,
  salary_q25: 150000,
  salary_q75: 280000,
  remote_share: 0.6,
  junior_friendly_share: 0.3,
  top_skills: ['Python', 'SQL', 'Pandas'],
  warnings: ['Данные за последние 30 дней'],
}

describe('MarketCard', () => {
  it('renders all metrics', () => {
    const { getByText } = render(<MarketCard summary={mockSummary} />)
    expect(getByText('150')).toBeTruthy()
    expect(getByText('Покрытие ЗП')).toBeTruthy()
    expect(getByText('Доверие')).toBeTruthy()
    expect(getByText(/90\/150/)).toBeTruthy()
  })

  it('displays warnings', () => {
    const { getByText } = render(<MarketCard summary={mockSummary} />)
    expect(getByText(/Данные за последние/)).toBeTruthy()
  })

  it('renders with empty warnings', () => {
    const { container } = render(<MarketCard summary={{ ...mockSummary, warnings: [] }} />)
    expect(container).toBeTruthy()
  })

  it('renders top skills list', () => {
    const { getByText } = render(<MarketCard summary={mockSummary} />)
    expect(getByText('Python')).toBeTruthy()
  })
})
