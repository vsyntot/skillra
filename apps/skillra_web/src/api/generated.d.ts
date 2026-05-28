/**
 * Generated from FastAPI OpenAPI schema.
 * Run `npm run generate:api` to update.
 */
export interface paths {
  "/health": {
    get: {
      parameters: never
      responses: {
        200: Record<string, unknown>
      }
    }
  }
  "/": {
    get: {
      parameters: never
      responses: {
        200: Record<string, unknown>
      }
    }
  }
  "/v1/auth/check": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: Record<string, string>
      }
    }
  }
  "/v1/health": {
    get: {
      parameters: never
      responses: {
        200: unknown
      }
    }
  }
  "/v1/ready": {
    get: {
      parameters: never
      responses: {
        200: unknown
      }
    }
  }
  "/v1/meta/roles": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaRolesResponse"]
      }
    }
  }
  "/v1/meta/grades": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaGradesResponse"]
      }
    }
  }
  "/v1/meta/city-tiers": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaCityTiersResponse"]
      }
    }
  }
  "/v1/meta/countries": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaCountriesResponse"]
      }
    }
  }
  "/v1/meta/regions": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaRegionsResponse"]
      }
    }
  }
  "/v1/meta/cities": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaCitiesResponse"]
      }
    }
  }
  "/v1/meta/work-modes": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaWorkModesResponse"]
      }
    }
  }
  "/v1/meta/geo-scopes": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaGeoScopesResponse"]
      }
    }
  }
  "/v1/meta/domains": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["MetaDomainsResponse"]
      }
    }
  }
  "/v1/meta/skills": {
    get: {
      parameters: {
      query: {
        "limit"?: number
        "offset"?: number
        "search"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["PaginatedMetaSkillsResponse"]
      }
    }
  }
  "/v1/meta/dataset": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DatasetMetaResponse"]
      }
    }
  }
  "/v1/market/segment-summary": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["SegmentSummary"]
      }
    }
  }
  "/v1/market/trends/salary": {
    get: {
      parameters: {
      query: {
        "role": string
        "grade": string
        "weeks"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["SalaryTrendOut"]
      }
    }
  }
  "/v1/market/trends/skill-demand": {
    get: {
      parameters: {
      query: {
        "skill": string
        "role"?: string | null
        "grade"?: string | null
        "weeks"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["SkillDemandTrendOut"]
      }
    }
  }
  "/v1/market/trends/vacancy-count": {
    get: {
      parameters: {
      query: {
        "role": string
        "grade"?: string | null
        "weeks"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["VacancyCountTrendOut"]
      }
    }
  }
  "/v1/market/career-graph": {
    get: {
      parameters: {
      query: {
        "role": string
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerGraphOut"]
      }
    }
  }
  "/v1/organizations": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationOut"]
      }
    }
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationOut"][]
      }
    }
  }
  "/v1/organizations/{organization_id}": {
    get: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationOut"]
      }
    }
    patch: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationOut"]
      }
    }
  }
  "/v1/organizations/{organization_id}/members": {
    get: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationMemberOut"][]
      }
    }
  }
  "/v1/organizations/{organization_id}/members/{member_user_id}": {
    patch: {
      parameters: {
      path: {
        "organization_id": number
        "member_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationMemberOut"]
      }
    }
  }
  "/v1/organizations/{organization_id}/cohorts": {
    post: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CohortOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CohortOut"][]
      }
    }
  }
  "/v1/organizations/{organization_id}/cohorts/{cohort_id}/members": {
    get: {
      parameters: {
      path: {
        "organization_id": number
        "cohort_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CohortMemberOut"][]
      }
    }
  }
  "/v1/organizations/{organization_id}/cohorts/{cohort_id}/members/{member_user_id}": {
    patch: {
      parameters: {
      path: {
        "organization_id": number
        "cohort_id": number
        "member_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CohortMemberOut"]
      }
    }
  }
  "/v1/organizations/{organization_id}/invites": {
    post: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationInviteOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "organization_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationInviteOut"][]
      }
    }
  }
  "/v1/organizations/{organization_id}/invites/{invite_id}": {
    delete: {
      parameters: {
      path: {
        "organization_id": number
        "invite_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["OrganizationInviteOut"]
      }
    }
  }
  "/v1/invites/{invite_token}/accept": {
    post: {
      parameters: {
      path: {
        "invite_token": string
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["InviteAcceptOut"]
      }
    }
  }
  "/v1/organizations/{organization_id}/cohorts/{cohort_id}/analytics": {
    get: {
      parameters: {
      path: {
        "organization_id": number
        "cohort_id": number
      }
      query: {
        "days"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CohortAnalyticsOut"]
      }
    }
  }
  "/v1/organizations/{organization_id}/cohorts/{cohort_id}/export.csv": {
    get: {
      parameters: {
      path: {
        "organization_id": number
        "cohort_id": number
      }
      query: {
        "days"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/persona/analyze": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["PersonaAnalysisResponse"]
      }
    }
  }
  "/v1/persona/career-trajectory": {
    get: {
      parameters: {
      query: {
        "role": string
        "grade": string
        "skills"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerTrajectoryOut"]
      }
    }
  }
  "/v1/persona/export-csv": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/persona/skill-gap-chart": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/persona/export-pdf": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/persona/share": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/persona/share/{share_token}": {
    get: {
      parameters: {
      path: {
        "share_token": string
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/admin/reload-data": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/admin/index-meilisearch": {
    post: {
      parameters: {
      query: {
        "force"?: boolean
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/admin/indexer-status": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["IndexerStatusOut"]
      }
    }
  }
  "/v1/admin/data-runs/{run_id}/state": {
    post: {
      parameters: {
      path: {
        "run_id": string
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DataRunOut"]
      }
    }
  }
  "/v1/admin/data-runs/{run_id}/activate": {
    post: {
      parameters: {
      path: {
        "run_id": string
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ActiveDatasetStatusOut"]
      }
    }
  }
  "/v1/admin/data-runs/latest": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DataRunStatusOut"]
      }
    }
  }
  "/v1/admin/data-runs/active": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ActiveDatasetStatusOut"]
      }
    }
  }
  "/v1/admin/data-runs": {
    get: {
      parameters: {
      query: {
        "limit"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DataRunOut"][]
      }
    }
  }
  "/v1/admin/notify-data-updated": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/billing/webhooks/{provider}": {
    post: {
      parameters: {
      path: {
        "provider": string
      }
      header: {
        "X-Skillra-Billing-Signature"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["BillingWebhookOut"]
      }
    }
  }
  "/v1/users/me": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/users/me/api-key": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserApiKeyStatusOut"]
      }
    }
    delete: {
      parameters: {
      query: {
        "source"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserApiKeyRevokeOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/profile": {
    put: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserProfileOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserProfileOut"]
      }
    }
    delete: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/users/{telegram_user_id}/next-best-action": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "source"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["NextBestActionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/evidence-packet": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "task"?: "skill_gap_explanation" | "career_action_draft" | "vacancy_fit_explanation" | "market_change_summary" | "fallback_copy"
        "surface"?: "web" | "bot" | "api" | "worker"
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["EvidencePacketOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/evidence-explainer": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "task"?: "skill_gap_explanation" | "career_action_draft" | "vacancy_fit_explanation" | "market_change_summary" | "fallback_copy"
        "surface"?: "web" | "bot" | "api" | "worker"
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["EvidenceExplainerOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/product-events": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ProductEventOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/commercial-state": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CommercialStateOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan": {
    put: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerPlanOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerPlanOut"]
      }
    }
    delete: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
    patch: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerPlanOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan/actions": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerActionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan/actions/{action_id}": {
    patch: {
      parameters: {
      path: {
        "telegram_user_id": number
        "action_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerActionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan/generate-actions": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerPlanOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan/saved-vacancies": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerActionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/career-plan/actions/{action_id}/outcome": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
        "action_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["CareerActionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/api-key": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserApiKeyOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserApiKeyStatusOut"]
      }
    }
    delete: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserApiKeyRevokeOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/resume": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "filename"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ResumeUploadOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ResumeStatusOut"]
      }
    }
    delete: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/users/{telegram_user_id}/resume/presigned-url": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "ttl"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ResumePresignedUrlOut"]
      }
    }
  }
  "/v1/admin/product-loop-summary": {
    get: {
      parameters: {
      query: {
        "days"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ProductLoopSummaryOut"]
      }
    }
  }
  "/v1/admin/users": {
    get: {
      parameters: {
      query: {
        "skip"?: number
        "limit"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["UserSummaryOut"][]
      }
    }
  }
  "/v1/users/{telegram_user_id}/subscriptions/weekly": {
    put: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["WeeklySubscriptionOut"]
      }
    }
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["WeeklySubscriptionOut"]
      }
    }
    delete: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "source"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/subscriptions/due": {
    get: {
      parameters: {
      query: {
        "now_utc"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DueSubscriptionsResponse"]
      }
    }
  }
  "/v1/subscriptions/weekly/claim": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["ClaimSubscriptionsResponse"]
      }
    }
  }
  "/v1/subscriptions/weekly/ack-sent": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["WeeklySubscriptionOut"]
      }
    }
  }
  "/v1/subscriptions/weekly/ack-failed": {
    post: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["WeeklySubscriptionOut"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/subscriptions/weekly/mark-sent": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["WeeklySubscriptionOut"]
      }
    }
  }
  "/v1/subscriptions/active": {
    get: {
      parameters: {
      header: {
        "X-Skillra-Token"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/users/{telegram_user_id}/digest-preview": {
    post: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "source"?: string | null
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DigestPreviewResponse"]
      }
    }
  }
  "/v1/users/{telegram_user_id}/digest-chart": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/v1/users/{telegram_user_id}/digest/history": {
    get: {
      parameters: {
      path: {
        "telegram_user_id": number
      }
      query: {
        "limit"?: number
        "offset"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["DigestHistoryResponse"]
      }
    }
  }
  "/v1/search/vacancies": {
    get: {
      parameters: {
      query: {
        "q": string
        "role"?: string | null
        "grade"?: string | null
        "country"?: string | null
        "region"?: string | null
        "city"?: string | null
        "geo_scope"?: string | null
        "skill"?: string | null
        "telegram_user_id"?: number | null
        "source"?: string | null
        "limit"?: number
        "offset"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["VacancySearchResponse"]
      }
    }
  }
  "/v1/search/skills": {
    get: {
      parameters: {
      query: {
        "q": string
        "limit"?: number
      }
      header: {
        "X-Skillra-Token"?: string | null
        "Authorization"?: string | null
      }
    }
      responses: {
        200: components["schemas"]["SkillSearchResponse"]
      }
    }
  }
  "/metrics": {
    get: {
      parameters: {
      header: {
        "X-Admin-Token"?: string | null
      }
    }
      responses: {
        200: unknown
      }
    }
  }
  "/internal/metrics": {
    get: {
      parameters: never
      responses: {
        200: unknown
      }
    }
  }
}

export interface components {
  schemas: {
    "AckSubscriptionRequest": {
      "telegram_user_id": number
      "lock": string
      "now_utc"?: string | null
      "text_preview"?: string | null
    }
    "ActiveDatasetOut": {
      "run_id": string
      "activated_at": string
      "source"?: string | null
      "dataset_meta_path"?: string | null
      "manifest_uri"?: string | null
      "quality_report_uri"?: string | null
      "raw_rows"?: number | null
      "processed_rows"?: number | null
      "run"?: components["schemas"]["DataRunOut"] | null
    }
    "ActiveDatasetStatusOut": {
      "state": string
      "active"?: components["schemas"]["ActiveDatasetOut"] | null
    }
    "ApplicationOutcomeIn": {
      "status": "saved" | "applied" | "interview" | "offer" | "rejected" | "withdrawn"
      "note"?: string | null
      "source"?: string
    }
    "BillingWebhookOut": {
      "accepted": boolean
      "duplicate"?: boolean
      "applied"?: boolean
      "commercial_state": components["schemas"]["CommercialStateOut"]
    }
    "CareerActionIn": {
      "title": string
      "description"?: string | null
      "action_type"?: "learning" | "application" | "portfolio" | "networking" | "saved_vacancy" | "other"
      "status"?: "planned" | "in_progress" | "done" | "skipped"
      "priority"?: number
      "skill_name"?: string | null
      "hh_vacancy_id"?: string | null
      "vacancy_title"?: string | null
      "vacancy_url"?: string | null
      "recommendation_source"?: string | null
      "dataset_run_id"?: string | null
      "reason"?: string | null
      "expected_impact"?: string | null
      "effort_estimate"?: string | null
      "due_date"?: string | null
      "evidence"?: Record<string, unknown> | null
      "application_status"?: "saved" | "applied" | "interview" | "offer" | "rejected" | "withdrawn" | null
      "source"?: string | null
    }
    "CareerActionOut": {
      "id": number
      "title": string
      "description"?: string | null
      "action_type": string
      "status": string
      "priority": number
      "skill_name"?: string | null
      "hh_vacancy_id"?: string | null
      "vacancy_title"?: string | null
      "vacancy_url"?: string | null
      "recommendation_source"?: string | null
      "dataset_run_id"?: string | null
      "reason"?: string | null
      "expected_impact"?: string | null
      "effort_estimate"?: string | null
      "due_date"?: string | null
      "review_date"?: string | null
      "evidence"?: Record<string, unknown> | null
      "application_status"?: string | null
      "created_at": string
      "updated_at": string
      "completed_at"?: string | null
    }
    "CareerActionPatch": {
      "title"?: string | null
      "description"?: string | null
      "action_type"?: "learning" | "application" | "portfolio" | "networking" | "saved_vacancy" | "other" | null
      "status"?: "planned" | "in_progress" | "done" | "skipped" | null
      "priority"?: number | null
      "skill_name"?: string | null
      "hh_vacancy_id"?: string | null
      "vacancy_title"?: string | null
      "vacancy_url"?: string | null
      "recommendation_source"?: string | null
      "dataset_run_id"?: string | null
      "reason"?: string | null
      "expected_impact"?: string | null
      "effort_estimate"?: string | null
      "due_date"?: string | null
      "evidence"?: Record<string, unknown> | null
      "application_status"?: "saved" | "applied" | "interview" | "offer" | "rejected" | "withdrawn" | null
      "source"?: string | null
    }
    "CareerGraphOut": {
      "role": string
      "transitions"?: components["schemas"]["CareerTransitionOut"][]
    }
    "CareerPlanGenerateActionsIn": {
      "limit"?: number
      "replace_generated"?: boolean
      "source"?: string | null
    }
    "CareerPlanIn": {
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "status"?: "active" | "completed" | "archived"
      "notes"?: string | null
    }
    "CareerPlanOut": {
      "telegram_user_id": number
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "status": string
      "notes"?: string | null
      "created_at": string
      "updated_at": string
      "actions"?: components["schemas"]["CareerActionOut"][]
    }
    "CareerPlanPatch": {
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "status"?: "active" | "completed" | "archived" | null
      "notes"?: string | null
    }
    "CareerTrajectoryOut": {
      "current_role": string
      "current_grade": string
      "next_grade": string
      "salary_current_p50"?: number | null
      "salary_next_p50"?: number | null
      "salary_delta_pct"?: number | null
      "skills_to_add"?: string[]
      "weeks_trend"?: number
    }
    "CareerTransitionOut": {
      "from_grade": string
      "to_grade": string
      "skills_to_add"?: string[]
      "salary_delta_pct"?: number | null
      "demand_trend"?: string
    }
    "ClaimSubscriptionsRequest": {
      "now_utc"?: string | null
      "stale_lock_seconds"?: number
    }
    "ClaimSubscriptionsResponse": {
      "subscriptions"?: components["schemas"]["ClaimedSubscription"][]
    }
    "ClaimedSubscription": {
      "telegram_user_id": number
      "weekday": number
      "time_local": string
      "timezone": string
      "lock": string
      "attempt": number
      "last_sent_at"?: string | null
    }
    "CohortAnalyticsOut": {
      "organization_id": number
      "cohort_id": number
      "cohort_name": string
      "window_days": number
      "generated_at": string
      "member_count": number
      "member_count_bucket": string
      "suppressed"?: boolean
      "suppression_reason"?: string | null
      "metrics"?: components["schemas"]["CohortMetricOut"][]
      "skill_heatmap"?: components["schemas"]["CohortSkillHeatmapRowOut"][]
    }
    "CohortIn": {
      "name": string
      "slug"?: string | null
      "starts_at"?: string | null
      "ends_at"?: string | null
    }
    "CohortMemberOut": {
      "user_id": number
      "status": "active" | "revoked"
      "has_profile"?: boolean
      "joined_at": string
    }
    "CohortMemberPatch": {
      "status"?: "active" | "revoked" | null
      "target_cohort_id"?: number | null
    }
    "CohortMetricOut": {
      "metric": string
      "count"?: number | null
      "denominator"?: number | null
      "rate"?: number | null
      "suppressed"?: boolean
    }
    "CohortOut": {
      "id": number
      "organization_id": number
      "slug": string
      "name": string
      "members_count"?: number
      "starts_at"?: string | null
      "ends_at"?: string | null
      "created_at": string
      "archived_at"?: string | null
    }
    "CohortSkillHeatmapRowOut": {
      "skill_name": string
      "cohort_member_count": number
      "users_missing_count"?: number | null
      "users_missing_share"?: number | null
      "target_role"?: string | null
      "suppressed"?: boolean
    }
    "CommercialStateOut": {
      "plan": "free" | "trial" | "pro" | "admin"
      "subscription_state": "none" | "trialing" | "active" | "cancel_at_period_end" | "expired" | "refunded" | "payment_failed" | "provider_unavailable" | "past_due" | "cancelled"
      "entitlements"?: string[]
      "locked_features"?: string[]
      "trial_ends_at"?: string | null
      "current_period_ends_at"?: string | null
      "provider"?: string | null
      "account_url"?: string
    }
    "DataRunOut": {
      "run_id": string
      "state": string
      "source"?: string | null
      "started_at": string
      "updated_at": string
      "finished_at"?: string | null
      "raw_rows"?: number | null
      "processed_rows"?: number | null
      "error_msg"?: string | null
      "dataset_meta_path"?: string | null
      "manifest_uri"?: string | null
      "quality_report_uri"?: string | null
      "artifact_uris"?: Record<string, unknown> | null
      "raw_quality_report"?: Record<string, unknown> | null
      "processed_quality_report"?: Record<string, unknown> | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
    }
    "DataRunStateUpdateIn": {
      "state": string
      "source"?: string | null
      "raw_rows"?: number | null
      "processed_rows"?: number | null
      "error_msg"?: string | null
      "dataset_meta_path"?: string | null
      "manifest_uri"?: string | null
      "quality_report_uri"?: string | null
      "artifact_uris"?: Record<string, unknown> | null
      "raw_quality_report"?: Record<string, unknown> | null
      "processed_quality_report"?: Record<string, unknown> | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
    }
    "DataRunStatusOut": {
      "state": string
      "latest"?: components["schemas"]["DataRunOut"] | null
    }
    "DatasetMetaResponse": {
      "created_at"?: string | null
      "vacancy_count"?: number | null
      "source"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "features_path"?: string | null
      "market_view_path"?: string | null
      "dataset_meta_path"?: string | null
    }
    "DigestHistoryItem": {
      "id": number
      "sent_at": string
      "format": string
      "text_preview"?: string | null
      "attempt": number
    }
    "DigestHistoryResponse": {
      "items"?: components["schemas"]["DigestHistoryItem"][]
      "total": number
    }
    "DigestPreviewResponse": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "format": "HTML" | "Markdown"
      "text": string
    }
    "DueSubscription": {
      "telegram_user_id": number
      "weekday": number
      "time_local": string
      "timezone": string
      "last_sent_at"?: string | null
    }
    "DueSubscriptionsResponse": {
      "subscriptions"?: components["schemas"]["DueSubscription"][]
    }
    "EvidenceDatasetContext": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
    }
    "EvidenceExplainerOut": {
      "version"?: string
      "packet_version": string
      "task": "skill_gap_explanation" | "career_action_draft" | "vacancy_fit_explanation" | "market_change_summary" | "fallback_copy"
      "surface": "web" | "bot" | "api" | "worker"
      "status": "answered" | "fallback" | "blocked" | "disabled"
      "answer": string
      "bullets"?: string[]
      "evidence_refs"?: components["schemas"]["EvidenceRefOut"][]
      "uncertainties"?: string[]
      "blocked_claims"?: string[]
      "human_review_required"?: boolean
    }
    "EvidenceItem": {
      "evidence_id": string
      "evidence_type": string
      "source": string
      "claim": string
      "value"?: unknown | null
      "unit"?: string | null
      "confidence"?: string | null
      "dataset_run_id"?: string | null
      "generated_at_utc"?: string | null
      "metadata"?: Record<string, unknown>
    }
    "EvidenceOutputConstraints": {
      "language"?: "ru"
      "max_bullets"?: number
      "require_evidence_refs"?: boolean
      "allowed_tasks"?: "skill_gap_explanation" | "career_action_draft" | "vacancy_fit_explanation" | "market_change_summary" | "fallback_copy"[]
      "forbidden_claims"?: string[]
      "blocked_claims"?: string[]
    }
    "EvidencePacketOut": {
      "version"?: string
      "task": "skill_gap_explanation" | "career_action_draft" | "vacancy_fit_explanation" | "market_change_summary" | "fallback_copy"
      "surface": "web" | "bot" | "api" | "worker"
      "telegram_user_id": number
      "profile": components["schemas"]["EvidenceUserContext"]
      "dataset": components["schemas"]["EvidenceDatasetContext"]
      "market_summary"?: components["schemas"]["MarketSummary"] | null
      "skill_gap"?: components["schemas"]["SkillGapEntry"][]
      "recommended_skills"?: string[]
      "plan"?: components["schemas"]["EvidencePlanContext"]
      "search"?: components["schemas"]["EvidenceSearchContext"]
      "output_constraints": components["schemas"]["EvidenceOutputConstraints"]
      "evidence"?: components["schemas"]["EvidenceItem"][]
      "warnings"?: string[]
    }
    "EvidencePlanActionContext": {
      "action_id": number
      "title": string
      "action_type": string
      "status": string
      "priority": number
      "skill_name"?: string | null
      "hh_vacancy_id"?: string | null
      "vacancy_title"?: string | null
      "recommendation_source"?: string | null
      "dataset_run_id"?: string | null
      "reason"?: string | null
      "evidence"?: Record<string, unknown> | null
    }
    "EvidencePlanContext": {
      "status"?: string | null
      "action_count"?: number
      "next_actions"?: components["schemas"]["EvidencePlanActionContext"][]
    }
    "EvidenceRefOut": {
      "evidence_id": string
      "claim": string
    }
    "EvidenceSearchContext": {
      "search_state"?: "ready" | "degraded" | "fallback" | "unavailable"
      "index_status"?: string | null
      "degraded_reason"?: string | null
      "warnings"?: string[]
    }
    "EvidenceUserContext": {
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "current_skills"?: string[]
      "profile_quality": components["schemas"]["ProfileQualityOut"]
    }
    "HTTPValidationError": {
      "detail"?: components["schemas"]["ValidationError"][]
    }
    "IndexerStatusOut": {
      "status": string
      "source"?: string | null
      "dataset_run_id"?: string | null
      "served_dataset_run_id"?: string | null
      "active_dataset_run_id"?: string | null
      "started_at"?: string | null
      "finished_at"?: string | null
      "inserted"?: number
      "indexed"?: number
      "error_msg"?: string | null
    }
    "InviteAcceptOut": {
      "organization": components["schemas"]["OrganizationOut"]
      "cohort"?: components["schemas"]["CohortOut"] | null
    }
    "MarkSentRequest": {
      "now_utc"?: string | null
    }
    "MarketSummary": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "vacancy_count": number
      "salary_sample_size"?: number | null
      "salary_coverage_share"?: number | null
      "min_market_n"?: number | null
      "salary_median"?: number | null
      "salary_q25"?: number | null
      "salary_q75"?: number | null
      "remote_share"?: number | null
      "geo_scope"?: string | null
      "junior_friendly_share"?: number | null
      "top_skills"?: string[] | null
    }
    "MetaCitiesResponse": {
      "cities"?: string[]
    }
    "MetaCityTiersResponse": {
      "city_tiers"?: string[]
    }
    "MetaCountriesResponse": {
      "countries"?: string[]
    }
    "MetaDomainsResponse": {
      "domains"?: string[]
    }
    "MetaGeoScopesResponse": {
      "geo_scopes"?: string[]
    }
    "MetaGradesResponse": {
      "grades"?: string[]
    }
    "MetaRegionsResponse": {
      "regions"?: string[]
    }
    "MetaRolesResponse": {
      "roles"?: string[]
    }
    "MetaWorkModesResponse": {
      "work_modes"?: string[]
    }
    "NextBestActionOut": {
      "telegram_user_id": number
      "state": "create_profile" | "complete_profile" | "create_plan" | "generate_plan_actions" | "find_vacancy" | "update_application_outcome" | "enable_digest" | "continue_plan" | "data_unavailable"
      "action_id": string
      "title": string
      "reason": string
      "cta": string
      "target_surface": "web" | "bot"
      "route"?: string | null
      "command"?: string | null
      "trust_warning"?: string | null
      "profile_quality": components["schemas"]["ProfileQualityOut"]
    }
    "OrganizationIn": {
      "name": string
      "slug"?: string | null
      "organization_type"?: "university" | "bootcamp" | "career_center" | "company" | "other"
    }
    "OrganizationInviteIn": {
      "cohort_id"?: number | null
      "role"?: "admin" | "member"
      "max_uses"?: number
      "expires_at"?: string | null
    }
    "OrganizationInviteOut": {
      "id": number
      "organization_id": number
      "cohort_id"?: number | null
      "role": "admin" | "member"
      "max_uses": number
      "uses_count": number
      "expires_at": string
      "revoked_at"?: string | null
      "created_at": string
      "token"?: string | null
    }
    "OrganizationMemberOut": {
      "user_id": number
      "role": "owner" | "admin" | "member"
      "status": "active" | "revoked"
      "has_profile"?: boolean
      "joined_at": string
    }
    "OrganizationMemberPatch": {
      "role"?: "owner" | "admin" | "member" | null
      "status"?: "active" | "revoked" | null
    }
    "OrganizationOut": {
      "id": number
      "slug": string
      "name": string
      "organization_type": "university" | "bootcamp" | "career_center" | "company" | "other"
      "role": "owner" | "admin" | "member"
      "members_count"?: number
      "cohorts_count"?: number
      "created_at": string
      "archived_at"?: string | null
    }
    "OrganizationPatch": {
      "name"?: string | null
      "organization_type"?: "university" | "bootcamp" | "career_center" | "company" | "other" | null
    }
    "PaginatedMetaSkillsResponse": {
      "skills"?: string[]
      "total": number
      "limit": number
      "offset": number
    }
    "PersonaAnalysisResponse": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "market_summary": components["schemas"]["MarketSummary"]
      "recommended_skills": string[]
      "top_skill_demand": components["schemas"]["SkillDemandEntry"][]
      "skill_gap": components["schemas"]["SkillGapEntry"][]
      "warnings": string[]
      "filters_used": Record<string, unknown>
      "skill_resources"?: Record<string, components["schemas"]["SkillResource"][]>
    }
    "PersonaProfile": {
      "name": string
      "description": string
      "current_skills"?: string[]
      "target_role": string
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "skill_whitelist"?: string[] | null
      "constraints"?: Record<string, unknown>
      "goals"?: string[]
      "limitations"?: string[]
    }
    "ProductCohortSummaryOut": {
      "cohort_week": string
      "users_started": number
      "active_users": number
      "profiles_completed_users": number
      "first_value_users": number
      "weekly_return_users": number
      "digest_engagement_users": number
      "digest_subscribers": number
      "events_by_surface"?: Record<string, number>
    }
    "ProductEventIn": {
      "event_name": string
      "surface"?: "api" | "web" | "bot" | "worker" | "digest" | "admin" | "user" | "system"
      "entity_type"?: string | null
      "entity_id"?: string | null
      "session_id"?: string | null
      "correlation_id"?: string | null
      "metadata"?: Record<string, unknown>
      "occurred_at"?: string | null
    }
    "ProductEventOut": {
      "id": number
      "event_name": string
      "surface": string
      "entity_type"?: string | null
      "entity_id"?: string | null
      "request_id"?: string | null
      "session_id"?: string | null
      "correlation_id"?: string | null
      "metadata"?: Record<string, unknown>
      "occurred_at": string
    }
    "ProductLoopSummaryOut": {
      "window_days": number
      "generated_at": string
      "users_total": number
      "profiles_total": number
      "career_plans_total": number
      "active_subscriptions_total": number
      "recent_active_users": number
      "users_with_saved_vacancy": number
      "users_with_application_outcome": number
      "career_actions_total": number
      "completed_actions_total": number
      "saved_vacancies_total": number
      "application_outcomes_total": number
      "recent_application_outcomes_total": number
      "recent_product_events_by_type"?: Record<string, number>
      "recent_product_events_by_source"?: Record<string, number>
      "activation_events_by_source"?: Record<string, number>
      "first_value_users_by_source"?: Record<string, number>
      "activation_conversion_by_source"?: Record<string, number>
      "first_value_conversion_by_source"?: Record<string, number>
      "weekly_return_users_by_source"?: Record<string, number>
      "digest_engagement_users_by_source"?: Record<string, number>
      "trust_tier_distribution"?: Record<string, number>
      "degraded_search_exposures"?: number
      "cohort_weeks"?: components["schemas"]["ProductCohortSummaryOut"][]
      "career_actions_by_type"?: Record<string, number>
      "career_actions_by_recommendation_source"?: Record<string, number>
      "recent_application_outcomes_by_status"?: Record<string, number>
    }
    "ProfileQualityOut": {
      "score": number
      "is_complete": boolean
      "completed_fields"?: string[]
      "missing_fields"?: string[]
    }
    "ResumePresignedUrlOut": {
      "url": string
      "ttl": number
    }
    "ResumeStatusOut": {
      "uploaded": boolean
      "telegram_user_id"?: number | null
      "s3_key"?: string | null
      "original_filename"?: string | null
      "content_type"?: string | null
      "file_size_bytes"?: number | null
      "uploaded_at"?: string | null
      "extracted_skills"?: string[]
      "presigned_url"?: string | null
    }
    "ResumeUploadOut": {
      "uploaded"?: boolean
      "telegram_user_id"?: number | null
      "s3_key": string
      "original_filename": string
      "content_type"?: string | null
      "file_size_bytes": number
      "uploaded_at"?: string | null
      "extracted_skills"?: string[]
    }
    "SalaryTrendOut": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "claim_status"?: "ready" | "blocked"
      "warnings"?: string[]
      "role": string
      "grade": string
      "metric"?: string
      "currency"?: string
      "data"?: components["schemas"]["TrendDataPoint"][]
    }
    "SavedVacancyIn": {
      "hh_vacancy_id": string
      "title": string
      "url"?: string | null
      "note"?: string | null
      "source"?: string | null
    }
    "SegmentFilters": {
      "role"?: string | null
      "grade"?: string | null
      "city_tier"?: string | null
      "country"?: string | null
      "region"?: string | null
      "city"?: string | null
      "geo_scope"?: string | null
      "work_mode"?: string | null
      "domain"?: string | null
    }
    "SegmentSummary": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "vacancy_count": number
      "min_market_n"?: number | null
      "salary_sample_size"?: number | null
      "salary_coverage_share"?: number | null
      "salary_median"?: number | null
      "salary_q25"?: number | null
      "salary_q75"?: number | null
      "junior_friendly_share"?: number | null
      "remote_share"?: number | null
      "geo_scope"?: string | null
      "median_tech_stack_size"?: number | null
      "top_skills"?: string[] | null
      "warnings"?: string[]
    }
    "SkillDemandEntry": {
      "skill_name": string
      "market_share": number
      "skill_name_raw"?: string | null
    }
    "SkillDemandTrendOut": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "claim_status"?: "ready" | "blocked"
      "warnings"?: string[]
      "skill": string
      "role"?: string | null
      "data"?: components["schemas"]["TrendDataPoint"][]
    }
    "SkillGapEntry": {
      "skill_name": string
      "market_share": number
      "skill_name_raw"?: string | null
      "persona_has": boolean
      "gap": boolean
    }
    "SkillResource": {
      "title": string
      "url": string
      "type": "course" | "docs" | "practice" | "book"
    }
    "SkillSearchResponse": {
      "skills"?: string[]
      "total": number
    }
    "TrendDataPoint": {
      "week_start": string
      "value": number
      "dataset_run_id"?: string | null
      "coverage_window"?: string | null
      "completeness"?: string | number | boolean | null
      "is_complete"?: boolean | null
      "source_row_count"?: number | null
      "confidence"?: string | null
    }
    "UserApiKeyOut": {
      "key": string
      "key_prefix": string
      "created_at": string
    }
    "UserApiKeyRevokeOut": {
      "revoked": boolean
      "revoked_at": string
    }
    "UserApiKeyStatusOut": {
      "key_prefix": string
      "created_at": string
      "last_used_at"?: string | null
      "is_active": boolean
    }
    "UserProfileIn": {
      "username"?: string | null
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "current_skills"?: string[]
      "source"?: string | null
    }
    "UserProfileOut": {
      "telegram_user_id": number
      "username"?: string | null
      "target_role"?: string | null
      "target_grade"?: string | null
      "target_city_tier"?: string | null
      "target_country"?: string | null
      "target_region"?: string | null
      "target_city"?: string | null
      "target_geo_scope"?: string | null
      "target_work_mode"?: string | null
      "target_domain"?: string | null
      "current_skills"?: string[]
      "warnings"?: string[]
      "created_at"?: string | null
      "updated_at"?: string | null
    }
    "UserSummaryOut": {
      "id": number
      "telegram_user_id": number
      "username"?: string | null
      "created_at": string
      "has_profile"?: boolean
      "has_subscription"?: boolean
    }
    "VacancyCountTrendOut": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "claim_status"?: "ready" | "blocked"
      "warnings"?: string[]
      "role": string
      "grade"?: string | null
      "data"?: components["schemas"]["TrendDataPoint"][]
    }
    "VacancySearchResponse": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "results"?: components["schemas"]["VacancySearchResult"][]
      "total": number
      "query": string
      "index_status"?: string | null
      "index_dataset_run_id"?: string | null
      "search_state"?: "ready" | "degraded" | "fallback" | "unavailable"
      "degraded_reason"?: string | null
      "warnings"?: string[]
    }
    "VacancySearchResult": {
      "dataset_run_id"?: string | null
      "generated_at"?: string | null
      "generated_at_utc"?: string | null
      "freshness"?: string | null
      "sample_size"?: number | null
      "confidence"?: string | null
      "source_kind"?: string | null
      "dataset_semantic_type"?: string | null
      "requested_date_from"?: string | null
      "requested_date_to"?: string | null
      "observed_published_at_from"?: string | null
      "observed_published_at_to"?: string | null
      "date_semantics_status"?: string | null
      "product_eligibility"?: Record<string, unknown> | null
      "source_capability_ref"?: Record<string, unknown> | null
      "trend_ready_gate"?: Record<string, unknown> | null
      "hh_vacancy_id": string
      "title": string
      "primary_role"?: string | null
      "grade"?: string | null
      "city"?: string | null
      "city_tier"?: string | null
      "country"?: string | null
      "region"?: string | null
      "city_normalized"?: string | null
      "geo_scope"?: string | null
      "salary_from"?: number | null
      "salary_to"?: number | null
      "skills"?: string[]
      "url"?: string | null
      "hh_url"?: string | null
      "published_at"?: string | null
      "fit_reason"?: string | null
      "gap_reason"?: string | null
      "plan_relevance"?: string | null
      "matched_skills"?: string[]
      "missing_skills"?: string[]
      "match_score"?: number | null
      "match_level"?: "high" | "medium" | "low" | "unknown" | null
    }
    "ValidationError": {
      "loc": string | number[]
      "msg": string
      "type": string
    }
    "WeeklySubscriptionIn": {
      "active"?: boolean
      "weekday": number
      "time_local": string
      "timezone": string
      "source"?: string | null
    }
    "WeeklySubscriptionOut": {
      "telegram_user_id": number
      "active": boolean
      "weekday": number
      "time_local": string
      "timezone": string
      "last_sent_at"?: string | null
    }
  }
}
