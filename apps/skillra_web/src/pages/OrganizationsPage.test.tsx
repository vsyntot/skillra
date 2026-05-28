import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OrganizationsPage from './OrganizationsPage'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useOrganizations: vi.fn(),
  useCreateOrganization: vi.fn(),
  useOrganizationMembers: vi.fn(),
  useCohorts: vi.fn(),
  useCreateCohort: vi.fn(),
  useCohortMembers: vi.fn(),
  useCohortAnalytics: vi.fn(),
  useCreateOrganizationInvite: vi.fn(),
  useExportCohortAnalyticsCsv: vi.fn(),
  useUpdateOrganizationMember: vi.fn(),
  useUpdateCohortMember: vi.fn(),
  createOrganizationMutate: vi.fn(),
  createCohortMutate: vi.fn(),
  createInviteMutate: vi.fn(),
  exportMutate: vi.fn(),
  updateOrgMemberMutate: vi.fn(),
  updateCohortMemberMutate: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('../hooks/useOrganizations', () => ({
  useOrganizations: mocks.useOrganizations,
  useCreateOrganization: mocks.useCreateOrganization,
  useOrganizationMembers: mocks.useOrganizationMembers,
  useCohorts: mocks.useCohorts,
  useCreateCohort: mocks.useCreateCohort,
  useCohortMembers: mocks.useCohortMembers,
  useCohortAnalytics: mocks.useCohortAnalytics,
  useCreateOrganizationInvite: mocks.useCreateOrganizationInvite,
  useExportCohortAnalyticsCsv: mocks.useExportCohortAnalyticsCsv,
  useUpdateOrganizationMember: mocks.useUpdateOrganizationMember,
  useUpdateCohortMember: mocks.useUpdateCohortMember,
}))

describe('OrganizationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.useAuth.mockReturnValue({ mode: 'user' })
    mocks.useOrganizations.mockReturnValue({
      data: [
        {
          id: 1,
          slug: 'hse',
          name: 'HSE Career Center',
          organization_type: 'university',
          role: 'owner',
          members_count: 3,
          cohorts_count: 1,
          created_at: '2026-05-27T10:00:00Z',
          archived_at: null,
        },
      ],
      isLoading: false,
      isError: false,
    })
    mocks.useCreateOrganization.mockReturnValue({ mutate: mocks.createOrganizationMutate, isPending: false })
    mocks.useOrganizationMembers.mockReturnValue({
      data: [
        { user_id: 11, role: 'owner', status: 'active', has_profile: true, joined_at: '2026-05-27T10:00:00Z' },
        { user_id: 12, role: 'member', status: 'active', has_profile: false, joined_at: '2026-05-27T10:00:00Z' },
      ],
      isLoading: false,
    })
    mocks.useCohorts.mockReturnValue({
      data: [
        {
          id: 7,
          organization_id: 1,
          slug: 'data-spring',
          name: 'Data Spring',
          members_count: 3,
          starts_at: null,
          ends_at: null,
          created_at: '2026-05-27T10:00:00Z',
          archived_at: null,
        },
      ],
      isLoading: false,
    })
    mocks.useCreateCohort.mockReturnValue({ mutate: mocks.createCohortMutate, isPending: false })
    mocks.useCohortMembers.mockReturnValue({
      data: [{ user_id: 12, status: 'active', has_profile: false, joined_at: '2026-05-27T10:00:00Z' }],
      isLoading: false,
    })
    mocks.useCohortAnalytics.mockReturnValue({
      data: {
        organization_id: 1,
        cohort_id: 7,
        cohort_name: 'Data Spring',
        window_days: 30,
        generated_at: '2026-05-27T10:00:00Z',
        member_count: 3,
        member_count_bucket: '3',
        suppressed: false,
        suppression_reason: null,
        metrics: [{ metric: 'profile_completion_rate', count: 2, denominator: 3, rate: 0.6667, suppressed: false }],
        skill_heatmap: [
          {
            skill_name: 'python',
            cohort_member_count: 3,
            users_missing_count: 2,
            users_missing_share: 0.6667,
            target_role: 'data',
            suppressed: false,
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
    mocks.useCreateOrganizationInvite.mockReturnValue({ mutate: mocks.createInviteMutate, isPending: false })
    mocks.useExportCohortAnalyticsCsv.mockReturnValue({ mutate: mocks.exportMutate, isPending: false })
    mocks.useUpdateOrganizationMember.mockReturnValue({ mutate: mocks.updateOrgMemberMutate, isPending: false })
    mocks.useUpdateCohortMember.mockReturnValue({ mutate: mocks.updateCohortMemberMutate, isPending: false })
  })

  it('renders B2B admin surface for organization owners', async () => {
    render(<OrganizationsPage />)

    expect((await screen.findAllByText('HSE Career Center')).length).toBeGreaterThan(0)
    expect(screen.getByText('Data Spring')).toBeInTheDocument()
    expect(screen.getByText('Участники организации')).toBeInTheDocument()
    expect(screen.getByText('Профиль заполнен')).toBeInTheDocument()
    expect(screen.getByText('python')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Создать инвайт' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Owner' })).toBeEnabled()
    expect(screen.getAllByRole('button', { name: 'Revoke' }).length).toBeGreaterThan(0)
  })

  it('shows personal-login guard outside user mode', () => {
    mocks.useAuth.mockReturnValue({ mode: 'service' })

    render(<OrganizationsPage />)

    expect(screen.getByText('B2B workspace доступен только в личном входе.')).toBeInTheDocument()
    expect(screen.getByText(/Войдите через личный API-ключ/)).toBeInTheDocument()
  })

  it('creates organizations from the empty-state form', async () => {
    const user = userEvent.setup()
    render(<OrganizationsPage />)

    await user.type(screen.getByPlaceholderText('Новая организация'), 'New Pilot')
    await user.click(screen.getAllByRole('button', { name: 'Создать' })[0])

    expect(mocks.createOrganizationMutate).toHaveBeenCalledWith(
      { name: 'New Pilot', organization_type: 'other' },
      expect.any(Object),
    )
  })

  it('shows suppression copy for small cohorts', async () => {
    mocks.useCohortAnalytics.mockReturnValue({
      data: {
        organization_id: 1,
        cohort_id: 7,
        cohort_name: 'Data Spring',
        window_days: 30,
        generated_at: '2026-05-27T10:00:00Z',
        member_count: 1,
        member_count_bucket: '<3',
        suppressed: true,
        suppression_reason: 'small_cohort',
        metrics: [],
        skill_heatmap: [],
      },
      isLoading: false,
      isError: false,
    })

    render(<OrganizationsPage />)

    expect(await screen.findByText(/Когорта малая: <3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CSV' })).toBeDisabled()
  })

  it('calls member lifecycle mutations from admin controls', async () => {
    const user = userEvent.setup()
    render(<OrganizationsPage />)

    await user.click(await screen.findByRole('button', { name: 'Owner' }))
    await user.click(screen.getAllByRole('button', { name: 'Revoke' })[0])

    expect(mocks.updateOrgMemberMutate).toHaveBeenCalledWith({ userId: 12, payload: { role: 'owner' } })
    expect(mocks.updateOrgMemberMutate).toHaveBeenCalledWith({ userId: 12, payload: { status: 'revoked' } })
  })
})
