import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCohort,
  createOrganization,
  createOrganizationInvite,
  exportCohortAnalyticsCsv,
  fetchCohortAnalytics,
  fetchCohortMembers,
  fetchCohorts,
  fetchOrganizationMembers,
  fetchOrganizations,
  updateCohortMember,
  updateOrganizationMember,
  type CohortMemberPatch,
  type CohortIn,
  type OrganizationIn,
  type OrganizationInviteIn,
  type OrganizationMemberPatch,
} from '../api/client'

export const organizationsKey = ['organizations']
export const cohortsKey = (organizationId: number) => ['organizations', organizationId, 'cohorts']
export const membersKey = (organizationId: number) => ['organizations', organizationId, 'members']
export const cohortMembersKey = (organizationId: number, cohortId: number) => [
  'organizations',
  organizationId,
  'cohorts',
  cohortId,
  'members',
]
export const cohortAnalyticsKey = (organizationId: number, cohortId: number, days: number) => [
  'organizations',
  organizationId,
  'cohorts',
  cohortId,
  'analytics',
  days,
]

export function useOrganizations(enabled: boolean) {
  return useQuery({
    queryKey: organizationsKey,
    queryFn: fetchOrganizations,
    enabled,
    retry: false,
  })
}

export function useCreateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: OrganizationIn) => createOrganization(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationsKey })
    },
  })
}

export function useOrganizationMembers(organizationId: number, enabled: boolean) {
  return useQuery({
    queryKey: membersKey(organizationId),
    queryFn: () => fetchOrganizationMembers(organizationId),
    enabled: enabled && organizationId > 0,
    retry: false,
  })
}

export function useUpdateOrganizationMember(organizationId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: number; payload: OrganizationMemberPatch }) =>
      updateOrganizationMember(organizationId, userId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: membersKey(organizationId) })
      void queryClient.invalidateQueries({ queryKey: organizationsKey })
    },
  })
}

export function useCohorts(organizationId: number, enabled: boolean) {
  return useQuery({
    queryKey: cohortsKey(organizationId),
    queryFn: () => fetchCohorts(organizationId),
    enabled: enabled && organizationId > 0,
    retry: false,
  })
}

export function useCreateCohort(organizationId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: CohortIn) => createCohort(organizationId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cohortsKey(organizationId) })
    },
  })
}

export function useCohortMembers(organizationId: number, cohortId: number, enabled: boolean) {
  return useQuery({
    queryKey: cohortMembersKey(organizationId, cohortId),
    queryFn: () => fetchCohortMembers(organizationId, cohortId),
    enabled: enabled && organizationId > 0 && cohortId > 0,
    retry: false,
  })
}

export function useUpdateCohortMember(organizationId: number, cohortId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: number; payload: CohortMemberPatch }) =>
      updateCohortMember(organizationId, cohortId, userId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cohortsKey(organizationId) })
      void queryClient.invalidateQueries({ queryKey: cohortMembersKey(organizationId, cohortId) })
      void queryClient.invalidateQueries({ queryKey: ['organizations', organizationId, 'cohorts'] })
    },
  })
}

export function useCohortAnalytics(organizationId: number, cohortId: number, days: number, enabled: boolean) {
  return useQuery({
    queryKey: cohortAnalyticsKey(organizationId, cohortId, days),
    queryFn: () => fetchCohortAnalytics(organizationId, cohortId, days),
    enabled: enabled && organizationId > 0 && cohortId > 0,
    retry: false,
  })
}

export function useCreateOrganizationInvite(organizationId: number) {
  return useMutation({
    mutationFn: (payload: OrganizationInviteIn) => createOrganizationInvite(organizationId, payload),
  })
}

export function useExportCohortAnalyticsCsv(organizationId: number, cohortId: number, days: number) {
  return useMutation({
    mutationFn: () => exportCohortAnalyticsCsv(organizationId, cohortId, days),
  })
}
