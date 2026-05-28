/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import {
  clearSession,
  getSession,
  setSession,
  type AuthSession,
  type SessionMode,
} from './TokenStore'

interface LoginParams {
  mode: SessionMode
  token: string
  telegramUserId?: number
}

interface AuthContextValue {
  session: AuthSession | null
  mode: SessionMode | null
  token: string | null
  telegramUserId: number | null
  isAuthenticated: boolean
  login: (params: LoginParams) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<AuthSession | null>(() => getSession())

  const login = useCallback((params: LoginParams) => {
    const nextSession: AuthSession = {
      mode: params.mode,
      token: params.token,
      telegramUserId: params.telegramUserId,
    }
    setSession(nextSession)
    setSessionState(nextSession)
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setSessionState(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      mode: session?.mode ?? null,
      token: session?.token ?? null,
      telegramUserId: session?.telegramUserId ?? null,
      isAuthenticated: Boolean(session?.token),
      login,
      logout,
    }),
    [login, logout, session],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
