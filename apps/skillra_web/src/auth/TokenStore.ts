/**
 * TokenStore — browser session persistence for service and user API keys.
 * Keeps the Sprint-006 token helpers as compatibility wrappers.
 */

const TOKEN_KEY = 'skillra_api_token'
const SESSION_KEY = 'skillra_auth_session'

export type SessionMode = 'service' | 'user'

export interface AuthSession {
  mode: SessionMode
  token: string
  telegramUserId?: number
}

function parseSession(raw: string | null): AuthSession | null {
  if (!raw) return null

  try {
    const value = JSON.parse(raw) as Partial<AuthSession>
    if ((value.mode === 'service' || value.mode === 'user') && typeof value.token === 'string' && value.token) {
      return {
        mode: value.mode,
        token: value.token,
        telegramUserId: typeof value.telegramUserId === 'number' ? value.telegramUserId : undefined,
      }
    }
  } catch {
    return null
  }

  return null
}

export const getSession = (): AuthSession | null => {
  const session = parseSession(localStorage.getItem(SESSION_KEY))
  if (session) return session

  const legacyToken = localStorage.getItem(TOKEN_KEY)
  return legacyToken ? { mode: 'service', token: legacyToken } : null
}

export const setSession = (session: AuthSession): void => {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  localStorage.setItem(TOKEN_KEY, session.token)
}

export const clearSession = (): void => {
  localStorage.removeItem(SESSION_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

export const getToken = (): string | null => getSession()?.token ?? null

export const setToken = (token: string): void => setSession({ mode: 'service', token })

export const clearToken = (): void => clearSession()

export const hasToken = (): boolean => Boolean(getToken())

export const hasSession = (): boolean => Boolean(getSession())
