import { useQuery } from '@tanstack/react-query'
import { fetchPersonaAnalysis, type PersonaAnalysisResponse, type PersonaProfile } from '../api/client'

interface UseSkillGapOptions {
  enabled?: boolean
}

/**
 * React Query hook for POST /v1/persona/analyze.
 * Profile must have at minimum name, description, current_skills, target_role.
 */
export function useSkillGap(profile: PersonaProfile | null, options: UseSkillGapOptions = {}) {
  const { enabled } = options
  return useQuery<PersonaAnalysisResponse, Error>({
    queryKey: ['skillGap', profile],
    queryFn: () => {
      if (!profile) throw new Error('Profile is required')
      return fetchPersonaAnalysis(profile)
    },
    enabled: enabled !== undefined ? enabled && profile !== null : profile !== null,
    staleTime: 5 * 60 * 1000, // 5 min
    retry: 1,
  })
}
