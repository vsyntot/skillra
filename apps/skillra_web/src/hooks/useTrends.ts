import { useQuery, type UseQueryResult } from '@tanstack/react-query'
import {
  fetchCareerGraph,
  fetchCareerTrajectory,
  fetchSalaryTrend,
  fetchSkillDemandTrend,
  fetchVacancyCountTrend,
  type CareerGraphOut,
  type CareerTrajectoryOut,
  type SalaryTrendOut,
  type SkillDemandTrendOut,
  type VacancyCountTrendOut,
} from '../api/client'

const DEFAULT_WEEKS = 12
const TREND_STALE_TIME_MS = 5 * 60 * 1000

export function useSalaryTrend(
  role: string,
  grade: string,
  weeks = DEFAULT_WEEKS,
): UseQueryResult<SalaryTrendOut, Error> {
  const enabled = role.trim().length > 0 && grade.trim().length > 0

  return useQuery<SalaryTrendOut, Error>({
    queryKey: ['trends', 'salary', role, grade, weeks],
    queryFn: () => fetchSalaryTrend(role, grade, weeks),
    enabled,
    staleTime: TREND_STALE_TIME_MS,
    retry: 1,
  })
}

export function useSkillDemandTrend(
  skill: string,
  role?: string,
  weeks = DEFAULT_WEEKS,
): UseQueryResult<SkillDemandTrendOut, Error> {
  const enabled = skill.trim().length > 0

  return useQuery<SkillDemandTrendOut, Error>({
    queryKey: ['trends', 'skill-demand', skill, role || null, weeks],
    queryFn: () => fetchSkillDemandTrend(skill, role, weeks),
    enabled,
    staleTime: TREND_STALE_TIME_MS,
    retry: 1,
  })
}

export function useVacancyCountTrend(
  role: string,
  grade?: string,
  weeks = DEFAULT_WEEKS,
): UseQueryResult<VacancyCountTrendOut, Error> {
  const enabled = role.trim().length > 0

  return useQuery<VacancyCountTrendOut, Error>({
    queryKey: ['trends', 'vacancy-count', role, grade || null, weeks],
    queryFn: () => fetchVacancyCountTrend(role, grade, weeks),
    enabled,
    staleTime: TREND_STALE_TIME_MS,
    retry: 1,
  })
}

export function useCareerTrajectory(
  role: string,
  grade: string,
): UseQueryResult<CareerTrajectoryOut, Error> {
  const enabled = role.trim().length > 0 && grade.trim().length > 0

  return useQuery<CareerTrajectoryOut, Error>({
    queryKey: ['career-trajectory', role, grade],
    queryFn: () => fetchCareerTrajectory(role, grade),
    enabled,
    staleTime: TREND_STALE_TIME_MS,
    retry: 1,
  })
}

export function useCareerGraph(role: string): UseQueryResult<CareerGraphOut, Error> {
  const enabled = role.trim().length > 0

  return useQuery<CareerGraphOut, Error>({
    queryKey: ['career-graph', role],
    queryFn: () => fetchCareerGraph(role),
    enabled,
    staleTime: TREND_STALE_TIME_MS,
    retry: 1,
  })
}
