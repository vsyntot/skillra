import { describe, expect, it } from 'vitest'
import { resolveFallbackServiceToken, shouldClearSessionOnAuthError } from './client'

function axiosError(status: number, data: unknown) {
  return {
    isAxiosError: true,
    response: { status, data },
    toJSON: () => ({}),
  }
}

describe('resolveFallbackServiceToken', () => {
  it('allows service token fallback only in development runtime', () => {
    expect(
      resolveFallbackServiceToken({
        MODE: 'development',
        PROD: false,
        VITE_SKILLRA_API_TOKEN: 'dev-token',
      }),
    ).toBe('dev-token')
  })

  it('blocks service token fallback in production and staging builds', () => {
    expect(
      resolveFallbackServiceToken({
        MODE: 'production',
        PROD: true,
        VITE_SKILLRA_API_TOKEN: 'prod-token',
      }),
    ).toBeUndefined()
    expect(
      resolveFallbackServiceToken({
        MODE: 'development',
        PROD: false,
        VITE_SKILLRA_RUNTIME_ENV: 'staging',
        VITE_SKILLRA_API_TOKEN: 'staging-token',
      }),
    ).toBeUndefined()
  })
})

describe('shouldClearSessionOnAuthError', () => {
  it('clears the browser session for authentication failures', () => {
    expect(shouldClearSessionOnAuthError(axiosError(401, { detail: { error_code: 'INVALID_USER_API_KEY' } }))).toBe(
      true,
    )
    expect(shouldClearSessionOnAuthError(axiosError(401, { detail: { error_code: 'AUTHORIZATION_REQUIRED' } }))).toBe(
      true,
    )
  })

  it('keeps the session for authorization and feature-level denials', () => {
    expect(shouldClearSessionOnAuthError(axiosError(403, { detail: { error_code: 'USER_SCOPE_FORBIDDEN' } }))).toBe(
      false,
    )
    expect(
      shouldClearSessionOnAuthError(axiosError(403, { detail: { error_code: 'EVIDENCE_EXPLAINER_NOT_ALLOWED' } })),
    ).toBe(false)
    expect(shouldClearSessionOnAuthError(axiosError(403, { detail: { error_code: 'USER_API_KEY_REQUIRED' } }))).toBe(
      false,
    )
  })

  it('still clears sessions for legacy 403 invalid-token responses', () => {
    expect(shouldClearSessionOnAuthError(axiosError(403, { detail: { error_code: 'INVALID_USER_API_KEY' } }))).toBe(
      true,
    )
  })
})
