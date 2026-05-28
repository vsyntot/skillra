import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SearchPage from './SearchPage'

const mocks = vi.hoisted(() => ({
  useCurrentUserProfile: vi.fn(),
  useCareerPlan: vi.fn(),
  useSaveCareerPlanVacancy: vi.fn(),
  useUpdateApplicationOutcome: vi.fn(),
  useVacancySearch: vi.fn(),
}))

vi.mock('../components/DataFreshnessIndicator', () => ({
  default: () => <span>Данные актуальны по 19 мая 2026</span>,
}))

vi.mock('../components/MetaSelect', () => ({
  default: ({ label }: { label: string }) => <label>{label}</label>,
}))

vi.mock('../hooks/useVacancySearch', () => ({
  useVacancySearch: mocks.useVacancySearch,
}))

vi.mock('../hooks/useCurrentUserProfile', () => ({
  useCurrentUserProfile: mocks.useCurrentUserProfile,
}))

vi.mock('../hooks/useCareerPlan', () => ({
  useCareerPlan: mocks.useCareerPlan,
  useSaveCareerPlanVacancy: mocks.useSaveCareerPlanVacancy,
  useUpdateApplicationOutcome: mocks.useUpdateApplicationOutcome,
}))

describe('SearchPage', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-19T12:00:00Z'))
    mocks.useCurrentUserProfile.mockReset()
    mocks.useCareerPlan.mockReset()
    mocks.useSaveCareerPlanVacancy.mockReset()
    mocks.useUpdateApplicationOutcome.mockReset()
    mocks.useVacancySearch.mockReset()
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 0,
      profile: null,
      isUserMode: false,
    })
    mocks.useSaveCareerPlanVacancy.mockReturnValue({ mutate: vi.fn(), isPending: false })
    mocks.useUpdateApplicationOutcome.mockReturnValue({ mutate: vi.fn(), isPending: false })
    mocks.useCareerPlan.mockReturnValue({ data: null, isLoading: false, isError: false })
  })

  afterEach(() => {
    vi.useRealTimers()
    window.history.replaceState(null, '', '/')
  })

  it('does not show admin-only indexer status on the public search page', () => {
    mocks.useVacancySearch.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
    })

    render(<SearchPage />)

    expect(screen.queryByText(/Проиндексировано вакансий/)).not.toBeInTheDocument()
  })

  it('shows a user-facing empty state when the search index is not ready', () => {
    mocks.useVacancySearch.mockReturnValue({
      data: { total: 0, query: 'python', results: [], index_status: 'idle' },
      isLoading: false,
      isError: false,
    })

    render(<SearchPage />)
    fireEvent.change(screen.getByPlaceholderText('Поиск по вакансиям...'), { target: { value: 'python' } })

    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(screen.getByText('Вакансии не найдены')).toBeInTheDocument()
    expect(screen.getByText(/Индекс поиска сейчас обновляется/)).toBeInTheDocument()
    expect(screen.queryByText('POST /v1/admin/index-meilisearch')).not.toBeInTheDocument()
  })

  it('hydrates saved vacancy status from the current career plan', () => {
    const updateMutate = vi.fn()
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 101,
      profile: { target_role: 'data', target_grade: 'junior' },
      isUserMode: true,
    })
    mocks.useCareerPlan.mockReturnValue({
      data: {
        actions: [
          {
            id: 77,
            title: 'Apply to Data Analyst',
            action_type: 'saved_vacancy',
            status: 'planned',
            priority: 50,
            hh_vacancy_id: 'vac-1',
            application_status: 'saved',
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
    mocks.useUpdateApplicationOutcome.mockReturnValue({ mutate: updateMutate, isPending: false })
    mocks.useVacancySearch.mockReturnValue({
      data: { total: 1, query: '', results: [vacancyFixture('vac-1')] },
      isLoading: false,
      isError: false,
    })

    render(<SearchPage />)

    expect(screen.getByText('Сохранено')).toBeInTheDocument()
    expect(screen.queryByText('Сохранить в план')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Отклик' }))

    expect(updateMutate).toHaveBeenCalledWith(
      { actionId: 77, payload: { status: 'applied' } },
      expect.any(Object),
    )
  })

  it('offers guided recovery when search has results but the career plan is missing', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 102,
      profile: { target_role: 'data', target_grade: 'junior' },
      isUserMode: true,
    })
    mocks.useCareerPlan.mockReturnValue({ data: null, isLoading: false, isError: false })
    mocks.useVacancySearch.mockReturnValue({
      data: { total: 1, query: '', results: [vacancyFixture('vac-2')] },
      isLoading: false,
      isError: false,
    })

    render(<SearchPage />)

    expect(mocks.useVacancySearch).toHaveBeenLastCalledWith(
      expect.any(String),
      expect.objectContaining({ source: 'web', telegram_user_id: 102 }),
      expect.objectContaining({ limit: 20, offset: 0 }),
    )
    expect(screen.getByText(/Создайте карьерный план/)).toBeInTheDocument()
    expect(screen.queryByText('Сохранить в план')).not.toBeInTheDocument()
  })

  it('shows personalized match explanations for vacancy results', () => {
    mocks.useVacancySearch.mockReturnValue({
      data: {
        total: 1,
        query: 'python',
        search_state: 'ready',
        results: [
          vacancyFixture('vac-3', {
            fit_reason: 'роль совпадает с профилем',
            gap_reason: 'нужно подтянуть: airflow',
            plan_relevance: 'Связана с действием плана',
            matched_skills: ['sql'],
            missing_skills: ['airflow'],
            match_score: 82,
            match_level: 'high',
          }),
        ],
      },
      isLoading: false,
      isError: false,
    })

    render(<SearchPage />)

    expect(screen.getByText(/Матч 82%/)).toBeInTheDocument()
    expect(screen.getByText(/Почему подходит:/)).toBeInTheDocument()
    expect(screen.getByText(/Что подтянуть:/)).toBeInTheDocument()
    expect(screen.getByText(/Связь с планом:/)).toBeInTheDocument()
    expect(screen.getByText('Уже есть: sql')).toBeInTheDocument()
    expect(screen.getByText('Gap: airflow')).toBeInTheDocument()
  })
})

function vacancyFixture(id: string, overrides: Record<string, unknown> = {}) {
  return {
    hh_vacancy_id: id,
    title: 'Data Analyst',
    url: 'https://hh.ru/vacancy/1',
    hh_url: 'https://hh.ru/vacancy/1',
    skills: ['sql'],
    matched_skills: [],
    missing_skills: [],
    ...overrides,
  }
}
