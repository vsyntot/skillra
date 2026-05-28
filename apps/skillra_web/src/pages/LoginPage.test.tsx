/**
 * LoginPage unit tests
 * Sprint-006 TASK-10
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import LoginPage from './LoginPage'

// Mock apiClient
vi.mock('../api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

// Mock navigate
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

import { apiClient } from '../api/client'

function renderLoginPage() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </AuthProvider>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders login form', () => {
    const { getByRole, getByLabelText } = renderLoginPage()
    expect(getByLabelText(/Пользовательский ключ/i)).toBeTruthy()
    expect(getByRole('button', { name: /Войти в Skillra/i })).toBeTruthy()
  })

  it('explains how to get a user API key', () => {
    const { getByRole, getByText } = renderLoginPage()

    expect(getByText('Где взять ключ')).toBeTruthy()
    expect(getByRole('link', { name: '@skillra_bot' })).toHaveAttribute('href', 'https://t.me/skillra_bot')
    expect(getByText('/api_key')).toBeTruthy()
  })

  it('hides system-token mode selector by default', () => {
    const { queryByRole } = renderLoginPage()

    expect(queryByRole('tablist', { name: /Режим входа/i })).toBeNull()
    expect(queryByRole('button', { name: /^Системный$/i })).toBeNull()
    expect(queryByRole('button', { name: /^Пользователь$/i })).toBeNull()
  })

  it('submit button is disabled when token is empty', () => {
    const { getByRole } = renderLoginPage()
    const button = getByRole('button', { name: /Войти в Skillra/i }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it('submit button becomes enabled when token is provided', () => {
    const { getByRole, getByLabelText } = renderLoginPage()
    const input = getByLabelText(/Пользовательский ключ/i)
    fireEvent.change(input, { target: { value: 'my-token' } })
    const button = getByRole('button', { name: /Войти в Skillra/i }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
  })

  it('calls user session endpoint on submit with valid token', async () => {
    const mockedGet = apiClient.get as ReturnType<typeof vi.fn>
    mockedGet.mockResolvedValueOnce({ data: { telegram_user_id: 42 } })

    const { getByRole, getByLabelText } = renderLoginPage()
    fireEvent.change(getByLabelText(/Пользовательский ключ/i), { target: { value: 'valid-token' } })
    fireEvent.click(getByRole('button', { name: /Войти в Skillra/i }))

    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith('/v1/users/me', {
        headers: { Authorization: 'Bearer valid-token' },
      })
    })
  })

  it('shows error message on invalid token', async () => {
    const mockedGet = apiClient.get as ReturnType<typeof vi.fn>
    mockedGet.mockRejectedValueOnce(new Error('Unauthorized'))

    const { getByRole, getByLabelText, findByText } = renderLoginPage()
    fireEvent.change(getByLabelText(/Пользовательский ключ/i), { target: { value: 'bad-token' } })
    fireEvent.click(getByRole('button', { name: /Войти в Skillra/i }))

    const errorMsg = await findByText(/Неверный пользовательский ключ/i)
    expect(errorMsg).toBeTruthy()
  })
})
