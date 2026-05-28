import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DigestHistoryPage from './DigestHistoryPage'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useDigestHistory: vi.fn(),
  useDigestPreview: vi.fn(),
}))

vi.mock('../auth/AuthContext', () => ({
  useAuth: mocks.useAuth,
}))

vi.mock('../hooks/useDigestHistory', () => ({
  useDigestHistory: mocks.useDigestHistory,
  useDigestPreview: mocks.useDigestPreview,
}))

describe('DigestHistoryPage', () => {
  beforeEach(() => {
    mocks.useAuth.mockReturnValue({ mode: 'user', telegramUserId: 42 })
    mocks.useDigestHistory.mockReturnValue({
      data: {
        total: 1,
        items: [
          {
            id: 1,
            sent_at: '2026-05-20T09:00:00Z',
            format: 'html',
            text_preview: 'Digest preview',
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
    mocks.useDigestPreview.mockReturnValue({
      data: {
        text: '<p>Новый шаг по плану</p>',
        confidence: 'medium',
        freshness: 'fresh',
      },
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
    })
  })

  it('uses the authenticated user id without asking for Telegram User ID', () => {
    render(
      <MemoryRouter>
        <DigestHistoryPage />
      </MemoryRouter>,
    )

    expect(mocks.useDigestHistory).toHaveBeenCalledWith(42, 10, 0)
    expect(mocks.useDigestPreview).toHaveBeenCalledWith(42)
    expect(screen.queryByPlaceholderText('Telegram User ID')).not.toBeInTheDocument()
    expect(screen.getByText('Текущий дайджест')).toBeInTheDocument()
    expect(screen.getByText('Новый шаг по плану')).toBeInTheDocument()
    expect(screen.getByText('Digest preview')).toBeInTheDocument()
  })
})
