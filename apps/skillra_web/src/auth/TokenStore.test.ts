/**
 * TokenStore unit tests
 * Sprint-006 TASK-10
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { clearSession, clearToken, getSession, getToken, hasToken, setSession, setToken } from '../auth/TokenStore'

describe('TokenStore', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('getToken returns null when no token stored', () => {
    expect(getToken()).toBeNull()
  })

  it('setToken stores token and getToken retrieves it', () => {
    setToken('test-token-123')
    expect(getToken()).toBe('test-token-123')
  })

  it('clearToken removes the stored token', () => {
    setToken('test-token-123')
    clearToken()
    expect(getToken()).toBeNull()
  })

  it('hasToken returns false when no token', () => {
    expect(hasToken()).toBe(false)
  })

  it('hasToken returns true when token is set', () => {
    setToken('some-token')
    expect(hasToken()).toBe(true)
  })

  it('stores user sessions with telegram user id', () => {
    setSession({ mode: 'user', token: 'sk_123_key', telegramUserId: 123 })
    expect(getSession()).toEqual({ mode: 'user', token: 'sk_123_key', telegramUserId: 123 })
    expect(getToken()).toBe('sk_123_key')
  })

  it('clearSession removes the stored session and compatibility token', () => {
    setSession({ mode: 'service', token: 'service-token' })
    clearSession()
    expect(getSession()).toBeNull()
    expect(getToken()).toBeNull()
  })
})
