import { useQuery } from '@tanstack/react-query'
import { fetchSegmentSummary, type SegmentFilters, type SegmentSummary } from '../api/client'

/**
 * React Query hook for POST /v1/market/segment-summary.
 */
export function useMarket(filters: SegmentFilters | null) {
  return useQuery<SegmentSummary, Error>({
    queryKey: ['market', filters],
    queryFn: () => {
      if (!filters) throw new Error('Filters are required')
      return fetchSegmentSummary(filters)
    },
    enabled: filters !== null,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}
