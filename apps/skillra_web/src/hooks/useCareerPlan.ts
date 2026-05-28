import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApplicationOutcomeIn,
  CareerActionIn,
  CareerActionPatch,
  CareerPlanGenerateActionsIn,
  CareerPlanIn,
  CareerPlanPatch,
  createCareerAction,
  fetchCareerPlan,
  generateCareerPlanActions,
  patchCareerAction,
  patchCareerPlan,
  saveCareerPlanVacancy,
  SavedVacancyIn,
  upsertCareerPlan,
  updateApplicationOutcome,
} from '../api/client'
import { nextBestActionKey } from './useNextBestAction'

const careerPlanKey = (telegramUserId: number) => ['careerPlan', telegramUserId] as const

export function useCareerPlan(telegramUserId: number) {
  return useQuery({
    queryKey: careerPlanKey(telegramUserId),
    queryFn: () => fetchCareerPlan(telegramUserId),
    enabled: telegramUserId > 0,
    retry: false,
  })
}

export function useUpsertCareerPlan(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CareerPlanIn) => upsertCareerPlan(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function usePatchCareerPlan(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CareerPlanPatch) => patchCareerPlan(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useCreateCareerAction(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CareerActionIn) => createCareerAction(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function usePatchCareerAction(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ actionId, payload }: { actionId: number; payload: CareerActionPatch }) =>
      patchCareerAction(telegramUserId, actionId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useGenerateCareerPlanActions(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CareerPlanGenerateActionsIn) => generateCareerPlanActions(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useSaveCareerPlanVacancy(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SavedVacancyIn) => saveCareerPlanVacancy(telegramUserId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}

export function useUpdateApplicationOutcome(telegramUserId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ actionId, payload }: { actionId: number; payload: ApplicationOutcomeIn }) =>
      updateApplicationOutcome(telegramUserId, actionId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: careerPlanKey(telegramUserId) })
      void queryClient.invalidateQueries({ queryKey: nextBestActionKey(telegramUserId) })
    },
  })
}
