/**
 * useVacancySearch — React Query hook for vacancy search.
 * Sprint-008 TASK-05
 */
import { useQuery } from '@tanstack/react-query'
import { searchVacancies, VacancySearchResponse } from '../api/client'

interface SearchFilters {
  role?: string
  grade?: string
  country?: string
  region?: string
  city?: string
  geo_scope?: string
  skill?: string
  telegram_user_id?: number
  source?: string
}

export function useVacancySearch(
  query: string,
  filters: SearchFilters,
  pagination: { limit: number; offset: number },
) {
  return useQuery<VacancySearchResponse>({
    queryKey: ['vacancy-search', query, filters, pagination],
    queryFn: () => searchVacancies(query, filters, pagination),
    enabled: query.trim().length >= 1,
    staleTime: 30_000,
  })
}
