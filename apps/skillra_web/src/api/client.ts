/**
 * Skillra API HTTP client.
 * Sends service or user session credentials on every request.
 */
import axios from 'axios'
import type { components } from './generated'
import { clearSession, getSession } from '../auth/TokenStore'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const PROTECTED_RUNTIME_ENVS = new Set(['prod', 'production', 'staging'])

interface RuntimeEnv {
  MODE?: string
  PROD?: boolean
  VITE_SKILLRA_API_TOKEN?: string
  VITE_SKILLRA_RUNTIME_ENV?: string
}

export function resolveFallbackServiceToken(env: RuntimeEnv): string | undefined {
  const runtimeEnv = String(env.VITE_SKILLRA_RUNTIME_ENV ?? env.MODE ?? '').toLowerCase()
  if (env.PROD || PROTECTED_RUNTIME_ENVS.has(runtimeEnv)) {
    return undefined
  }
  return env.VITE_SKILLRA_API_TOKEN || undefined
}

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
})

// Sprint-006 TASK-06: Add token dynamically on every request
apiClient.interceptors.request.use((config) => {
  const session = getSession()
  const fallbackServiceToken = resolveFallbackServiceToken(import.meta.env)

  if (session?.mode === 'user') {
    config.headers.Authorization = config.headers.Authorization ?? `Bearer ${session.token}`
  } else {
    const token = session?.token || fallbackServiceToken || ''
    if (token && !config.headers.Authorization) {
      config.headers['X-Skillra-Token'] = config.headers['X-Skillra-Token'] ?? token
    }
  }

  return config
})

const SESSION_INVALID_ERROR_CODES = new Set(['INVALID_USER_API_KEY', 'INVALID_SERVICE_TOKEN'])

export function shouldClearSessionOnAuthError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false
  const status = error.response?.status
  if (status === 401) return true
  if (status !== 403) return false
  return SESSION_INVALID_ERROR_CODES.has(apiErrorCode(error) ?? '')
}

function redirectToLogin(): void {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

// Redirect to /login only when the current session is actually invalid.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (shouldClearSessionOnAuthError(error)) {
      clearSession()
      redirectToLogin()
    }
    return Promise.reject(error)
  },
)

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ApiSchema<Name extends keyof components['schemas']> = components['schemas'][Name]
type WithRequiredArray<T, K extends keyof T> = Omit<T, K> & { [P in K]-?: NonNullable<T[P]> }

export type SegmentFilters = ApiSchema<'SegmentFilters'>
export type SegmentSummary = WithRequiredArray<ApiSchema<'SegmentSummary'>, 'warnings'>
export type PersonaProfile = ApiSchema<'PersonaProfile'>
export type SkillGapEntry = ApiSchema<'SkillGapEntry'>
export type MarketSummary = ApiSchema<'MarketSummary'>
export type PersonaAnalysisResponse = ApiSchema<'PersonaAnalysisResponse'>
export type UserProfileIn = ApiSchema<'UserProfileIn'>
export type UserProfileOut = WithRequiredArray<ApiSchema<'UserProfileOut'>, 'current_skills' | 'warnings'>
export type DigestHistoryItem = ApiSchema<'DigestHistoryItem'>
export type DigestHistoryResponse = WithRequiredArray<ApiSchema<'DigestHistoryResponse'>, 'items'>
export type DigestPreviewResponse = ApiSchema<'DigestPreviewResponse'>
export type VacancySearchResult = WithRequiredArray<
  ApiSchema<'VacancySearchResult'>,
  'skills' | 'matched_skills' | 'missing_skills'
>
export type VacancySearchResponse = Omit<ApiSchema<'VacancySearchResponse'>, 'results' | 'warnings'> & {
  results: VacancySearchResult[]
  warnings: string[]
}

export type DatasetMeta = ApiSchema<'DatasetMetaResponse'> & {
  last_updated: string | null
  records_count: number
  date_range_from?: string | null
  date_range_to?: string | null
}

export interface ShareLinkResponse {
  token: string
  expires_in: number
}

export interface CurrentUserResponse {
  telegram_user_id: number
  profile: UserProfileOut | null
}

export type WeeklySubscriptionIn = ApiSchema<'WeeklySubscriptionIn'>
export type WeeklySubscriptionOut = ApiSchema<'WeeklySubscriptionOut'>

export type CareerPlanStatus = NonNullable<ApiSchema<'CareerPlanIn'>['status']>
export type CareerActionType = NonNullable<ApiSchema<'CareerActionIn'>['action_type']>
export type CareerActionStatus = NonNullable<ApiSchema<'CareerActionIn'>['status']>
export type ApplicationOutcomeStatus = ApiSchema<'ApplicationOutcomeIn'>['status']

export type CareerPlanIn = ApiSchema<'CareerPlanIn'>
export type CareerPlanPatch = ApiSchema<'CareerPlanPatch'>
export type CareerActionIn = ApiSchema<'CareerActionIn'>
export type CareerActionPatch = ApiSchema<'CareerActionPatch'>
export type CareerPlanGenerateActionsIn = ApiSchema<'CareerPlanGenerateActionsIn'>
export type ApplicationOutcomeIn = ApiSchema<'ApplicationOutcomeIn'>
export type SavedVacancyIn = ApiSchema<'SavedVacancyIn'>
export type CareerActionOut = ApiSchema<'CareerActionOut'>
export type CareerPlanOut = Omit<ApiSchema<'CareerPlanOut'>, 'actions'> & { actions: CareerActionOut[] }
export type TrendDataPoint = ApiSchema<'TrendDataPoint'>
export type SalaryTrendOut = WithRequiredArray<ApiSchema<'SalaryTrendOut'>, 'data'>
export type SkillDemandTrendOut = WithRequiredArray<ApiSchema<'SkillDemandTrendOut'>, 'data'>
export type VacancyCountTrendOut = WithRequiredArray<ApiSchema<'VacancyCountTrendOut'>, 'data'>
export type CareerTrajectoryOut = WithRequiredArray<ApiSchema<'CareerTrajectoryOut'>, 'skills_to_add'>
export type CareerTransitionOut = WithRequiredArray<ApiSchema<'CareerTransitionOut'>, 'skills_to_add'> & {
  demand_trend: string
}
export type CareerGraphOut = Omit<ApiSchema<'CareerGraphOut'>, 'transitions'> & {
  transitions: CareerTransitionOut[]
}
export type ResumeUploadOut = WithRequiredArray<ApiSchema<'ResumeUploadOut'>, 'extracted_skills'>
export type ResumeStatusOut = WithRequiredArray<ApiSchema<'ResumeStatusOut'>, 'extracted_skills'>
export type NextBestActionOut = ApiSchema<'NextBestActionOut'>
export type EvidenceExplainerOut = WithRequiredArray<
  ApiSchema<'EvidenceExplainerOut'>,
  'bullets' | 'evidence_refs' | 'uncertainties' | 'blocked_claims'
>
export type UserApiKeyStatusOut = ApiSchema<'UserApiKeyStatusOut'>
export type UserApiKeyRevokeOut = ApiSchema<'UserApiKeyRevokeOut'>
export type CommercialStateOut = WithRequiredArray<ApiSchema<'CommercialStateOut'>, 'entitlements' | 'locked_features'>
export type OrganizationIn = ApiSchema<'OrganizationIn'>
export type OrganizationOut = ApiSchema<'OrganizationOut'>
export type OrganizationMemberOut = ApiSchema<'OrganizationMemberOut'>
export type OrganizationMemberPatch = ApiSchema<'OrganizationMemberPatch'>
export type CohortIn = ApiSchema<'CohortIn'>
export type CohortOut = ApiSchema<'CohortOut'>
export type CohortMemberOut = ApiSchema<'CohortMemberOut'>
export type CohortMemberPatch = ApiSchema<'CohortMemberPatch'>
export type OrganizationInviteIn = ApiSchema<'OrganizationInviteIn'>
export type OrganizationInviteOut = ApiSchema<'OrganizationInviteOut'>
export type CohortAnalyticsOut = ApiSchema<'CohortAnalyticsOut'>
export type ProductEventSurface = 'api' | 'web' | 'bot' | 'worker' | 'digest' | 'admin' | 'user' | 'system'

export interface ProductEventIn {
  event_name: string
  surface?: ProductEventSurface
  entity_type?: string | null
  entity_id?: string | null
  session_id?: string | null
  correlation_id?: string | null
  metadata?: Record<string, unknown>
  occurred_at?: string | null
}

function normalizeSegmentSummary(data: ApiSchema<'SegmentSummary'>): SegmentSummary {
  return { ...data, warnings: Array.isArray(data.warnings) ? data.warnings : [] }
}

function normalizeUserProfile(data: ApiSchema<'UserProfileOut'>): UserProfileOut {
  return {
    ...data,
    current_skills: Array.isArray(data.current_skills) ? data.current_skills : [],
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
  }
}

function normalizeCareerPlan(data: ApiSchema<'CareerPlanOut'>): CareerPlanOut {
  return { ...data, actions: Array.isArray(data.actions) ? data.actions : [] }
}

function normalizeDigestHistory(data: ApiSchema<'DigestHistoryResponse'>): DigestHistoryResponse {
  return { ...data, items: Array.isArray(data.items) ? data.items : [] }
}

function normalizeVacancySearch(data: ApiSchema<'VacancySearchResponse'>): VacancySearchResponse {
  return {
    ...data,
    results: (data.results ?? []).map((result) => ({
      ...result,
      skills: Array.isArray(result.skills) ? result.skills : [],
      matched_skills: Array.isArray(result.matched_skills) ? result.matched_skills : [],
      missing_skills: Array.isArray(result.missing_skills) ? result.missing_skills : [],
    })),
    warnings: Array.isArray(data.warnings) ? data.warnings : [],
  }
}

function normalizeCareerTrajectory(data: ApiSchema<'CareerTrajectoryOut'>): CareerTrajectoryOut {
  return { ...data, skills_to_add: Array.isArray(data.skills_to_add) ? data.skills_to_add : [] }
}

function normalizeCareerGraph(data: ApiSchema<'CareerGraphOut'>): CareerGraphOut {
  return {
    ...data,
    transitions: (data.transitions ?? []).map((transition) => ({
      ...transition,
      demand_trend: transition.demand_trend ?? 'stable',
      skills_to_add: Array.isArray(transition.skills_to_add) ? transition.skills_to_add : [],
    })),
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchSegmentSummary(filters: SegmentFilters): Promise<SegmentSummary> {
  const { data } = await apiClient.post<ApiSchema<'SegmentSummary'>>('/v1/market/segment-summary', filters)
  return normalizeSegmentSummary(data)
}

export async function fetchPersonaAnalysis(profile: PersonaProfile): Promise<PersonaAnalysisResponse> {
  const { data } = await apiClient.post<PersonaAnalysisResponse>('/v1/persona/analyze', profile)
  return data
}

export async function fetchMetaRoles(): Promise<string[]> {
  const { data } = await apiClient.get<{ roles: string[] }>('/v1/meta/roles')
  return data.roles
}

export async function fetchMetaGrades(): Promise<string[]> {
  const { data } = await apiClient.get<{ grades: string[] }>('/v1/meta/grades')
  return data.grades
}

export async function fetchMetaCityTiers(): Promise<string[]> {
  const { data } = await apiClient.get<{ city_tiers?: string[] }>('/v1/meta/city-tiers')
  return data.city_tiers ?? []
}

export async function fetchMetaCountries(): Promise<string[]> {
  const { data } = await apiClient.get<{ countries?: string[] }>('/v1/meta/countries')
  return data.countries ?? []
}

export async function fetchMetaRegions(): Promise<string[]> {
  const { data } = await apiClient.get<{ regions?: string[] }>('/v1/meta/regions')
  return data.regions ?? []
}

export async function fetchMetaCities(): Promise<string[]> {
  const { data } = await apiClient.get<{ cities?: string[] }>('/v1/meta/cities')
  return data.cities ?? []
}

export async function fetchMetaGeoScopes(): Promise<string[]> {
  const { data } = await apiClient.get<{ geo_scopes?: string[] }>('/v1/meta/geo-scopes')
  return data.geo_scopes ?? []
}

export async function fetchMetaWorkModes(): Promise<string[]> {
  const { data } = await apiClient.get<{ work_modes?: string[] }>('/v1/meta/work-modes')
  return data.work_modes ?? []
}

export async function fetchMetaDomains(): Promise<string[]> {
  const { data } = await apiClient.get<{ domains?: string[] }>('/v1/meta/domains')
  return data.domains ?? []
}

export async function fetchMetaSkills(params: { limit?: number; offset?: number; search?: string } = {}): Promise<string[]> {
  const { data } = await apiClient.get<{ skills?: string[] }>('/v1/meta/skills', { params })
  return data.skills ?? []
}

export async function fetchDatasetMeta(): Promise<DatasetMeta> {
  const { data } = await apiClient.get<DatasetMeta & {
    last_updated?: string | null
    records_count?: number | null
  }>('/v1/meta/dataset')

  return {
    ...data,
    last_updated: data.last_updated ?? data.date_range_to ?? data.created_at ?? null,
    records_count: data.records_count ?? data.vacancy_count ?? 0,
  }
}

export async function fetchCurrentUser(): Promise<CurrentUserResponse> {
  const { data } = await apiClient.get<{ telegram_user_id: number; profile?: ApiSchema<'UserProfileOut'> | null }>(
    '/v1/users/me',
  )
  return {
    telegram_user_id: data.telegram_user_id,
    profile: data.profile ? normalizeUserProfile(data.profile) : null,
  }
}

export async function fetchProfile(telegramUserId: number): Promise<UserProfileOut> {
  const { data } = await apiClient.get<ApiSchema<'UserProfileOut'>>(`/v1/users/${telegramUserId}/profile`)
  return normalizeUserProfile(data)
}

export async function updateProfile(telegramUserId: number, payload: UserProfileIn): Promise<UserProfileOut> {
  const { data } = await apiClient.put<ApiSchema<'UserProfileOut'>>(
    `/v1/users/${telegramUserId}/profile`,
    { ...payload, source: payload.source ?? 'web' },
  )
  return normalizeUserProfile(data)
}

export async function deleteProfile(telegramUserId: number): Promise<void> {
  await apiClient.delete(`/v1/users/${telegramUserId}/profile`)
}

export async function fetchCurrentApiKeyStatus(): Promise<UserApiKeyStatusOut> {
  const { data } = await apiClient.get<UserApiKeyStatusOut>('/v1/users/me/api-key')
  return data
}

export async function revokeCurrentApiKey(source = 'web'): Promise<UserApiKeyRevokeOut> {
  const { data } = await apiClient.delete<UserApiKeyRevokeOut>('/v1/users/me/api-key', {
    params: { source },
  })
  return data
}

export async function fetchNextBestAction(telegramUserId: number, source = 'web'): Promise<NextBestActionOut> {
  const { data } = await apiClient.get<NextBestActionOut>(`/v1/users/${telegramUserId}/next-best-action`, {
    params: { source },
  })
  return data
}

export async function fetchEvidenceExplainer(telegramUserId: number): Promise<EvidenceExplainerOut> {
  const { data } = await apiClient.get<EvidenceExplainerOut>(`/v1/users/${telegramUserId}/evidence-explainer`, {
    params: { task: 'skill_gap_explanation', surface: 'web' },
  })
  return {
    ...data,
    bullets: Array.isArray(data.bullets) ? data.bullets : [],
    evidence_refs: Array.isArray(data.evidence_refs) ? data.evidence_refs : [],
    uncertainties: Array.isArray(data.uncertainties) ? data.uncertainties : [],
    blocked_claims: Array.isArray(data.blocked_claims) ? data.blocked_claims : [],
  }
}

export async function fetchCommercialState(telegramUserId: number): Promise<CommercialStateOut> {
  const { data } = await apiClient.get<ApiSchema<'CommercialStateOut'>>(
    `/v1/users/${telegramUserId}/commercial-state`,
  )
  return {
    ...data,
    entitlements: Array.isArray(data.entitlements) ? data.entitlements : [],
    locked_features: Array.isArray(data.locked_features) ? data.locked_features : [],
  }
}

export async function fetchOrganizations(): Promise<OrganizationOut[]> {
  const { data } = await apiClient.get<OrganizationOut[]>('/v1/organizations')
  return data
}

export async function createOrganization(payload: OrganizationIn): Promise<OrganizationOut> {
  const { data } = await apiClient.post<OrganizationOut>('/v1/organizations', payload)
  return data
}

export async function fetchOrganizationMembers(organizationId: number): Promise<OrganizationMemberOut[]> {
  const { data } = await apiClient.get<OrganizationMemberOut[]>(`/v1/organizations/${organizationId}/members`)
  return data
}

export async function updateOrganizationMember(
  organizationId: number,
  memberUserId: number,
  payload: OrganizationMemberPatch,
): Promise<OrganizationMemberOut> {
  const { data } = await apiClient.patch<OrganizationMemberOut>(
    `/v1/organizations/${organizationId}/members/${memberUserId}`,
    payload,
  )
  return data
}

export async function fetchCohorts(organizationId: number): Promise<CohortOut[]> {
  const { data } = await apiClient.get<CohortOut[]>(`/v1/organizations/${organizationId}/cohorts`)
  return data
}

export async function createCohort(organizationId: number, payload: CohortIn): Promise<CohortOut> {
  const { data } = await apiClient.post<CohortOut>(`/v1/organizations/${organizationId}/cohorts`, payload)
  return data
}

export async function fetchCohortMembers(organizationId: number, cohortId: number): Promise<CohortMemberOut[]> {
  const { data } = await apiClient.get<CohortMemberOut[]>(
    `/v1/organizations/${organizationId}/cohorts/${cohortId}/members`,
  )
  return data
}

export async function updateCohortMember(
  organizationId: number,
  cohortId: number,
  memberUserId: number,
  payload: CohortMemberPatch,
): Promise<CohortMemberOut> {
  const { data } = await apiClient.patch<CohortMemberOut>(
    `/v1/organizations/${organizationId}/cohorts/${cohortId}/members/${memberUserId}`,
    payload,
  )
  return data
}

export async function fetchCohortAnalytics(
  organizationId: number,
  cohortId: number,
  days = 30,
): Promise<CohortAnalyticsOut> {
  const { data } = await apiClient.get<CohortAnalyticsOut>(
    `/v1/organizations/${organizationId}/cohorts/${cohortId}/analytics`,
    { params: { days } },
  )
  return data
}

export async function exportCohortAnalyticsCsv(organizationId: number, cohortId: number, days = 30): Promise<Blob> {
  const response = await apiClient.get(`/v1/organizations/${organizationId}/cohorts/${cohortId}/export.csv`, {
    params: { days },
    responseType: 'blob',
  })
  return response.data as Blob
}

export async function createOrganizationInvite(
  organizationId: number,
  payload: OrganizationInviteIn,
): Promise<OrganizationInviteOut> {
  const { data } = await apiClient.post<OrganizationInviteOut>(
    `/v1/organizations/${organizationId}/invites`,
    payload,
  )
  return data
}

export async function revokeOrganizationInvite(
  organizationId: number,
  inviteId: number,
): Promise<OrganizationInviteOut> {
  const { data } = await apiClient.delete<OrganizationInviteOut>(
    `/v1/organizations/${organizationId}/invites/${inviteId}`,
  )
  return data
}

export async function createProductEvent(telegramUserId: number, payload: ProductEventIn): Promise<void> {
  await apiClient.post(`/v1/users/${telegramUserId}/product-events`, {
    ...payload,
    surface: payload.surface ?? 'web',
    metadata: payload.metadata ?? {},
  })
}

export function trackProductEvent(telegramUserId: number, payload: ProductEventIn): void {
  if (telegramUserId <= 0) return
  void createProductEvent(telegramUserId, payload).catch(() => undefined)
}

export function apiErrorCode(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null
  const payload = error.response?.data
  if (payload && typeof payload === 'object') {
    const direct = 'error_code' in payload ? payload.error_code : undefined
    const detail = 'detail' in payload ? payload.detail : undefined
    if (typeof direct === 'string') return direct
    if (detail && typeof detail === 'object' && 'error_code' in detail && typeof detail.error_code === 'string') {
      return detail.error_code
    }
  }
  return null
}

export function apiErrorMessage(error: unknown): string | null {
  if (!axios.isAxiosError(error)) return null
  const payload = error.response?.data
  if (payload && typeof payload === 'object') {
    const direct = 'message' in payload ? payload.message : undefined
    const detail = 'detail' in payload ? payload.detail : undefined
    if (typeof direct === 'string') return direct
    if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') {
      return detail.message
    }
  }
  return null
}

export async function fetchUserResume(telegramUserId: number): Promise<ResumeStatusOut> {
  const { data } = await apiClient.get<ApiSchema<'ResumeStatusOut'>>(`/v1/users/${telegramUserId}/resume`)
  return { ...data, extracted_skills: Array.isArray(data.extracted_skills) ? data.extracted_skills : [] }
}

export async function uploadUserResume(telegramUserId: number, file: File): Promise<ResumeUploadOut> {
  const { data } = await apiClient.post<ApiSchema<'ResumeUploadOut'>>(
    `/v1/users/${telegramUserId}/resume`,
    file,
    {
      headers: { 'Content-Type': 'application/pdf' },
      params: { filename: file.name || 'resume.pdf' },
    },
  )
  return { ...data, extracted_skills: Array.isArray(data.extracted_skills) ? data.extracted_skills : [] }
}

export async function fetchWeeklySubscription(telegramUserId: number): Promise<WeeklySubscriptionOut> {
  const { data } = await apiClient.get<WeeklySubscriptionOut>(`/v1/users/${telegramUserId}/subscriptions/weekly`)
  return data
}

export async function upsertWeeklySubscription(
  telegramUserId: number,
  payload: WeeklySubscriptionIn,
): Promise<WeeklySubscriptionOut> {
  const { data } = await apiClient.put<WeeklySubscriptionOut>(
    `/v1/users/${telegramUserId}/subscriptions/weekly`,
    { ...payload, source: 'web' },
  )
  return data
}

export async function deleteWeeklySubscription(telegramUserId: number, source = 'web'): Promise<void> {
  await apiClient.delete(`/v1/users/${telegramUserId}/subscriptions/weekly`, { params: { source } })
}

export async function fetchCareerPlan(telegramUserId: number): Promise<CareerPlanOut | null> {
  const response = await apiClient.get<ApiSchema<'CareerPlanOut'>>(`/v1/users/${telegramUserId}/career-plan`, {
    validateStatus: (status) => (status >= 200 && status < 300) || status === 404,
  })

  if (response.status === 404) {
    return null
  }

  return normalizeCareerPlan(response.data)
}

export async function upsertCareerPlan(
  telegramUserId: number,
  payload: CareerPlanIn,
): Promise<CareerPlanOut> {
  const { data } = await apiClient.put<ApiSchema<'CareerPlanOut'>>(
    `/v1/users/${telegramUserId}/career-plan`,
    { ...payload, source: 'web' },
  )
  return normalizeCareerPlan(data)
}

export async function patchCareerPlan(
  telegramUserId: number,
  payload: CareerPlanPatch,
): Promise<CareerPlanOut> {
  const { data } = await apiClient.patch<ApiSchema<'CareerPlanOut'>>(
    `/v1/users/${telegramUserId}/career-plan`,
    { ...payload, source: 'web' },
  )
  return normalizeCareerPlan(data)
}

export async function createCareerAction(
  telegramUserId: number,
  payload: CareerActionIn,
): Promise<CareerActionOut> {
  const { data } = await apiClient.post<CareerActionOut>(
    `/v1/users/${telegramUserId}/career-plan/actions`,
    { ...payload, source: payload.source ?? 'web' },
  )
  return data
}

export async function patchCareerAction(
  telegramUserId: number,
  actionId: number,
  payload: CareerActionPatch,
): Promise<CareerActionOut> {
  const { data } = await apiClient.patch<CareerActionOut>(
    `/v1/users/${telegramUserId}/career-plan/actions/${actionId}`,
    { ...payload, source: 'web' },
  )
  return data
}

export async function generateCareerPlanActions(
  telegramUserId: number,
  payload: CareerPlanGenerateActionsIn,
): Promise<CareerPlanOut> {
  const { data } = await apiClient.post<ApiSchema<'CareerPlanOut'>>(
    `/v1/users/${telegramUserId}/career-plan/generate-actions`,
    { ...payload, source: payload.source ?? 'web' },
  )
  return normalizeCareerPlan(data)
}

export async function saveCareerPlanVacancy(
  telegramUserId: number,
  payload: SavedVacancyIn,
): Promise<CareerActionOut> {
  const { data } = await apiClient.post<CareerActionOut>(
    `/v1/users/${telegramUserId}/career-plan/saved-vacancies`,
    { ...payload, source: payload.source ?? 'web' },
  )
  return data
}

export async function updateApplicationOutcome(
  telegramUserId: number,
  actionId: number,
  payload: ApplicationOutcomeIn,
): Promise<CareerActionOut> {
  const { data } = await apiClient.post<CareerActionOut>(
    `/v1/users/${telegramUserId}/career-plan/actions/${actionId}/outcome`,
    { ...payload, source: payload.source ?? 'web' },
  )
  return data
}

// Sprint-007 TASK-10
export async function fetchDigestHistory(
  telegramUserId: number,
  params: { limit: number; offset: number },
): Promise<DigestHistoryResponse> {
  const { data } = await apiClient.get<ApiSchema<'DigestHistoryResponse'>>(
    `/v1/users/${telegramUserId}/digest/history`,
    { params },
  )
  return normalizeDigestHistory(data)
}

export async function fetchDigestPreview(telegramUserId: number, source = 'web'): Promise<DigestPreviewResponse> {
  const { data } = await apiClient.post<DigestPreviewResponse>(
    `/v1/users/${telegramUserId}/digest-preview`,
    undefined,
    { params: { source } },
  )
  return data
}

// Sprint-008 TASK-06 frontend
export async function exportSkillGapCsv(profile: PersonaProfile): Promise<Blob> {
  const response = await apiClient.post('/v1/persona/export-csv', profile, { responseType: 'blob' })
  return response.data as Blob
}

export async function exportSkillGapPdf(profile: PersonaProfile): Promise<Blob> {
  const response = await apiClient.post('/v1/persona/export-pdf', profile, { responseType: 'blob' })
  return response.data as Blob
}

export async function createShareLink(profile: PersonaProfile): Promise<ShareLinkResponse> {
  const { data } = await apiClient.post<ShareLinkResponse>('/v1/persona/share', profile)
  return data
}

export async function getSharedAnalysis(token: string): Promise<PersonaAnalysisResponse> {
  const { data } = await apiClient.get<PersonaAnalysisResponse>(`/v1/persona/share/${token}`)
  return data
}

// Sprint-008 TASK-05
export async function searchVacancies(
  query: string,
  filters: {
    role?: string
    grade?: string
    country?: string
    region?: string
    city?: string
    geo_scope?: string
    skill?: string
    telegram_user_id?: number
    source?: string
  },
  pagination: { limit: number; offset: number },
): Promise<VacancySearchResponse> {
  const { data } = await apiClient.get<ApiSchema<'VacancySearchResponse'>>('/v1/search/vacancies', {
    params: { q: query, ...filters, ...pagination },
  })
  return normalizeVacancySearch(data)
}

export async function fetchSalaryTrend(
  role: string,
  grade: string,
  weeks = 12,
): Promise<SalaryTrendOut> {
  const { data } = await apiClient.get<ApiSchema<'SalaryTrendOut'>>('/v1/market/trends/salary', {
    params: { role, grade, weeks },
  })
  return { ...data, data: Array.isArray(data.data) ? data.data : [] }
}

export async function fetchSkillDemandTrend(
  skill: string,
  role?: string,
  weeks = 12,
): Promise<SkillDemandTrendOut> {
  const { data } = await apiClient.get<ApiSchema<'SkillDemandTrendOut'>>('/v1/market/trends/skill-demand', {
    params: { skill, role: role || undefined, weeks },
  })
  return { ...data, data: Array.isArray(data.data) ? data.data : [] }
}

export async function fetchVacancyCountTrend(
  role: string,
  grade?: string,
  weeks = 12,
): Promise<VacancyCountTrendOut> {
  const { data } = await apiClient.get<ApiSchema<'VacancyCountTrendOut'>>('/v1/market/trends/vacancy-count', {
    params: { role, grade: grade || undefined, weeks },
  })
  return { ...data, data: Array.isArray(data.data) ? data.data : [] }
}

export async function fetchCareerTrajectory(
  role: string,
  grade: string,
): Promise<CareerTrajectoryOut> {
  const { data } = await apiClient.get<ApiSchema<'CareerTrajectoryOut'>>('/v1/persona/career-trajectory', {
    params: { role, grade },
  })
  return normalizeCareerTrajectory(data)
}

export async function fetchCareerGraph(role: string): Promise<CareerGraphOut> {
  const { data } = await apiClient.get<ApiSchema<'CareerGraphOut'>>('/v1/market/career-graph', {
    params: { role },
  })
  return normalizeCareerGraph(data)
}
