import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccountPage from './AccountPage'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  fetchCurrentApiKeyStatus: vi.fn(),
  revokeCurrentApiKey: vi.fn(),
  deleteProfile: vi.fn(),
  useCommercialState: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('../api/client', () => ({
  fetchCurrentApiKeyStatus: mocks.fetchCurrentApiKeyStatus,
  revokeCurrentApiKey: mocks.revokeCurrentApiKey,
  deleteProfile: mocks.deleteProfile,
}))

vi.mock('../hooks/useCommercialState', () => ({
  useCommercialState: mocks.useCommercialState,
}))

describe('AccountPage', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ mode: 'user', telegramUserId: 42, logout: vi.fn() })
    mocks.fetchCurrentApiKeyStatus.mockResolvedValue({
      key_prefix: 'sk_42_ab',
      created_at: '2026-05-20T09:00:00Z',
      last_used_at: '2026-05-21T10:00:00Z',
      is_active: true,
    })
    mocks.revokeCurrentApiKey.mockResolvedValue({
      revoked: true,
      revoked_at: '2026-05-21T10:30:00Z',
    })
    mocks.deleteProfile.mockResolvedValue(undefined)
    mocks.useCommercialState.mockReturnValue({
      data: {
        plan: 'free',
        subscription_state: 'none',
        entitlements: ['profile.basic'],
        locked_features: ['career_plan.generate_actions', 'skill_gap.export'],
        trial_ends_at: null,
        current_period_ends_at: null,
        provider: null,
        account_url: '/account',
      },
      isLoading: false,
      isError: false,
    })
  })

  it('shows account access and privacy controls for authenticated users', async () => {
    renderWithQueryClient(<AccountPage />)

    expect(await screen.findByText('активен, префикс sk_42_ab')).toBeInTheDocument()
    expect(screen.getByText('Личный вход')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('Free')).toBeInTheDocument()
    expect(screen.getByText('нет платной подписки')).toBeInTheDocument()
    expect(screen.getByText(/Закрыто: Рекомендации из skill gap, Экспорт skill gap/)).toBeInTheDocument()
    expect(screen.getByText(/PM-аналитика строится агрегированно/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отозвать текущий ключ' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Удалить профиль' })).toBeEnabled()
  })

  it('does not allow destructive account actions outside personal login', () => {
    mocks.useAuth.mockReturnValue({ mode: 'team', telegramUserId: null, logout: vi.fn() })

    renderWithQueryClient(<AccountPage />)

    expect(screen.getByText('Командный режим')).toBeInTheDocument()
    expect(screen.getByText('Коммерческий статус доступен только в личном входе.')).toBeInTheDocument()
    expect(screen.getByText('доступен в личном входе')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Отозвать текущий ключ' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Удалить профиль' })).toBeDisabled()
  })

  it('shows payment failure state without provider payload details', () => {
    mocks.useCommercialState.mockReturnValue({
      data: {
        plan: 'pro',
        subscription_state: 'payment_failed',
        entitlements: ['profile.basic'],
        locked_features: ['career_plan.generate_actions'],
        trial_ends_at: null,
        current_period_ends_at: null,
        provider: 'manual_invoice',
        account_url: '/account',
      },
      isLoading: false,
      isError: false,
    })

    renderWithQueryClient(<AccountPage />)

    expect(screen.getByText('платёж не прошёл')).toBeInTheDocument()
    expect(screen.getByText(/При проблемах с оплатой обратитесь в поддержку/)).toBeInTheDocument()
    expect(screen.queryByText(/manual_invoice/)).not.toBeInTheDocument()
  })
})

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
