import { useQuery } from '@tanstack/react-query'
import { fetchCommercialState } from '../api/client'

export function useCommercialState(telegramUserId: number) {
  return useQuery({
    queryKey: ['commercial-state', telegramUserId],
    queryFn: () => fetchCommercialState(telegramUserId),
    enabled: telegramUserId > 0,
    retry: false,
  })
}
