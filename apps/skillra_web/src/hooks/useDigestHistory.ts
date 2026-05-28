/**
 * useDigestHistory — React Query hook for digest history.
 * Sprint-007 TASK-10
 */
import { useQuery } from '@tanstack/react-query'
import { fetchDigestHistory, fetchDigestPreview, DigestHistoryResponse, DigestPreviewResponse } from '../api/client'

export function useDigestHistory(telegramUserId: number, limit = 20, offset = 0) {
  return useQuery<DigestHistoryResponse>({
    queryKey: ['digest-history', telegramUserId, limit, offset],
    queryFn: () => fetchDigestHistory(telegramUserId, { limit, offset }),
    enabled: telegramUserId > 0,
  })
}

export function useDigestPreview(telegramUserId: number) {
  return useQuery<DigestPreviewResponse>({
    queryKey: ['digest-preview', telegramUserId],
    queryFn: () => fetchDigestPreview(telegramUserId, 'web'),
    enabled: false,
  })
}
