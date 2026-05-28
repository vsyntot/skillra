from __future__ import annotations

"""Pydantic schemas for Skillra API responses."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Input validation constraints (DoS prevention — see GAP-11)
# ---------------------------------------------------------------------------

#: Maximum number of skills allowed in a single request.
MAX_SKILLS_COUNT: int = 200
#: Maximum character length for a single skill name.
MAX_SKILL_NAME_LEN: int = 100

# Reusable annotated type: a skill name with length constraint.
_SkillName = Annotated[str, Field(max_length=MAX_SKILL_NAME_LEN)]


class AnalyticalTrustFields(BaseModel):
    """Common trust metadata for analytical responses."""

    dataset_run_id: str | None = Field(None, description="Dataset run id used to produce the response")
    generated_at: str | None = Field(None, description="Dataset generation timestamp")
    generated_at_utc: str | None = Field(None, description="Dataset generation timestamp in UTC")
    freshness: str | None = Field(None, description="Freshness label: fresh, aging, stale, or unknown")
    sample_size: int | None = Field(None, description="Sample size used for the response")
    confidence: str | None = Field(None, description="Confidence label: low, medium, high, or unknown")
    source_kind: str | None = Field(None, description="Operational source kind for the dataset")
    dataset_semantic_type: str | None = Field(None, description="Business meaning of the dataset snapshot")
    requested_date_from: str | None = Field(None, description="Requested source publication date lower bound")
    requested_date_to: str | None = Field(None, description="Requested source publication date upper bound")
    observed_published_at_from: str | None = Field(None, description="Observed publication date lower bound")
    observed_published_at_to: str | None = Field(None, description="Observed publication date upper bound")
    date_semantics_status: str | None = Field(None, description="Date-semantics validation status")
    product_eligibility: dict[str, Any] | None = Field(None, description="Dataset product eligibility flags")
    source_capability_ref: dict[str, Any] | None = Field(None, description="Source capability reference")
    trend_ready_gate: dict[str, Any] | None = Field(None, description="Trend-ready gate evidence")


class PersonaProfile(BaseModel):
    """Persona payload describing current skills and target segment."""

    name: str = Field(..., description="Persona display name")
    description: str = Field(..., description="Short description for the persona")
    current_skills: list[_SkillName] = Field(
        default_factory=list,
        max_length=MAX_SKILLS_COUNT,
        description="Skills the persona already has",
    )
    target_role: str = Field(..., description="Target primary role")
    target_grade: str | None = Field(None, description="Target grade")
    target_city_tier: str | None = Field(None, description="Target city tier")
    target_country: str | None = Field(None, description="Target country")
    target_region: str | None = Field(None, description="Target region")
    target_city: str | None = Field(None, description="Target normalized city")
    target_geo_scope: str | None = Field(None, description="Target market geography scope")
    target_work_mode: str | None = Field(None, description="Preferred work mode")
    skill_whitelist: list[_SkillName] | None = Field(
        None,
        max_length=MAX_SKILLS_COUNT,
        description="Optional explicit list of skills to analyse",
    )
    constraints: dict[str, Any] = Field(default_factory=dict, description="Extra filters for the target segment")
    goals: list[str] = Field(default_factory=list, description="Persona goals")
    limitations: list[str] = Field(default_factory=list, description="Persona limitations")


class UserProfileIn(BaseModel):
    """User profile payload for storing preferences and skills."""

    username: str | None = Field(None, description="Optional Telegram username of the user")
    target_role: str | None = Field(None, description="Target primary role")
    target_grade: str | None = Field(None, description="Target grade")
    target_city_tier: str | None = Field(None, description="Preferred city tier")
    target_country: str | None = Field(None, description="Preferred country")
    target_region: str | None = Field(None, description="Preferred region")
    target_city: str | None = Field(None, description="Preferred normalized city")
    target_geo_scope: str | None = Field(None, description="Preferred market geography scope")
    target_work_mode: str | None = Field(None, description="Preferred work mode")
    target_domain: str | None = Field(None, description="Preferred domain")
    current_skills: list[_SkillName] = Field(
        default_factory=list,
        max_length=MAX_SKILLS_COUNT,
        description="List of skills the user already has",
    )
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class UserProfileOut(BaseModel):
    """User profile response payload."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    username: str | None = Field(None, description="Telegram username if available")
    target_role: str | None = Field(None, description="Target primary role")
    target_grade: str | None = Field(None, description="Target grade")
    target_city_tier: str | None = Field(None, description="Preferred city tier")
    target_country: str | None = Field(None, description="Preferred country")
    target_region: str | None = Field(None, description="Preferred region")
    target_city: str | None = Field(None, description="Preferred normalized city")
    target_geo_scope: str | None = Field(None, description="Preferred market geography scope")
    target_work_mode: str | None = Field(None, description="Preferred work mode")
    target_domain: str | None = Field(None, description="Preferred domain")
    current_skills: list[str] = Field(default_factory=list, description="List of skills the user already has")
    warnings: list[str] = Field(default_factory=list, description="Non-blocking warnings")
    created_at: datetime | None = Field(None, description="Profile creation timestamp UTC")
    updated_at: datetime | None = Field(None, description="Profile last update timestamp UTC")


NextBestActionState = Literal[
    "create_profile",
    "complete_profile",
    "create_plan",
    "generate_plan_actions",
    "find_vacancy",
    "update_application_outcome",
    "enable_digest",
    "continue_plan",
    "data_unavailable",
]
NextBestActionSurface = Literal["web", "bot"]


class ProfileQualityOut(BaseModel):
    """Profile completeness signal shared by web and Telegram surfaces."""

    score: int = Field(..., ge=0, le=100, description="Profile completeness score from 0 to 100")
    is_complete: bool = Field(..., description="Whether all required activation fields are present")
    completed_fields: list[str] = Field(default_factory=list, description="Required fields already filled")
    missing_fields: list[str] = Field(default_factory=list, description="Required fields still missing")


class NextBestActionOut(BaseModel):
    """One shared activation recommendation for the user's next product step."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    state: NextBestActionState = Field(..., description="Normalized activation state")
    action_id: str = Field(..., description="Stable action identifier for analytics/UI")
    title: str = Field(..., description="User-facing action title")
    reason: str = Field(..., description="Why this action is recommended now")
    cta: str = Field(..., description="Primary call-to-action label")
    target_surface: NextBestActionSurface = Field(..., description="Preferred surface for completing the action")
    route: str | None = Field(None, description="Web route for the action")
    command: str | None = Field(None, description="Telegram command for the action")
    trust_warning: str | None = Field(None, description="Optional data-trust warning to show near the action")
    profile_quality: ProfileQualityOut = Field(..., description="Profile completeness signal")


class UserSummaryOut(BaseModel):
    """Admin summary for a registered user."""

    id: int
    telegram_user_id: int
    username: str | None = None
    created_at: datetime
    has_profile: bool = False
    has_subscription: bool = False


ProductEventSurface = Literal["api", "web", "bot", "worker", "digest", "admin", "user", "system"]
CommercialPlan = Literal["free", "trial", "pro", "admin"]
CommercialSubscriptionState = Literal[
    "none",
    "trialing",
    "active",
    "cancel_at_period_end",
    "expired",
    "refunded",
    "payment_failed",
    "provider_unavailable",
    "past_due",
    "cancelled",
]


class ProductEventIn(BaseModel):
    """Canonical product telemetry event payload."""

    event_name: str = Field(..., min_length=1, max_length=64)
    surface: ProductEventSurface = Field("api", description="Surface that produced the event")
    entity_type: str | None = Field(None, max_length=64)
    entity_id: str | None = Field(None, max_length=64)
    session_id: str | None = Field(None, max_length=128)
    correlation_id: str | None = Field(None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class ProductEventOut(BaseModel):
    """Stored product telemetry event after validation and redaction."""

    id: int
    event_name: str
    surface: str
    entity_type: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class ProductCohortSummaryOut(BaseModel):
    """PII-free PM cohort summary for product-loop learning."""

    cohort_week: date
    users_started: int
    active_users: int
    profiles_completed_users: int
    first_value_users: int
    weekly_return_users: int
    digest_engagement_users: int
    digest_subscribers: int
    events_by_surface: dict[str, int] = Field(default_factory=dict)


class ProductLoopSummaryOut(BaseModel):
    """PM-readable product-loop funnel summary without PII labels."""

    window_days: int
    generated_at: datetime
    users_total: int
    profiles_total: int
    career_plans_total: int
    active_subscriptions_total: int
    recent_active_users: int
    users_with_saved_vacancy: int
    users_with_application_outcome: int
    career_actions_total: int
    completed_actions_total: int
    saved_vacancies_total: int
    application_outcomes_total: int
    recent_application_outcomes_total: int
    recent_product_events_by_type: dict[str, int] = Field(default_factory=dict)
    recent_product_events_by_source: dict[str, int] = Field(default_factory=dict)
    activation_events_by_source: dict[str, int] = Field(default_factory=dict)
    first_value_users_by_source: dict[str, int] = Field(default_factory=dict)
    activation_conversion_by_source: dict[str, float] = Field(default_factory=dict)
    first_value_conversion_by_source: dict[str, float] = Field(default_factory=dict)
    weekly_return_users_by_source: dict[str, int] = Field(default_factory=dict)
    digest_engagement_users_by_source: dict[str, int] = Field(default_factory=dict)
    trust_tier_distribution: dict[str, int] = Field(default_factory=dict)
    degraded_search_exposures: int = 0
    cohort_weeks: list[ProductCohortSummaryOut] = Field(default_factory=list)
    career_actions_by_type: dict[str, int] = Field(default_factory=dict)
    career_actions_by_recommendation_source: dict[str, int] = Field(default_factory=dict)
    recent_application_outcomes_by_status: dict[str, int] = Field(default_factory=dict)


class CommercialStateOut(BaseModel):
    """PII-light commercial state for account and locked-state UX."""

    plan: CommercialPlan
    subscription_state: CommercialSubscriptionState
    entitlements: list[str] = Field(default_factory=list)
    locked_features: list[str] = Field(default_factory=list)
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None
    provider: str | None = None
    account_url: str = "/account"


class BillingFakeWebhookIn(BaseModel):
    """Provider-neutral fake billing event for local/CI tests and dry runs."""

    event_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field("subscription.updated", max_length=64)
    telegram_user_id: int
    plan: CommercialPlan
    subscription_state: CommercialSubscriptionState
    entitlements: list[str] | None = None
    provider_customer_id: str | None = Field(None, max_length=128)
    provider_subscription_id: str | None = Field(None, max_length=128)
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None
    occurred_at: datetime | None = None


class BillingWebhookOut(BaseModel):
    """Webhook processing result without provider secrets or PII labels."""

    accepted: bool
    duplicate: bool = False
    applied: bool = True
    commercial_state: CommercialStateOut


OrganizationType = Literal["university", "bootcamp", "career_center", "company", "other"]
OrganizationRole = Literal["owner", "admin", "member"]
OrganizationMembershipStatus = Literal["active", "revoked"]
CohortMembershipStatus = Literal["active", "revoked"]


class OrganizationIn(BaseModel):
    """Create a B2B workspace."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(None, min_length=2, max_length=64)
    organization_type: OrganizationType = "other"


class OrganizationPatch(BaseModel):
    """Update mutable organization fields."""

    name: str | None = Field(None, min_length=1, max_length=255)
    organization_type: OrganizationType | None = None


class OrganizationOut(BaseModel):
    """B2B workspace visible to the authenticated member."""

    id: int
    slug: str
    name: str
    organization_type: OrganizationType
    role: OrganizationRole
    members_count: int = 0
    cohorts_count: int = 0
    created_at: datetime
    archived_at: datetime | None = None


class OrganizationMemberOut(BaseModel):
    """PII-minimized organization member row for org admins."""

    user_id: int
    role: OrganizationRole
    status: OrganizationMembershipStatus
    has_profile: bool = False
    joined_at: datetime


class OrganizationMemberPatch(BaseModel):
    """Update a member role or status."""

    role: OrganizationRole | None = None
    status: OrganizationMembershipStatus | None = None


class CohortIn(BaseModel):
    """Create a cohort inside an organization."""

    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(None, min_length=2, max_length=64)
    starts_at: date | None = None
    ends_at: date | None = None


class CohortPatch(BaseModel):
    """Update mutable cohort fields."""

    name: str | None = Field(None, min_length=1, max_length=255)
    starts_at: date | None = None
    ends_at: date | None = None


class CohortOut(BaseModel):
    """B2B cohort summary."""

    id: int
    organization_id: int
    slug: str
    name: str
    members_count: int = 0
    starts_at: date | None = None
    ends_at: date | None = None
    created_at: datetime
    archived_at: datetime | None = None


class CohortMemberOut(BaseModel):
    """PII-minimized cohort member row for org admins."""

    user_id: int
    status: CohortMembershipStatus
    has_profile: bool = False
    joined_at: datetime


class CohortMemberPatch(BaseModel):
    """Update or move a cohort member inside one organization."""

    status: CohortMembershipStatus | None = None
    target_cohort_id: int | None = Field(None, ge=1)


class OrganizationInviteIn(BaseModel):
    """Create a hash-only invite token for an organization and optional cohort."""

    cohort_id: int | None = None
    role: Literal["admin", "member"] = "member"
    max_uses: int = Field(1, ge=1, le=500)
    expires_at: datetime | None = None


class OrganizationInviteOut(BaseModel):
    """Invite metadata. Plain token is returned only on creation."""

    id: int
    organization_id: int
    cohort_id: int | None = None
    role: Literal["admin", "member"]
    max_uses: int
    uses_count: int
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime
    token: str | None = None


class InviteAcceptOut(BaseModel):
    """Accepted invite result."""

    organization: OrganizationOut
    cohort: CohortOut | None = None


class CohortMetricOut(BaseModel):
    """Privacy-safe aggregate metric for B2B cohort reporting."""

    metric: str
    count: int | None = None
    denominator: int | None = None
    rate: float | None = None
    suppressed: bool = False


class CohortSkillHeatmapRowOut(BaseModel):
    """Privacy-safe skill gap heatmap cell."""

    skill_name: str
    cohort_member_count: int
    users_missing_count: int | None = None
    users_missing_share: float | None = None
    target_role: str | None = None
    suppressed: bool = False


class CohortAnalyticsOut(BaseModel):
    """Privacy-safe B2B cohort analytics."""

    organization_id: int
    cohort_id: int
    cohort_name: str
    window_days: int
    generated_at: datetime
    member_count: int
    member_count_bucket: str
    suppressed: bool = False
    suppression_reason: str | None = None
    metrics: list[CohortMetricOut] = Field(default_factory=list)
    skill_heatmap: list[CohortSkillHeatmapRowOut] = Field(default_factory=list)


CareerPlanStatus = Literal["active", "completed", "archived"]
CareerActionType = Literal["learning", "application", "portfolio", "networking", "saved_vacancy", "other"]
CareerActionStatus = Literal["planned", "in_progress", "done", "skipped"]
ApplicationOutcomeStatus = Literal["saved", "applied", "interview", "offer", "rejected", "withdrawn"]


class CareerPlanIn(BaseModel):
    """Career plan payload for creating or replacing a user's plan."""

    target_role: str | None = Field(None, description="Target primary role")
    target_grade: str | None = Field(None, description="Target grade")
    target_city_tier: str | None = Field(None, description="Preferred city tier")
    target_country: str | None = Field(None, description="Preferred country")
    target_region: str | None = Field(None, description="Preferred region")
    target_city: str | None = Field(None, description="Preferred normalized city")
    target_geo_scope: str | None = Field(None, description="Preferred market geography scope")
    target_work_mode: str | None = Field(None, description="Preferred work mode")
    target_domain: str | None = Field(None, description="Preferred domain")
    status: CareerPlanStatus = Field("active", description="Plan lifecycle status")
    notes: str | None = Field(None, max_length=5000, description="Free-form plan notes")


class CareerPlanPatch(BaseModel):
    """Partial career plan update payload."""

    target_role: str | None = None
    target_grade: str | None = None
    target_city_tier: str | None = None
    target_country: str | None = None
    target_region: str | None = None
    target_city: str | None = None
    target_geo_scope: str | None = None
    target_work_mode: str | None = None
    target_domain: str | None = None
    status: CareerPlanStatus | None = None
    notes: str | None = Field(None, max_length=5000)


class CareerActionIn(BaseModel):
    """Career plan action payload."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    action_type: CareerActionType = "learning"
    status: CareerActionStatus = "planned"
    priority: int = Field(100, ge=0, le=1000)
    skill_name: str | None = Field(None, max_length=100)
    hh_vacancy_id: str | None = Field(None, max_length=50)
    vacancy_title: str | None = Field(None, max_length=500)
    vacancy_url: str | None = Field(None, max_length=512)
    recommendation_source: str | None = Field(None, max_length=64)
    dataset_run_id: str | None = Field(None, max_length=64)
    reason: str | None = Field(None, max_length=5000)
    expected_impact: str | None = Field(None, max_length=64)
    effort_estimate: str | None = Field(None, max_length=64)
    due_date: date | None = None
    evidence: dict[str, Any] | None = None
    application_status: ApplicationOutcomeStatus | None = None
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class CareerActionPatch(BaseModel):
    """Partial career action update payload."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=5000)
    action_type: CareerActionType | None = None
    status: CareerActionStatus | None = None
    priority: int | None = Field(None, ge=0, le=1000)
    skill_name: str | None = Field(None, max_length=100)
    hh_vacancy_id: str | None = Field(None, max_length=50)
    vacancy_title: str | None = Field(None, max_length=500)
    vacancy_url: str | None = Field(None, max_length=512)
    recommendation_source: str | None = Field(None, max_length=64)
    dataset_run_id: str | None = Field(None, max_length=64)
    reason: str | None = Field(None, max_length=5000)
    expected_impact: str | None = Field(None, max_length=64)
    effort_estimate: str | None = Field(None, max_length=64)
    due_date: date | None = None
    evidence: dict[str, Any] | None = None
    application_status: ApplicationOutcomeStatus | None = None
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class CareerPlanGenerateActionsIn(BaseModel):
    """Request for generating evidence-backed career-plan actions."""

    limit: int = Field(5, ge=1, le=10)
    replace_generated: bool = Field(
        False,
        description="Remove existing generated planned actions before creating new ones",
    )
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class ApplicationOutcomeIn(BaseModel):
    """Vacancy/application funnel transition payload."""

    status: ApplicationOutcomeStatus
    note: str | None = Field(None, max_length=5000)
    source: str = Field("user", max_length=32)


class SavedVacancyIn(BaseModel):
    """Payload for saving a vacancy into the current career plan."""

    hh_vacancy_id: str = Field(..., max_length=50)
    title: str = Field(..., min_length=1, max_length=500)
    url: str | None = Field(None, max_length=512)
    note: str | None = Field(None, max_length=5000)
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class CareerActionOut(BaseModel):
    """Career action response payload."""

    id: int
    title: str
    description: str | None = None
    action_type: str
    status: str
    priority: int
    skill_name: str | None = None
    hh_vacancy_id: str | None = None
    vacancy_title: str | None = None
    vacancy_url: str | None = None
    recommendation_source: str | None = None
    dataset_run_id: str | None = None
    reason: str | None = None
    expected_impact: str | None = None
    effort_estimate: str | None = None
    due_date: date | None = None
    review_date: date | None = Field(None, description="Recommended date to review the action progress")
    evidence: dict[str, Any] | None = None
    application_status: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class CareerPlanOut(BaseModel):
    """Career plan response payload."""

    telegram_user_id: int
    target_role: str | None = None
    target_grade: str | None = None
    target_city_tier: str | None = None
    target_country: str | None = None
    target_region: str | None = None
    target_city: str | None = None
    target_geo_scope: str | None = None
    target_work_mode: str | None = None
    target_domain: str | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime
    actions: list[CareerActionOut] = Field(default_factory=list)


class MetaRolesResponse(BaseModel):
    """List of available roles in the processed market data."""

    roles: list[str] = Field(default_factory=list, description="Available primary roles")


class MetaGradesResponse(BaseModel):
    """List of available grades."""

    grades: list[str] = Field(default_factory=list, description="Available grades")


class MetaCityTiersResponse(BaseModel):
    """List of supported city tiers."""

    city_tiers: list[str] = Field(default_factory=list, description="Available city tiers")


class MetaCountriesResponse(BaseModel):
    """List of available normalized countries."""

    countries: list[str] = Field(default_factory=list, description="Available normalized countries")


class MetaRegionsResponse(BaseModel):
    """List of available normalized regions."""

    regions: list[str] = Field(default_factory=list, description="Available normalized regions")


class MetaCitiesResponse(BaseModel):
    """List of available normalized cities."""

    cities: list[str] = Field(default_factory=list, description="Available normalized cities")


class MetaGeoScopesResponse(BaseModel):
    """List of available geography scopes."""

    geo_scopes: list[str] = Field(default_factory=list, description="Available geography scopes")


class DatasetMetaResponse(BaseModel):
    """Metadata about the current dataset snapshot loaded by DataStore."""

    model_config = ConfigDict(extra="allow")

    created_at: str | None = Field(None, description="ISO datetime of dataset creation")
    vacancy_count: int | None = Field(None, description="Total vacancy rows in dataset")
    source: str | None = Field(None, description="Data source identifier (e.g. hh)")
    source_kind: str | None = Field(None, description="Operational source kind for the dataset")
    dataset_semantic_type: str | None = Field(None, description="Business meaning of the dataset snapshot")
    requested_date_from: str | None = Field(None, description="Requested source publication date lower bound")
    requested_date_to: str | None = Field(None, description="Requested source publication date upper bound")
    observed_published_at_from: str | None = Field(None, description="Observed publication date lower bound")
    observed_published_at_to: str | None = Field(None, description="Observed publication date upper bound")
    date_semantics_status: str | None = Field(None, description="Date-semantics validation status")
    features_path: str | None = Field(None, description="Path to features parquet file")
    market_view_path: str | None = Field(None, description="Path to market view parquet file")
    dataset_meta_path: str | None = Field(None, description="Path to dataset_meta.json")


class MetaWorkModesResponse(BaseModel):
    """List of supported work modes."""

    work_modes: list[str] = Field(default_factory=list, description="Available work modes")


class MetaDomainsResponse(BaseModel):
    """List of available domains if present in the market view."""

    domains: list[str] = Field(default_factory=list, description="Available domains")


class MetaSkillsResponse(BaseModel):
    """List of skills discovered in the feature set."""

    skills: list[str] = Field(default_factory=list, description="Available skills")


class PaginatedMetaSkillsResponse(BaseModel):
    """Paginated list of skills with optional search filter."""

    skills: list[str] = Field(default_factory=list, description="Available skills (paginated)")
    total: int = Field(..., description="Total number of skills matching the query")
    limit: int = Field(..., description="Maximum number of results per page")
    offset: int = Field(..., description="Offset of the current page")


class SegmentFilters(BaseModel):
    """Filters that define a market segment."""

    role: str | None = Field(None, description="Primary role filter")
    grade: str | None = Field(None, description="Grade filter")
    city_tier: str | None = Field(None, description="City tier filter")
    country: str | None = Field(None, description="Country filter")
    region: str | None = Field(None, description="Region filter")
    city: str | None = Field(None, description="Normalized city filter")
    geo_scope: str | None = Field(None, description="Market geography scope filter")
    work_mode: str | None = Field(None, description="Preferred work mode filter")
    domain: str | None = Field(None, description="Domain filter")


class SegmentSummary(AnalyticalTrustFields):
    """Summary statistics for a market segment."""

    vacancy_count: int = Field(..., description="Total number of vacancies in the segment")
    min_market_n: int | None = Field(None, description="Minimal stable market sample size")
    salary_sample_size: int | None = Field(None, description="Sample size with disclosed salary")
    salary_coverage_share: float | None = Field(None, description="Share of vacancies with disclosed salary")
    salary_median: float | None = Field(None, description="Average median salary across the segment")
    salary_q25: float | None = Field(None, description="Average 25th percentile salary across the segment")
    salary_q75: float | None = Field(None, description="Average 75th percentile salary across the segment")
    junior_friendly_share: float | None = Field(None, description="Average junior-friendly share")
    remote_share: float | None = Field(None, description="Average share of remote vacancies")
    geo_scope: str | None = Field(None, description="Resolved market geography scope")
    median_tech_stack_size: float | None = Field(None, description="Average median tech stack size")
    top_skills: list[str] | None = Field(None, description="Top skills for the segment ordered by demand")
    warnings: list[str] = Field(default_factory=list, description="Non-blocking warnings for the segment")


class SkillDemandEntry(BaseModel):
    """Single skill demand datapoint with market share."""

    skill_name: str = Field(..., description="Canonical skill name")
    market_share: float = Field(..., description="Share of vacancies requiring the skill")
    skill_name_raw: str | None = Field(None, description="Original skill column used for computation")


class SkillGapEntry(SkillDemandEntry):
    """Skill demand enriched with persona possession flag and gap indicator."""

    persona_has: bool = Field(..., description="Whether persona already has the skill")
    gap: bool = Field(..., description="True when the skill is missing and in demand")


class MarketSummary(AnalyticalTrustFields):
    """Aggregated stats for the persona's target market segment."""

    vacancy_count: int = Field(..., description="Number of vacancies in the filtered segment")
    salary_sample_size: int | None = Field(None, description="Sample size with disclosed salary")
    salary_coverage_share: float | None = Field(None, description="Share of vacancies with disclosed salary")
    min_market_n: int | None = Field(None, description="Minimal stable market sample size")
    salary_median: float | None = Field(None, description="Median salary for the segment")
    salary_q25: float | None = Field(None, description="25th percentile salary")
    salary_q75: float | None = Field(None, description="75th percentile salary")
    remote_share: float | None = Field(None, description="Share of remote vacancies")
    geo_scope: str | None = Field(None, description="Resolved market geography scope")
    junior_friendly_share: float | None = Field(None, description="Share of junior-friendly vacancies")
    top_skills: list[str] | None = Field(None, description="Top skills for the segment ordered by demand")


class SkillResource(BaseModel):
    """A learning resource for a particular skill."""

    title: str = Field(..., description="Resource title")
    url: str = Field(..., description="URL of the resource")
    type: Literal["course", "docs", "practice", "book"] = Field(..., description="Resource type")


class PersonaAnalysisResponse(AnalyticalTrustFields):
    """Response payload for persona analysis results."""

    market_summary: MarketSummary
    recommended_skills: list[str]
    top_skill_demand: list[SkillDemandEntry]
    skill_gap: list[SkillGapEntry]
    warnings: list[str]
    filters_used: dict[str, Any]
    skill_resources: dict[str, list[SkillResource]] = Field(
        default_factory=dict,
        description="Learning resources for recommended skills (Sprint-008 TASK-08)",
    )


class WeeklySubscriptionIn(BaseModel):
    """Weekly digest subscription payload for upsert."""

    active: bool = Field(default=True, description="Flag indicating whether the subscription is active")
    weekday: int = Field(..., ge=0, le=6, description="Weekday number where Monday=0 and Sunday=6")
    time_local: str = Field(..., description="Local time in HH:MM format for sending the digest")
    timezone: str = Field(..., description="IANA timezone name for the local time interpretation")
    source: str | None = Field(None, max_length=32, description="Product event source: web, bot, api or digest")


class WeeklySubscriptionOut(BaseModel):
    """Weekly digest subscription response payload."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    active: bool = Field(..., description="Whether the subscription is active")
    weekday: int = Field(..., description="Weekday number where Monday=0 and Sunday=6")
    time_local: str = Field(..., description="Local time in HH:MM format")
    timezone: str = Field(..., description="IANA timezone name")
    last_sent_at: datetime | None = Field(None, description="Timestamp of the last sent digest in UTC")


class ClaimedSubscription(BaseModel):
    """Represents a claimed subscription ready for delivery."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    weekday: int = Field(..., description="Weekday number where Monday=0 and Sunday=6")
    time_local: str = Field(..., description="Local time in HH:MM format")
    timezone: str = Field(..., description="IANA timezone name")
    lock: str = Field(..., description="Opaque lock token required for ack operations")
    attempt: int = Field(..., description="Attempt counter since last successful send")
    last_sent_at: datetime | None = Field(None, description="Timestamp of the last sent digest in UTC")


class DueSubscription(BaseModel):
    """Represents a subscription that is due for sending."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    weekday: int = Field(..., description="Weekday number where Monday=0 and Sunday=6")
    time_local: str = Field(..., description="Local time in HH:MM format")
    timezone: str = Field(..., description="IANA timezone name")
    last_sent_at: datetime | None = Field(None, description="Timestamp of the last sent digest in UTC")


class DueSubscriptionsResponse(BaseModel):
    """Response containing subscriptions that should be processed."""

    subscriptions: list[DueSubscription] = Field(default_factory=list, description="List of due subscriptions")


class MarkSentRequest(BaseModel):
    """Request payload to mark a subscription digest as sent."""

    now_utc: datetime | None = Field(None, description="UTC timestamp to use for mark-sent; defaults to current time")


class ClaimSubscriptionsRequest(BaseModel):
    """Request payload to claim due subscriptions with locking."""

    now_utc: datetime | None = Field(None, description="Override current UTC time used for due calculation")
    stale_lock_seconds: int = Field(
        900,
        ge=0,
        description="Lock age in seconds after which a subscription can be reclaimed",
    )


class ClaimSubscriptionsResponse(BaseModel):
    """Response containing claimed subscriptions for processing."""

    subscriptions: list[ClaimedSubscription] = Field(
        default_factory=list, description="List of subscriptions locked for processing"
    )


class AckSubscriptionRequest(BaseModel):
    """Request payload to acknowledge subscription processing result."""

    telegram_user_id: int = Field(..., description="Telegram user id")
    lock: str = Field(..., description="Lock token acquired via claim endpoint")
    now_utc: datetime | None = Field(None, description="UTC timestamp to use for ack; defaults to current time")
    text_preview: str | None = Field(
        None,
        max_length=500,
        description="First 500 chars of digest text (Sprint-011 TASK-12)",
    )


class DigestPreviewResponse(AnalyticalTrustFields):
    """Preview of the digest message for a user."""

    format: Literal["HTML", "Markdown"] = Field(..., description="Markup format of the digest content")
    text: str = Field(..., description="Digest body ready for sending without additional formatting")


# ---------------------------------------------------------------------------
# DigestHistory schemas (Sprint-007 TASK-07)
# ---------------------------------------------------------------------------


class DigestHistoryItem(BaseModel):
    """Single entry in the user's digest send history."""

    id: int = Field(..., description="Record id")
    sent_at: datetime = Field(..., description="UTC timestamp of successful digest send")
    format: str = Field(..., description="Markup format used (HTML/Markdown)")
    text_preview: str | None = Field(None, description="First 500 characters of digest text")
    attempt: int = Field(..., description="Attempt number at the time of send")


class DigestHistoryResponse(BaseModel):
    """Paginated digest history for a user."""

    items: list[DigestHistoryItem] = Field(default_factory=list, description="Digest history items")
    total: int = Field(..., description="Total number of history records")


# ---------------------------------------------------------------------------
# Search schemas (Sprint-008 TASK-04)
# ---------------------------------------------------------------------------


class VacancySearchResult(AnalyticalTrustFields):
    """Single vacancy search result."""

    hh_vacancy_id: str = Field(..., description="HH.ru vacancy id")
    title: str = Field(..., description="Vacancy title")
    primary_role: str | None = Field(None, description="Detected primary role")
    grade: str | None = Field(None, description="Detected grade")
    city: str | None = Field(None, description="City of the vacancy")
    city_tier: str | None = Field(None, description="City tier of the vacancy")
    country: str | None = Field(None, description="Normalized country of the vacancy")
    region: str | None = Field(None, description="Normalized region of the vacancy")
    city_normalized: str | None = Field(None, description="Normalized city of the vacancy")
    geo_scope: str | None = Field(None, description="Vacancy geography scope")
    salary_from: int | None = Field(None, description="Salary lower bound")
    salary_to: int | None = Field(None, description="Salary upper bound")
    skills: list[str] = Field(default_factory=list, description="Required skills")
    url: str | None = Field(None, description="Original vacancy URL")
    hh_url: str | None = Field(None, description="Original HH.ru vacancy URL")
    published_at: datetime | None = Field(None, description="Publication timestamp")
    fit_reason: str | None = Field(None, description="Optional explanation why the vacancy matches the profile")
    gap_reason: str | None = Field(None, description="Optional explanation of skill gaps for the vacancy")
    plan_relevance: str | None = Field(None, description="Explanation of how the vacancy connects to the career plan")
    matched_skills: list[str] = Field(default_factory=list, description="Vacancy skills already present in profile")
    missing_skills: list[str] = Field(default_factory=list, description="Vacancy skills absent from the profile")
    match_score: int | None = Field(None, ge=0, le=100, description="Profile/vacancy match score from 0 to 100")
    match_level: Literal["high", "medium", "low", "unknown"] | None = Field(
        None,
        description="Coarse match quality label",
    )


class VacancySearchResponse(AnalyticalTrustFields):
    """Vacancy full-text search response."""

    results: list[VacancySearchResult] = Field(default_factory=list, description="Matching vacancies")
    total: int = Field(..., description="Total number of results")
    query: str = Field(..., description="Original search query")
    index_status: str | None = Field(None, description="Current vacancy search index status")
    index_dataset_run_id: str | None = Field(None, description="Dataset run id last confirmed by search indexing")
    search_state: Literal["ready", "degraded", "fallback", "unavailable"] = Field(
        "ready",
        description="Operational state of vacancy search results",
    )
    degraded_reason: str | None = Field(None, description="Reason why search results may be incomplete")
    warnings: list[str] = Field(default_factory=list, description="Search trust/degradation warnings")


EvidenceTask = Literal[
    "skill_gap_explanation",
    "career_action_draft",
    "vacancy_fit_explanation",
    "market_change_summary",
    "fallback_copy",
]
EvidenceSurface = Literal["web", "bot", "api", "worker"]
EvidenceExplainerStatus = Literal["answered", "fallback", "blocked", "disabled"]
EvidenceSearchState = Literal["ready", "degraded", "fallback", "unavailable"]


class EvidenceDatasetContext(AnalyticalTrustFields):
    """Dataset lineage and product eligibility attached to an evidence packet."""

    pass


class EvidenceUserContext(BaseModel):
    """PII-minimized user context allowed in explainer prompts and deterministic copy."""

    target_role: str | None = None
    target_grade: str | None = None
    target_city_tier: str | None = None
    target_country: str | None = None
    target_region: str | None = None
    target_city: str | None = None
    target_geo_scope: str | None = None
    target_work_mode: str | None = None
    target_domain: str | None = None
    current_skills: list[str] = Field(default_factory=list)
    profile_quality: ProfileQualityOut


class EvidencePlanActionContext(BaseModel):
    """Career-plan action context allowed in an evidence packet."""

    action_id: int
    title: str
    action_type: str
    status: str
    priority: int
    skill_name: str | None = None
    hh_vacancy_id: str | None = None
    vacancy_title: str | None = None
    recommendation_source: str | None = None
    dataset_run_id: str | None = None
    reason: str | None = None
    evidence: dict[str, Any] | None = None


class EvidencePlanContext(BaseModel):
    """Career-plan context included in an evidence packet."""

    status: str | None = None
    action_count: int = 0
    next_actions: list[EvidencePlanActionContext] = Field(default_factory=list)


class EvidenceSearchContext(BaseModel):
    """Search/index runtime state included in an evidence packet."""

    search_state: EvidenceSearchState = "ready"
    index_status: str | None = None
    degraded_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """One factual claim that can be referenced by an explainer output."""

    evidence_id: str
    evidence_type: str
    source: str
    claim: str
    value: Any | None = None
    unit: str | None = None
    confidence: str | None = None
    dataset_run_id: str | None = None
    generated_at_utc: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceOutputConstraints(BaseModel):
    """Boundaries that consumers must respect when turning evidence into copy."""

    language: Literal["ru"] = "ru"
    max_bullets: int = Field(3, ge=1, le=5)
    require_evidence_refs: bool = True
    allowed_tasks: list[EvidenceTask] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)


class EvidencePacketOut(BaseModel):
    """Bounded runtime contract for evidence-backed AI or deterministic explainers."""

    version: str = "evidence_packet.v1"
    task: EvidenceTask
    surface: EvidenceSurface
    telegram_user_id: int
    profile: EvidenceUserContext
    dataset: EvidenceDatasetContext
    market_summary: MarketSummary | None = None
    skill_gap: list[SkillGapEntry] = Field(default_factory=list)
    recommended_skills: list[str] = Field(default_factory=list)
    plan: EvidencePlanContext = Field(default_factory=EvidencePlanContext)
    search: EvidenceSearchContext = Field(default_factory=EvidenceSearchContext)
    output_constraints: EvidenceOutputConstraints
    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceRefOut(BaseModel):
    """Reference from explainer copy to a packet evidence item."""

    evidence_id: str
    claim: str


class EvidenceExplainerOut(BaseModel):
    """Deterministic bounded explainer output for web/bot surfaces."""

    version: str = "evidence_explainer.v1"
    packet_version: str
    task: EvidenceTask
    surface: EvidenceSurface
    status: EvidenceExplainerStatus
    answer: str
    bullets: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRefOut] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)
    human_review_required: bool = False


class SkillSearchResponse(BaseModel):
    """Skill search autocomplete response."""

    skills: list[str] = Field(default_factory=list, description="Matching skill names")
    total: int = Field(..., description="Total number of matching skills")


class IndexerStatusOut(BaseModel):
    """Persistent vacancy indexer status."""

    status: str
    source: str | None = None
    dataset_run_id: str | None = None
    served_dataset_run_id: str | None = None
    active_dataset_run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    inserted: int = 0
    indexed: int = 0
    error_msg: str | None = None


class DataRunStateUpdateIn(BaseModel):
    """Admin request for updating data pipeline run state."""

    state: str
    source: str | None = None
    raw_rows: int | None = None
    processed_rows: int | None = None
    error_msg: str | None = None
    dataset_meta_path: str | None = None
    manifest_uri: str | None = None
    quality_report_uri: str | None = None
    artifact_uris: dict[str, Any] | None = None
    raw_quality_report: dict[str, Any] | None = None
    processed_quality_report: dict[str, Any] | None = None
    product_eligibility: dict[str, Any] | None = None
    source_capability_ref: dict[str, Any] | None = None


class DataRunOut(BaseModel):
    """Persistent end-to-end data pipeline run status."""

    run_id: str
    state: str
    source: str | None = None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    raw_rows: int | None = None
    processed_rows: int | None = None
    error_msg: str | None = None
    dataset_meta_path: str | None = None
    manifest_uri: str | None = None
    quality_report_uri: str | None = None
    artifact_uris: dict[str, Any] | None = None
    raw_quality_report: dict[str, Any] | None = None
    processed_quality_report: dict[str, Any] | None = None
    product_eligibility: dict[str, Any] | None = None
    source_capability_ref: dict[str, Any] | None = None


class DataRunStatusOut(BaseModel):
    """Latest data pipeline run wrapper."""

    state: str
    latest: DataRunOut | None = None


class ActiveDatasetOut(BaseModel):
    """Transactional active dataset pointer."""

    run_id: str
    activated_at: datetime
    source: str | None = None
    dataset_meta_path: str | None = None
    manifest_uri: str | None = None
    quality_report_uri: str | None = None
    raw_rows: int | None = None
    processed_rows: int | None = None
    run: DataRunOut | None = None


class ActiveDatasetStatusOut(BaseModel):
    """Active published dataset wrapper."""

    state: str
    active: ActiveDatasetOut | None = None


class TrendDataPoint(BaseModel):
    week_start: date
    value: float
    dataset_run_id: str | None = None
    coverage_window: str | None = None
    completeness: str | float | bool | None = None
    is_complete: bool | None = None
    source_row_count: int | None = None
    confidence: str | None = None


class TrendTrustFields(AnalyticalTrustFields):
    """Trust and claim state for trend-like responses."""

    claim_status: Literal["ready", "blocked"] = Field("ready", description="Whether trend claims may be shown")
    warnings: list[str] = Field(default_factory=list, description="Trend claim warnings or block reasons")


class SalaryTrendOut(TrendTrustFields):
    role: str
    grade: str
    metric: str = "p50"
    currency: str = "RUB"
    data: list[TrendDataPoint] = Field(default_factory=list)


class SkillDemandTrendOut(TrendTrustFields):
    skill: str
    role: str | None = None
    data: list[TrendDataPoint] = Field(default_factory=list)


class VacancyCountTrendOut(TrendTrustFields):
    role: str
    grade: str | None = None
    data: list[TrendDataPoint] = Field(default_factory=list)


class CareerTrajectoryOut(BaseModel):
    current_role: str
    current_grade: str
    next_grade: str
    salary_current_p50: float | None = None
    salary_next_p50: float | None = None
    salary_delta_pct: float | None = None
    skills_to_add: list[str] = Field(default_factory=list)
    weeks_trend: int = 12


class CareerTransitionOut(BaseModel):
    from_grade: str
    to_grade: str
    skills_to_add: list[str] = Field(default_factory=list)
    salary_delta_pct: float | None = None
    demand_trend: str = "stable"


class CareerGraphOut(BaseModel):
    role: str
    transitions: list[CareerTransitionOut] = Field(default_factory=list)


class ResumeUploadOut(BaseModel):
    uploaded: bool = True
    telegram_user_id: int | None = None
    s3_key: str
    original_filename: str
    content_type: str | None = None
    file_size_bytes: int
    uploaded_at: datetime | None = None
    extracted_skills: list[str] = Field(default_factory=list)


class ResumeStatusOut(BaseModel):
    uploaded: bool
    telegram_user_id: int | None = None
    s3_key: str | None = None
    original_filename: str | None = None
    content_type: str | None = None
    file_size_bytes: int | None = None
    uploaded_at: datetime | None = None
    extracted_skills: list[str] = Field(default_factory=list)
    presigned_url: str | None = None


class ResumePresignedUrlOut(BaseModel):
    url: str
    ttl: int


# ---------------------------------------------------------------------------
# Per-user API Keys schemas (Sprint-011 TASK-02 / ADR-008)
# ---------------------------------------------------------------------------


class UserApiKeyOut(BaseModel):
    """Response for newly created API key — plaintext returned only once."""

    key: str = Field(..., description="Full API key (only returned at creation)")
    key_prefix: str = Field(..., description="First 8 characters for hint display")
    created_at: datetime = Field(..., description="Creation timestamp UTC")


class UserApiKeyStatusOut(BaseModel):
    """Status of active API key without exposing plaintext."""

    key_prefix: str = Field(..., description="First 8 characters for hint display")
    created_at: datetime = Field(..., description="Creation timestamp UTC")
    last_used_at: datetime | None = Field(None, description="Last successful auth timestamp")
    is_active: bool = Field(..., description="False if key has been revoked")


class UserApiKeyRevokeOut(BaseModel):
    """Confirmation of API key revocation."""

    revoked: bool = Field(..., description="True when key was revoked")
    revoked_at: datetime = Field(..., description="Revocation timestamp UTC")
