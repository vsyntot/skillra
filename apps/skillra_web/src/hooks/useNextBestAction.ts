import { useQuery } from '@tanstack/react-query'
import { fetchNextBestAction } from '../api/client'

export const nextBestActionKey = (telegramUserId: number) => ['nextBestAction', telegramUserId] as const

export function useNextBestAction(telegramUserId: number) {
  return useQuery({
    queryKey: nextBestActionKey(telegramUserId),
    queryFn: () => fetchNextBestAction(telegramUserId, 'web'),
    enabled: telegramUserId > 0,
    retry: false,
  })
}
