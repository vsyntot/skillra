import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import {
  fetchDatasetMeta,
  type DatasetMeta,
} from '../api/client'

export type { DatasetMeta } from '../api/client'

export function useDatasetMeta(): UseQueryResult<DatasetMeta, Error> {
  return useQuery<DatasetMeta, Error>({
    queryKey: ['dataset-meta'],
    queryFn: fetchDatasetMeta,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}
