import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteWeeklySubscription,
  fetchWeeklySubscription,
  upsertWeeklySubscription,
  type WeeklySubscriptionIn,
  type WeeklySubscriptionOut,
} from '../api/client'
import { nextBestActionKey } from './useNextBestAction'

export function useSubscription(telegramUserId: number) {
  return useQuery<WeeklySubscriptionOut>({
    queryKey: ['weekly-subscription', telegramUserId],
    queryFn: () => fetchWeeklySubscription(telegramUserId),
    enabled: telegramUserId > 0,
    retry: false,
  })
}

export function useUpsertSubscription(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: WeeklySubscriptionIn) => upsertWeeklySubscription(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['weekly-subscription', telegramUserId] })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useDeleteSubscription(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteWeeklySubscription(telegramUserId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['weekly-subscription', telegramUserId] })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}
