import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HomePage from './HomePage'

const mocks = vi.hoisted(() => ({
  useCurrentUserProfile: vi.fn(),
  useCareerPlan: vi.fn(),
  useSubscription: vi.fn(),
  useNextBestAction: vi.fn(),
  useEvidenceExplainer: vi.fn(),
  resolveEvidenceExplainerEnabled: vi.fn(),
  trackProductEvent: vi.fn(),
}))

vi.mock('../api/client', () => ({
  trackProductEvent: mocks.trackProductEvent,
}))

vi.mock('../hooks/useCurrentUserProfile', () => ({
  useCurrentUserProfile: mocks.useCurrentUserProfile,
}))

vi.mock('../hooks/useCareerPlan', () => ({
  useCareerPlan: mocks.useCareerPlan,
}))

vi.mock('../hooks/useSubscription', () => ({
  useSubscription: mocks.useSubscription,
}))

vi.mock('../hooks/useNextBestAction', () => ({
  useNextBestAction: mocks.useNextBestAction,
}))

vi.mock('../hooks/useEvidenceExplainer', () => ({
  useEvidenceExplainer: mocks.useEvidenceExplainer,
}))

vi.mock('../lib/featureFlags', () => ({
  resolveEvidenceExplainerEnabled: mocks.resolveEvidenceExplainerEnabled,
}))

describe('HomePage', () => {
  beforeEach(() => {
    mocks.useCurrentUserProfile.mockReset()
    mocks.useCareerPlan.mockReset()
    mocks.useSubscription.mockReset()
    mocks.useNextBestAction.mockReset()
    mocks.useEvidenceExplainer.mockReset()
    mocks.resolveEvidenceExplainerEnabled.mockReset()
    mocks.trackProductEvent.mockReset()
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 501,
      isUserMode: true,
      isLoading: false,
      profile: null,
    })
    mocks.useCareerPlan.mockReturnValue({ data: null, isLoading: false })
    mocks.useSubscription.mockReturnValue({ data: null, isLoading: false })
    mocks.useNextBestAction.mockReturnValue({ data: null, isLoading: false })
    mocks.useEvidenceExplainer.mockReturnValue({ data: null, isLoading: false })
    mocks.resolveEvidenceExplainerEnabled.mockReturnValue(false)
  })

  it('uses the shared backend next-best-action when available', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 504,
      isUserMode: true,
      isLoading: false,
      profile: profileFixture(),
    })
    mocks.useNextBestAction.mockReturnValue({
      data: {
        telegram_user_id: 504,
        state: 'find_vacancy',
        action_id: 'find_matching_vacancy',
        title: 'Найти подходящую вакансию',
        reason: 'В плане уже есть действие; теперь нужен рыночный пример.',
        cta: 'Искать вакансии',
        target_surface: 'web',
        route: '/search',
        command: '/search',
        trust_warning: 'Рыночные данные старше 30 дней.',
        profile_quality: {
          score: 100,
          is_complete: true,
          completed_fields: ['target_role'],
          missing_fields: [],
        },
      },
      isLoading: false,
    })

    renderHome()

    expect(screen.getByRole('heading', { name: 'Найти подходящую вакансию' })).toBeInTheDocument()
    expect(screen.getByText('Рыночные данные старше 30 дней.')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-vacancies')).getByText('Сейчас')).toBeInTheDocument()
  })

  it('guides a user without profile to profile creation', () => {
    renderHome()

    expect(screen.getByRole('heading', { name: 'Создать профиль' })).toBeInTheDocument()
    expect(screen.getByText('0%')).toBeInTheDocument()
    expect(screen.getByText('План не создан')).toBeInTheDocument()
    expect(screen.getByText('Первый сеанс')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-profile')).getByText('Сейчас')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-market')).getByText('Позже')).toBeInTheDocument()
  })

  it('guides a profiled user without plan to career plan setup', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 502,
      isUserMode: true,
      isLoading: false,
      profile: profileFixture(),
    })

    renderHome()

    expect(screen.getByRole('heading', { name: 'Собрать план' })).toBeInTheDocument()
    expect(screen.getByText('Аналитик данных · junior')).toBeInTheDocument()
    expect(screen.getByText('План не создан')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-plan')).getByText('Доступно')).toBeInTheDocument()
  })

  it('shows next action, saved vacancy state and active digest for a complete loop', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 503,
      isUserMode: true,
      isLoading: false,
      profile: profileFixture(),
    })
    mocks.useCareerPlan.mockReturnValue({
      data: {
        telegram_user_id: 503,
        target_role: 'Аналитик данных',
        target_grade: 'junior',
        status: 'active',
        created_at: '2026-05-20T10:00:00Z',
        updated_at: '2026-05-20T10:00:00Z',
        actions: [
          {
            id: 10,
            title: 'Собрать портфолио',
            action_type: 'portfolio',
            status: 'planned',
            priority: 10,
            created_at: '2026-05-20T10:00:00Z',
            updated_at: '2026-05-20T10:00:00Z',
          },
          {
            id: 11,
            title: 'Apply to Data Analyst',
            action_type: 'saved_vacancy',
            status: 'in_progress',
            priority: 50,
            hh_vacancy_id: '123',
            vacancy_title: 'Data Analyst',
            application_status: 'applied',
            created_at: '2026-05-20T10:00:00Z',
            updated_at: '2026-05-20T10:00:00Z',
          },
        ],
      },
      isLoading: false,
    })
    mocks.useSubscription.mockReturnValue({ data: { active: true }, isLoading: false })

    renderHome()

    expect(screen.getByText('Дайджест активен')).toBeInTheDocument()
    expect(screen.getAllByText('Собрать портфолио')).toHaveLength(2)
    expect(screen.getByText('Сохранено: 1')).toBeInTheDocument()
    expect(screen.getByText('В работе: 1')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-vacancies')).getByText('Готово')).toBeInTheDocument()
    expect(within(screen.getByTestId('first-session-step-digest')).getByText('Готово')).toBeInTheDocument()
  })

  it('keeps the evidence explainer hidden by default', () => {
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 505,
      isUserMode: true,
      isLoading: false,
      profile: profileFixture(),
    })

    renderHome()

    expect(screen.queryByTestId('evidence-explainer')).not.toBeInTheDocument()
    expect(mocks.useEvidenceExplainer).toHaveBeenCalledWith(505, false)
  })

  it('shows bounded evidence explainer output behind the feature flag', () => {
    mocks.resolveEvidenceExplainerEnabled.mockReturnValue(true)
    mocks.useCurrentUserProfile.mockReturnValue({
      effectiveUserId: 506,
      isUserMode: true,
      isLoading: false,
      profile: profileFixture(),
    })
    mocks.useEvidenceExplainer.mockReturnValue({
      data: {
        version: 'evidence_explainer.v1',
        packet_version: 'evidence_packet.v1',
        task: 'skill_gap_explanation',
        surface: 'web',
        status: 'answered',
        answer: 'Самый заметный разрыв для цели Аналитик данных: airflow.',
        bullets: ['airflow: около 42% вакансий сегмента, навыка нет в профиле. [skill_gap:airflow]'],
        evidence_refs: [{ evidence_id: 'skill_gap:airflow', claim: 'Навык airflow встречается в сегменте.' }],
        uncertainties: [],
        blocked_claims: ['historical_trend_claims'],
        human_review_required: false,
      },
      isLoading: false,
    })

    renderHome()

    expect(screen.getByTestId('evidence-explainer')).toBeInTheDocument()
    expect(screen.getByText('Самый заметный разрыв для цели Аналитик данных: airflow.')).toBeInTheDocument()
    expect(screen.getAllByText(/skill_gap:airflow/).length).toBeGreaterThan(0)
    expect(mocks.useEvidenceExplainer).toHaveBeenCalledWith(506, true)
  })
})

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  )
}

function profileFixture() {
  return {
    telegram_user_id: 502,
    username: 'skillra-user',
    target_role: 'Аналитик данных',
    target_grade: 'junior',
    target_city_tier: 'tier1',
    target_country: 'Россия',
    target_region: 'Москва',
    target_city: 'Москва',
    target_geo_scope: 'local',
    target_work_mode: 'remote',
    target_domain: 'fintech',
    current_skills: ['sql', 'python'],
    warnings: [],
    created_at: '2026-05-20T10:00:00Z',
    updated_at: '2026-05-20T10:00:00Z',
  }
}
