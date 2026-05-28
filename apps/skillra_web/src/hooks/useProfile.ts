/**
 * useProfile — React Query hooks for user profile.
 * Sprint-006 TASK-08
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchProfile, fetchUserResume, updateProfile, uploadUserResume, UserProfileIn } from '../api/client'
import { nextBestActionKey } from './useNextBestAction'

export function useProfile(telegramUserId: number) {
  return useQuery({
    queryKey: ['profile', telegramUserId],
    queryFn: () => fetchProfile(telegramUserId),
    enabled: telegramUserId > 0,
  })
}

export function useUpdateProfile(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: UserProfileIn) => updateProfile(telegramUserId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['profile', telegramUserId] })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useResumeStatus(telegramUserId: number) {
  return useQuery({
    queryKey: ['resume', telegramUserId],
    queryFn: () => fetchUserResume(telegramUserId),
    enabled: telegramUserId > 0,
  })
}

export function useUploadResume(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => uploadUserResume(telegramUserId, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['resume', telegramUserId] })
    },
  })
}
