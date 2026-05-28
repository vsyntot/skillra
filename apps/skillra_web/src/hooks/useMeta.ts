import { useQuery } from '@tanstack/react-query'
import {
  fetchMetaCities,
  fetchMetaCityTiers,
  fetchMetaCountries,
  fetchMetaDomains,
  fetchMetaGeoScopes,
  fetchMetaGrades,
  fetchMetaRegions,
  fetchMetaRoles,
  fetchMetaSkills,
  fetchMetaWorkModes,
} from '../api/client'

export type MetaKind =
  | 'roles'
  | 'grades'
  | 'cityTiers'
  | 'countries'
  | 'regions'
  | 'cities'
  | 'geoScopes'
  | 'workModes'
  | 'domains'
  | 'skills'

interface UseMetaOptions {
  search?: string
  limit?: number
  enabled?: boolean
}

export function useMeta(kind: MetaKind, options: UseMetaOptions = {}) {
  const { enabled = true, limit = kind === 'skills' ? 100 : undefined, search } = options

  return useQuery<string[]>({
    queryKey: ['meta', kind, limit, search],
    queryFn: () => {
      switch (kind) {
        case 'roles':
          return fetchMetaRoles()
        case 'grades':
          return fetchMetaGrades()
        case 'cityTiers':
          return fetchMetaCityTiers()
        case 'countries':
          return fetchMetaCountries()
        case 'regions':
          return fetchMetaRegions()
        case 'cities':
          return fetchMetaCities()
        case 'geoScopes':
          return fetchMetaGeoScopes()
        case 'workModes':
          return fetchMetaWorkModes()
        case 'domains':
          return fetchMetaDomains()
        case 'skills':
          return fetchMetaSkills({ limit, search: search || undefined })
      }
    },
    enabled,
    staleTime: 10 * 60 * 1000,
  })
}
