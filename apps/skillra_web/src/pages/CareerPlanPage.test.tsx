import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CareerPlanPage from './CareerPlanPage'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useCareerPlan: vi.fn(),
  useUpsertCareerPlan: vi.fn(),
  usePatchCareerPlan: vi.fn(),
  useCreateCareerAction: vi.fn(),
  useGenerateCareerPlanActions: vi.fn(),
  usePatchCareerAction: vi.fn(),
  upsertMutate: vi.fn(),
  patchPlanMutate: vi.fn(),
  createActionMutate: vi.fn(),
  generateActionsMutate: vi.fn(),
  patchActionMutate: vi.fn(),
  trackProductEvent: vi.fn(),
  useCommercialState: vi.fn(),
}))

vi.mock('../api/client', () => ({
  apiErrorCode: vi.fn(),
  apiErrorMessage: vi.fn(),
  trackProductEvent: mocks.trackProductEvent,
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('../components/MetaSelect', () => ({
  default: ({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) => (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  ),
}))

vi.mock('../components/LockedFeatureCallout', () => ({
  default: () => <div>Рекомендации из skill gap доступно в Trial или Pro.</div>,
}))

vi.mock('../hooks/useCareerPlan', () => ({
  useCareerPlan: mocks.useCareerPlan,
  useUpsertCareerPlan: mocks.useUpsertCareerPlan,
  usePatchCareerPlan: mocks.usePatchCareerPlan,
  useCreateCareerAction: mocks.useCreateCareerAction,
  useGenerateCareerPlanActions: mocks.useGenerateCareerPlanActions,
  usePatchCareerAction: mocks.usePatchCareerAction,
}))

vi.mock('../hooks/useCommercialState', () => ({
  useCommercialState: mocks.useCommercialState,
}))

describe('CareerPlanPage', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ mode: 'user', telegramUserId: 42 })
    mocks.useCareerPlan.mockReturnValue({ data: null, isLoading: false, isError: false })
    mocks.useUpsertCareerPlan.mockReturnValue({ mutate: mocks.upsertMutate, isPending: false })
    mocks.usePatchCareerPlan.mockReturnValue({ mutate: mocks.patchPlanMutate, isPending: false })
    mocks.useCreateCareerAction.mockReturnValue({ mutate: mocks.createActionMutate, isPending: false })
    mocks.useGenerateCareerPlanActions.mockReturnValue({ mutate: mocks.generateActionsMutate, isPending: false })
    mocks.usePatchCareerAction.mockReturnValue({ mutate: mocks.patchActionMutate, isPending: false })
    mocks.useCommercialState.mockReturnValue({
      data: { entitlements: ['*'], locked_features: [], plan: 'pro', subscription_state: 'active' },
      isLoading: false,
      isError: false,
    })
    mocks.upsertMutate.mockReset()
    mocks.patchPlanMutate.mockReset()
    mocks.createActionMutate.mockReset()
    mocks.generateActionsMutate.mockReset()
    mocks.patchActionMutate.mockReset()
    mocks.trackProductEvent.mockReset()
  })

  it('creates an empty career plan for current user', () => {
    render(<CareerPlanPage />)

    fireEvent.click(screen.getByRole('button', { name: /Создать план/ }))

    expect(mocks.upsertMutate).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'active' }),
      expect.any(Object),
    )
  })

  it('renders actions and patches action status', () => {
    mocks.useCareerPlan.mockReturnValue({
      data: {
        telegram_user_id: 42,
        target_role: 'Data Analyst',
        target_grade: 'Middle',
        target_city_tier: 'Moscow',
        target_work_mode: 'remote',
        target_domain: 'fintech',
        status: 'active',
        notes: 'focus',
        created_at: '2026-05-19T10:00:00Z',
        updated_at: '2026-05-19T11:00:00Z',
        actions: [
          {
            id: 7,
            title: 'Learn Airflow',
            description: 'Finish DAG basics',
            action_type: 'learning',
            status: 'planned',
            priority: 10,
            skill_name: 'Airflow',
            expected_impact: 'high',
            effort_estimate: '2 недели',
            review_date: '2026-06-02',
            evidence: { missing_skill: 'Airflow', demand_share: 0.42 },
            hh_vacancy_id: null,
            vacancy_title: null,
            vacancy_url: null,
            created_at: '2026-05-19T10:00:00Z',
            updated_at: '2026-05-19T10:00:00Z',
            completed_at: null,
          },
        ],
      },
      isLoading: false,
      isError: false,
    })

    render(<CareerPlanPage />)

    expect(screen.getByText('Learn Airflow')).toBeInTheDocument()
    expect(screen.getByText(/0 из 1 действий завершено/)).toBeInTheDocument()
    expect(screen.getByText(/Ожидаемый эффект: high/)).toBeInTheDocument()
    expect(screen.getByText(/Оценка усилий: 2 недели/)).toBeInTheDocument()
    expect(screen.getByText('Доказательная база')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Готово/ }))

    expect(mocks.patchActionMutate).toHaveBeenCalledWith({
      actionId: 7,
      payload: { status: 'done' },
    })
  })

  it('does not call generated action API when plan is locked', () => {
    mocks.useCommercialState.mockReturnValue({
      data: {
        entitlements: ['profile.basic'],
        locked_features: ['career_plan.generate_actions'],
        plan: 'free',
        subscription_state: 'none',
      },
      isLoading: false,
      isError: false,
    })
    mocks.useCareerPlan.mockReturnValue({
      data: {
        telegram_user_id: 42,
        status: 'active',
        created_at: '2026-05-19T10:00:00Z',
        updated_at: '2026-05-19T11:00:00Z',
        actions: [],
      },
      isLoading: false,
      isError: false,
    })

    render(<CareerPlanPage />)

    const button = screen.getByRole('button', { name: /Добавить рекомендации из skill gap/ })
    expect(button).toBeDisabled()
    expect(screen.getByText(/доступно в Trial или Pro/)).toBeInTheDocument()

    fireEvent.click(button)

    expect(mocks.generateActionsMutate).not.toHaveBeenCalled()
  })
})
