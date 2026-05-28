import { useQuery } from '@tanstack/react-query'
import { fetchEvidenceExplainer } from '../api/client'

export const evidenceExplainerKey = (telegramUserId: number) => ['evidenceExplainer', telegramUserId] as const

export function useEvidenceExplainer(telegramUserId: number, enabled: boolean) {
  return useQuery({
    queryKey: evidenceExplainerKey(telegramUserId),
    queryFn: () => fetchEvidenceExplainer(telegramUserId),
    enabled: enabled && telegramUserId > 0,
    retry: false,
  })
}
