import { useAuth } from '../auth/AuthContext'
import { useProfile } from './useProfile'

export function useCurrentUserProfile() {
  const { mode, telegramUserId } = useAuth()
  const effectiveUserId = mode === 'user' ? telegramUserId ?? 0 : 0
  const profileQuery = useProfile(effectiveUserId)

  return {
    mode,
    telegramUserId,
    effectiveUserId,
    profile: profileQuery.data,
    isLoading: profileQuery.isLoading,
    isError: profileQuery.isError,
    isUserMode: mode === 'user',
  }
}
