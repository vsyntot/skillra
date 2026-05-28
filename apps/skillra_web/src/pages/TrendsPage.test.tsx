import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TrendsPage from './TrendsPage'

const mocks = vi.hoisted(() => ({
  useCareerGraph: vi.fn(),
  useCareerTrajectory: vi.fn(),
  useCurrentUserProfile: vi.fn(),
  useMarket: vi.fn(),
}))

vi.mock('../components/DataFreshnessIndicator', () => ({
  default: () => <span>Данные актуальны</span>,
}))

vi.mock('../components/MetaSelect', () => ({
  default: ({ label, value }: { label: string; value: string }) => (
    <label>
      {label}
      <select value={value} onChange={() => undefined}>
        <option value={value}>{value}</option>
      </select>
    </label>
  ),
}))

vi.mock('../components/SalaryTrendChart', () => ({
  default: ({ role, grade }: { role: string; grade: string }) => (
    <div>SalaryTrendChart {role} {grade}</div>
  ),
}))

vi.mock('../components/SkillDemandTrendChart', () => ({
  default: ({ skill }: { skill: string }) => <div>SkillDemandTrendChart {skill}</div>,
}))

vi.mock('../components/VacancyCountTrendChart', () => ({
  default: ({ role, grade }: { role: string; grade?: string }) => (
    <div>VacancyCountTrendChart {role} {grade}</div>
  ),
}))

vi.mock('../hooks/useMarket', () => ({
  useMarket: mocks.useMarket,
}))

vi.mock('../hooks/useTrends', () => ({
  useCareerGraph: mocks.useCareerGraph,
  useCareerTrajectory: mocks.useCareerTrajectory,
}))

vi.mock('../hooks/useCurrentUserProfile', () => ({
  useCurrentUserProfile: mocks.useCurrentUserProfile,
}))

describe('TrendsPage', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.useCareerGraph.mockReset()
    mocks.useCareerTrajectory.mockReset()
    mocks.useCurrentUserProfile.mockReset()
    mocks.useMarket.mockReset()

    mocks.useCurrentUserProfile.mockReturnValue({
      profile: null,
      isUserMode: false,
    })
    mocks.useMarket.mockReturnValue({
      data: { top_skills: ['Python', 'SQL', 'Airflow'] },
      isLoading: false,
      isError: false,
    })
    mocks.useCareerTrajectory.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mocks.useCareerGraph.mockReturnValue({
      data: {
        role: 'Data Analyst',
        transitions: [
          {
            from_grade: 'Junior',
            to_grade: 'Middle',
            skills_to_add: ['SQL', 'pandas'],
            salary_delta_pct: 25,
            demand_trend: 'growing',
          },
          {
            from_grade: 'Middle',
            to_grade: 'Senior',
            skills_to_add: ['Airflow'],
            salary_delta_pct: 18,
            demand_trend: 'stable',
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
  })

  it('renders trend charts, top skill trends, and career graph transitions', () => {
    render(<TrendsPage />)

    expect(screen.getByText('Тренды рынка')).toBeInTheDocument()
    expect(screen.getByText(/SalaryTrendChart Data Analyst Middle/)).toBeInTheDocument()
    expect(screen.getByText(/VacancyCountTrendChart Data Analyst Middle/)).toBeInTheDocument()
    expect(screen.getByText('SkillDemandTrendChart Python')).toBeInTheDocument()
    expect(screen.getByText('SkillDemandTrendChart SQL')).toBeInTheDocument()
    expect(screen.getByText('SkillDemandTrendChart Airflow')).toBeInTheDocument()
    expect(screen.getByText('Junior → Middle')).toBeInTheDocument()
    expect(screen.getByText('Middle → Senior')).toBeInTheDocument()
    expect(screen.getByText('Спрос: растёт')).toBeInTheDocument()
  })

  it('falls back to career trajectory when graph data is empty', () => {
    mocks.useCareerGraph.mockReturnValue({
      data: { role: 'Data Analyst', transitions: [] },
      isLoading: false,
      isError: false,
    })
    mocks.useCareerTrajectory.mockReturnValue({
      data: {
        current_role: 'Data Analyst',
        current_grade: 'Middle',
        next_grade: 'Senior',
        salary_current_p50: 220000,
        salary_next_p50: 300000,
        salary_delta_pct: 36,
        skills_to_add: ['Airflow', 'A/B tests'],
      },
      isLoading: false,
      isError: false,
    })

    render(<TrendsPage />)

    expect(screen.getByText('Текущий уровень')).toBeInTheDocument()
    expect(screen.getByText('Следующий уровень')).toBeInTheDocument()
    expect(screen.getByText('Senior')).toBeInTheDocument()
    expect(screen.getByText('Airflow')).toBeInTheDocument()
  })

  it('explains profile dimensions that trend charts do not apply yet', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      isUserMode: true,
      profile: {
        target_role: 'Data Analyst',
        target_grade: 'Middle',
        target_country: 'Россия',
        target_work_mode: 'remote',
        target_domain: 'fintech',
        current_skills: ['Python'],
      },
    })

    render(<TrendsPage />)

    expect(screen.getByText(/Тренды на этой странице считаются по роли и грейду/)).toBeInTheDocument()
    expect(screen.getByText(/география, формат работы, домен/)).toBeInTheDocument()
  })
})
